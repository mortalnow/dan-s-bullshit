import os
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

from .auth import AdminContext, get_current_admin, provide_auth_settings, verify_token
from .localdb import LocalDBError, LocalDBConfig, LocalQuoteStore
from .mongostore import MongoConfig, MongoDBError, MongoQuoteStore
from .models import QuoteCreate, QuoteListResponse, QuoteResponse

QuoteStore = MongoQuoteStore | LocalQuoteStore


class Settings(BaseModel):
    local_mode: bool = Field(default=False, alias="LOCAL_MODE")
    local_db_path: str = Field(default="local.db", alias="LOCAL_DB_PATH")
    mongodb_uri: Optional[str] = Field(default=None, alias="MONGODB_URI")
    mongodb_db: str = Field(default="dans-bullshit", alias="MONGODB_DB")
    mongodb_collection: str = Field(default="quotes", alias="MONGODB_COLLECTION")
    instantdb_jwks_url: Optional[str] = Field(default=None, alias="INSTANTDB_JWKS_URL")
    instantdb_token_verify_url: Optional[str] = Field(default=None, alias="INSTANTDB_TOKEN_VERIFY_URL")
    admin_emails_raw: str = Field(default="", alias="ADMIN_EMAILS")
    admin_password: Optional[str] = Field(default=None, alias="ADMIN_PASSWORD")

    model_config = {"arbitrary_types_allowed": True, "populate_by_name": True, "extra": "ignore"}

    @property
    def admin_emails(self) -> list[str]:
        return [e.strip() for e in self.admin_emails_raw.split(",") if e.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    load_dotenv(dotenv_path=dotenv_path, override=False)
    return Settings(**os.environ)


async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.local_mode:
        app.state.db_client = LocalQuoteStore(LocalDBConfig(path=settings.local_db_path))
        yield
        return

    if not settings.mongodb_uri:
        raise RuntimeError("Set MONGODB_URI for production (MongoDB Atlas), or enable LOCAL_MODE=1.")

    mongo_client = AsyncIOMotorClient(settings.mongodb_uri)
    try:
        store = MongoQuoteStore(
            MongoConfig(
                uri=settings.mongodb_uri,
                db=settings.mongodb_db,
                collection=settings.mongodb_collection,
            ),
            mongo_client,
        )
        await store.ensure_indexes()
        app.state.db_client = store
        yield
    finally:
        mongo_client.close()


app = FastAPI(title="Dan Quotes Service", lifespan=lifespan)

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


def strip_outer_quotes(value: object) -> object:
    """Remove one pair of outer quotes (ASCII or Chinese) if both ends match."""
    if not isinstance(value, str):
        return value
    s = value.strip()
    pairs = [("“", "”"), ('"', '"'), ("'", "'")]
    for left, right in pairs:
        if s.startswith(left) and s.endswith(right) and len(s) >= len(left) + len(right):
            return s[len(left) : -len(right)]
    return s


templates.env.filters["strip_outer_quotes"] = strip_outer_quotes


def get_db_client(request: Request) -> QuoteStore:
    return request.app.state.db_client


# Helpers -------------------------------------------------------------
def handle_db_error(exc: Exception):
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


# Web routes ----------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db: QuoteStore = Depends(get_db_client)):
    try:
        quote = await db.random_approved()
    except (MongoDBError, LocalDBError) as exc:
        handle_db_error(exc)
    return templates.TemplateResponse("index.html", {"request": request, "quote": quote})


@app.get("/random", response_class=HTMLResponse)
async def random_quote_page():
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)


@app.get("/submit", response_class=HTMLResponse)
async def submit_form(request: Request):
    return templates.TemplateResponse("submit.html", {"request": request})


@app.post("/submit")
async def submit_quote_form(
    request: Request,
    content: str = Form(...),
    source: str = Form("web_form"),
    db: QuoteStore = Depends(get_db_client),
):
    content_clean = content.strip()
    if not content_clean:
        raise HTTPException(status_code=400, detail="Content is required")
    try:
        quote = await db.create_quote(
            content=content_clean,
            content_hash=db.content_hash(content_clean),
            source=source,
            status="PENDING",
            submitted_by=None,
        )
    except (MongoDBError, LocalDBError) as exc:
        handle_db_error(exc)
    return templates.TemplateResponse(
        "submit_success.html", {"request": request, "quote": quote}, status_code=status.HTTP_201_CREATED
    )


@app.get("/admin", response_class=HTMLResponse)
async def admin_queue(
    request: Request,
    db: QuoteStore = Depends(get_db_client),
):
    settings = get_settings()
    authorization = request.headers.get("authorization")
    admin_token = request.cookies.get("admin_token")
    token: Optional[str] = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
    elif admin_token:
        token = admin_token
    if not token:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_302_FOUND)

    auth_settings = provide_auth_settings()
    try:
        claims = await verify_token(token, auth_settings)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            return RedirectResponse(url="/admin/login", status_code=status.HTTP_302_FOUND)
        raise

    if settings.local_mode:
        admin = AdminContext(email="local-admin", token=token, claims=claims)
    else:
        email = (claims.get("email") or "").lower()
        if not settings.admin_emails:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ADMIN_EMAILS not configured.",
            )
        if email not in settings.admin_emails:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not an admin")
        admin = AdminContext(email=email, token=token, claims=claims)

    try:
        quotes = await db.list_quotes(status="PENDING", limit=100)
    except (MongoDBError, LocalDBError) as exc:
        handle_db_error(exc)
    return templates.TemplateResponse(
        "admin.html",
        {"request": request, "quotes": quotes.items, "admin_email": admin.email},
    )


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_form(request: Request):
    settings = get_settings()
    return templates.TemplateResponse("admin_login.html", {"request": request, "local_mode": settings.local_mode})


@app.post("/admin/login")
async def admin_login(request: Request, token: str = Form(...)):
    resp = RedirectResponse(url="/admin", status_code=status.HTTP_302_FOUND)
    resp.set_cookie(key="admin_token", value=token, httponly=True, samesite="lax")
    return resp


# Public API ----------------------------------------------------------
@app.get("/api/quotes", response_model=QuoteListResponse)
async def api_list_quotes(
    status_param: str = Query(default="APPROVED", alias="status"),
    limit: int = 20,
    cursor: Optional[str] = None,
    db: QuoteStore = Depends(get_db_client),
):
    status_normalized = status_param.upper() if status_param else None
    try:
        return await db.list_quotes(status=status_normalized, limit=limit, cursor=cursor)
    except (MongoDBError, LocalDBError) as exc:
        handle_db_error(exc)


@app.get("/api/quotes/random", response_model=Optional[QuoteResponse])
async def api_random_quote(db: QuoteStore = Depends(get_db_client)):
    try:
        return await db.random_approved()
    except (MongoDBError, LocalDBError) as exc:
        handle_db_error(exc)


@app.get("/api/quotes/{quote_id}", response_model=QuoteResponse)
async def api_get_quote(quote_id: str, db: QuoteStore = Depends(get_db_client)):
    try:
        quote = await db.get_quote(quote_id)
    except (MongoDBError, LocalDBError) as exc:
        handle_db_error(exc)
    if not quote or quote.status != "APPROVED":
        raise HTTPException(status_code=404, detail="Quote not found")
    return quote


@app.get("/api/quotes/latest", response_model=Optional[QuoteResponse])
async def api_latest_quote(
    status_param: str = Query(default=None, alias="status"),
    db: QuoteStore = Depends(get_db_client),
):
    status_normalized = status_param.upper() if status_param else None
    try:
        return await db.latest_quote(status=status_normalized)
    except (MongoDBError, LocalDBError) as exc:
        handle_db_error(exc)


@app.post("/api/quotes", response_model=QuoteResponse, status_code=status.HTTP_201_CREATED)
async def api_create_quote(
    body: QuoteCreate,
    db: QuoteStore = Depends(get_db_client),
):
    content_clean = body.content.strip()
    try:
        return await db.create_quote(
            content=content_clean,
            content_hash=db.content_hash(content_clean),
            source=body.source or "api",
            status="PENDING",
            submitted_by=body.submitted_by,
        )
    except (MongoDBError, LocalDBError) as exc:
        handle_db_error(exc)


# Admin API -----------------------------------------------------------
@app.get("/api/admin/quotes", response_model=QuoteListResponse)
async def api_admin_list_quotes(
    status_param: str = Query(default="PENDING", alias="status"),
    limit: int = 50,
    cursor: Optional[str] = None,
    admin: AdminContext = Depends(get_current_admin),
    db: QuoteStore = Depends(get_db_client),
):
    status_normalized = status_param.upper() if status_param else None
    try:
        return await db.list_quotes(status=status_normalized, limit=limit, cursor=cursor)
    except (MongoDBError, LocalDBError) as exc:
        handle_db_error(exc)


@app.post("/api/admin/quotes/{quote_id}/approve", response_model=QuoteResponse)
async def api_admin_approve(
    quote_id: str,
    admin: AdminContext = Depends(get_current_admin),
    db: QuoteStore = Depends(get_db_client),
):
    try:
        return await db.update_status(quote_id, status="APPROVED", verified_by=admin.email)
    except (MongoDBError, LocalDBError) as exc:
        handle_db_error(exc)


@app.post("/api/admin/quotes/{quote_id}/reject", response_model=QuoteResponse)
async def api_admin_reject(
    quote_id: str,
    admin: AdminContext = Depends(get_current_admin),
    db: QuoteStore = Depends(get_db_client),
):
    try:
        return await db.update_status(quote_id, status="REJECTED", verified_by=admin.email)
    except (MongoDBError, LocalDBError) as exc:
        handle_db_error(exc)
