import os
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, status, Header, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

from .auth import AdminContext, AuthSettings, get_current_admin, get_current_user, provide_auth_settings, verify_token
from .localdb import LocalDBError, LocalDBConfig, LocalQuoteStore
from .mongostore import MongoConfig, MongoDBError, MongoQuoteStore
from .models import QuoteCreate, QuoteListResponse, QuoteResponse, User, UserStatus

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
    admin_name: str = Field(default="Admin", alias="ADMIN_NAME")

    model_config = {"arbitrary_types_allowed": True, "populate_by_name": True, "extra": "ignore"}

    @property
    def admin_emails(self) -> list[str]:
        return [e.strip() for e in self.admin_emails_raw.split(",") if e.strip()]

    @property
    def admin_creds(self) -> dict[str, str]:
        """Returns a mapping of admin email to password."""
        creds = {}
        # Try ADMIN_CREDENTIALS first if it exists in env
        creds_raw = os.environ.get("ADMIN_CREDENTIALS", "")
        if creds_raw:
            for pair in creds_raw.split(","):
                if ":" in pair:
                    email, password = pair.split(":", 1)
                    creds[email.strip().lower()] = password.strip()
        
        # Fallback to ADMIN_EMAILS and ADMIN_PASSWORD
        if not creds and self.admin_password:
            emails = self.admin_emails
            # Check if admin_password itself is a comma-separated list
            passwords = [p.strip() for p in self.admin_password.split(",")]
            
            if len(passwords) == len(emails):
                # Matching pairs
                for e, p in zip(emails, passwords):
                    creds[e.lower()] = p
            else:
                # One password for all (use the first one if multiple provided incorrectly)
                p = passwords[0]
                for e in emails:
                    creds[e.lower()] = p
        return creds


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    load_dotenv(dotenv_path=dotenv_path, override=False)
    return Settings(**os.environ)


async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.local_mode:
        print(f"🚀 Starting in LOCAL MODE. Using database: {settings.local_db_path}")
        store = LocalQuoteStore(LocalDBConfig(path=settings.local_db_path))
        
        # Ensure .env admins exist in DB (unified users table)
        for email, password in settings.admin_creds.items():
            existing = await store.get_user_by_email(email, is_admin=False)
            if not existing:
                await store.create_user(User(
                    email=email,
                    password=password,
                    admin_name=settings.admin_name,
                    status=UserStatus.APPROVED,
                    is_admin=True
                ))
            elif not existing.is_admin:
                # User exists but is not admin - upgrade them
                await store.set_user_admin(email, True)
        
        app.state.db_client = store
        yield
        return

    print(f"🌍 Starting in PRODUCTION MODE. Connecting to MongoDB...")
    if not settings.mongodb_uri:
        print("❌ Error: MONGODB_URI is not set. Production mode will fail.")
        # We still yield to let the app start (so logs can be seen), 
        # but routes will fail with 500 when accessing DB.
        app.state.db_client = None
        yield
        return

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
        # We skip ensure_indexes() and admin sync here because they are slow 
        # and should be handled by migration/deployment scripts, not every cold start.
        
        print(f"✅ Connected to MongoDB: {settings.mongodb_db}")
        app.state.db_client = store
        yield
    finally:
        mongo_client.close()


app = FastAPI(title="Dan Quotes Service", lifespan=lifespan)

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
templates.env.globals["settings"] = get_settings()
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


def get_db_client(request: Request) -> QuoteStore:
    return request.app.state.db_client


def format_datetime(value: object) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            from datetime import datetime
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value.strftime("%Y-%m-%d %H:%M")


templates.env.filters["format_datetime"] = format_datetime


# Helpers -------------------------------------------------------------
def handle_db_error(exc: Exception):
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


async def get_user(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    admin_token: Optional[str] = Cookie(default=None, alias="admin_token"),
    settings: AuthSettings = Depends(provide_auth_settings),
    db: QuoteStore = Depends(get_db_client),
) -> AdminContext:
    """A wrapper for get_current_user that ensures the DB client is passed."""
    return await get_current_user(
        authorization=authorization,
        admin_token=admin_token,
        settings=settings,
        db=db
    )


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
async def submit_form(
    request: Request,
    db: QuoteStore = Depends(get_db_client),
):
    admin_token = request.cookies.get("admin_token")
    if not admin_token:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_302_FOUND)

    try:
        # Manually invoke the dependency logic to handle redirection
        user = await get_current_user(
            authorization=None,
            admin_token=admin_token,
            settings=provide_auth_settings(),
            db=db
        )
    except HTTPException as exc:
        if exc.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN):
            return RedirectResponse(url="/admin/login", status_code=status.HTTP_302_FOUND)
        raise

    return templates.TemplateResponse("submit.html", {"request": request, "user": user})


@app.post("/submit")
async def submit_quote_form(
    request: Request,
    content: str = Form(...),
    submitted_by: str = Form(...),
    source: str = Form("web_form"),
    db: QuoteStore = Depends(get_db_client),
    user: AdminContext = Depends(get_user),
):
    content_clean = content.strip()
    submitted_by_clean = submitted_by.strip()
    if not content_clean:
        raise HTTPException(status_code=400, detail="Content is required")
    if not submitted_by_clean:
        raise HTTPException(status_code=400, detail="Submitted by is required")
    try:
        quote = await db.create_quote(
            content=content_clean,
            content_hash=db.content_hash(content_clean),
            source=source,
            status="PENDING",
            submitted_by=submitted_by_clean,
        )
    except (MongoDBError, LocalDBError) as exc:
        handle_db_error(exc)
    return templates.TemplateResponse(
        "submit_success.html", {"request": request, "quote": quote}, status_code=status.HTTP_201_CREATED
    )


@app.get("/admin", response_class=HTMLResponse)
async def admin_queue(
    request: Request,
    mode: str = Query("moderation"),
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
        claims = await verify_token(token, auth_settings, db=db)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            return RedirectResponse(url="/admin/login", status_code=status.HTTP_302_FOUND)
        raise

    email = claims.get("email") or "local-admin"
    name = claims.get("name")
    is_admin = claims.get("is_admin", False)
    admin = AdminContext(email=email, token=token, claims=claims, name=name, is_admin=is_admin)

    # Force regular users into archive mode if they try to access moderation/users
    if not is_admin and mode != "archive":
        mode = "archive"

    try:
        if mode == "archive" and is_admin:
            # Fetch all records (Pending, Approved, Rejected) to show in the admin dashboard
            quotes = await db.list_quotes(status=None, limit=200)
            users = []
        elif mode == "users" and is_admin:
            # Fetch all users for moderation
            users = await db.list_users()
            quotes = QuoteListResponse(items=[], next_cursor=None)
        elif mode == "moderation" and is_admin:
            # Default: Moderation mode - only pending
            quotes = await db.list_quotes(status="PENDING", limit=100)
            users = []
        else:
            # Regular user or invalid mode: no lists
            quotes = QuoteListResponse(items=[], next_cursor=None)
            users = []
    except (MongoDBError, LocalDBError) as exc:
        handle_db_error(exc)
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request, 
            "quotes": quotes.items, 
            "users": users,
            "admin_name": admin.name, 
            "admin_email": admin.email,
            "is_admin": is_admin,
            "mode": mode
        },
    )


@app.get("/register", response_class=HTMLResponse)
async def register_form(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.post("/register")
async def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    name: str = Form(...),
    db: QuoteStore = Depends(get_db_client),
):
    existing = await db.get_user_by_email(email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    user = User(
        email=email,
        password=password,
        admin_name=name,
        status=UserStatus.PENDING,
        is_admin=False
    )
    await db.create_user(user)
    return templates.TemplateResponse("register_success.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return RedirectResponse(url="/admin/login")


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_form(request: Request):
    settings = get_settings()
    return templates.TemplateResponse("admin_login.html", {"request": request, "local_mode": settings.local_mode})


@app.post("/admin/login")
async def admin_login(
    request: Request,
    email: Optional[str] = Form(None),
    token: str = Form(...),
    as_admin: bool = Form(False),
    settings: Settings = Depends(get_settings),
    db: QuoteStore = Depends(get_db_client),
):
    email_clean = (email or "").strip().lower()
    
    if not email_clean:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email is required")
    
    # Try .env admins first if logging in as admin
    creds = settings.admin_creds
    if as_admin and email_clean in creds and token == creds[email_clean]:
        cookie_value = f"{email_clean}:{token}:admin"
    else:
        # Check database - unified users collection
        user = await db.get_user_by_email(email_clean, is_admin=False)
        if not user or user.password != token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
        
        # If trying to login as admin but user is not admin, reject
        if as_admin and not user.is_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not an admin")
        
        # Use actual role from database
        role = "admin" if user.is_admin else "user"
        cookie_value = f"{email_clean}:{token}:{role}"

    resp = RedirectResponse(url="/admin", status_code=status.HTTP_302_FOUND)
    settings = get_settings()
    resp.set_cookie(
        key="admin_token", 
        value=cookie_value, 
        httponly=True, 
        samesite="lax",
        secure=not settings.local_mode
    )
    return resp


async def get_admin(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    admin_token: Optional[str] = Cookie(default=None, alias="admin_token"),
    settings: AuthSettings = Depends(provide_auth_settings),
    db: QuoteStore = Depends(get_db_client),
) -> AdminContext:
    """A wrapper for get_current_admin that ensures the DB client is passed."""
    return await get_current_admin(
        authorization=authorization,
        admin_token=admin_token,
        settings=settings,
        db=db
    )


@app.post("/admin/users/{email}/approve")
async def admin_approve_user(
    email: str,
    admin: AdminContext = Depends(get_current_admin),
    db: QuoteStore = Depends(get_db_client),
):
    try:
        await db.update_user_status(email, UserStatus.APPROVED)
    except (MongoDBError, LocalDBError) as exc:
        handle_db_error(exc)
    return RedirectResponse(url="/admin?mode=users", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/users/{email}/reject")
async def admin_reject_user(
    email: str,
    admin: AdminContext = Depends(get_current_admin),
    db: QuoteStore = Depends(get_db_client),
):
    try:
        await db.delete_user(email)
    except (MongoDBError, LocalDBError) as exc:
        handle_db_error(exc)
    return RedirectResponse(url="/admin?mode=users", status_code=status.HTTP_303_SEE_OTHER)


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


@app.post("/api/quotes/{quote_id}/like", response_model=QuoteResponse)
async def api_like_quote(quote_id: str, db: QuoteStore = Depends(get_db_client)):
    """Increment the likes count for a quote. No authentication required."""
    try:
        return await db.increment_likes(quote_id)
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
    admin: AdminContext = Depends(get_admin),
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
    admin: AdminContext = Depends(get_admin),
    db: QuoteStore = Depends(get_db_client),
):
    try:
        return await db.update_status(quote_id, status="APPROVED", verified_by=admin.email)
    except (MongoDBError, LocalDBError) as exc:
        handle_db_error(exc)


@app.post("/api/admin/quotes/{quote_id}/reject", response_model=QuoteResponse)
async def api_admin_reject(
    quote_id: str,
    admin: AdminContext = Depends(get_admin),
    db: QuoteStore = Depends(get_db_client),
):
    try:
        return await db.update_status(quote_id, status="REJECTED", verified_by=admin.email)
    except (MongoDBError, LocalDBError) as exc:
        handle_db_error(exc)


@app.post("/admin/logout")
async def admin_logout():
    resp = RedirectResponse(url="/admin/login", status_code=status.HTTP_302_FOUND)
    resp.delete_cookie(key="admin_token")
    return resp


# Web Admin Actions ----------------------------------------------------
@app.post("/admin/update/{quote_id}")
async def admin_update_web(
    request: Request,
    quote_id: str,
    content: str = Form(...),
    submitted_by: str = Form(...),
    action: str = Form(...),
    admin: AdminContext = Depends(get_admin),
    db: QuoteStore = Depends(get_db_client),
):
    status_update = None
    if action == "approve":
        status_update = "APPROVED"
    elif action == "reject":
        status_update = "REJECTED"
    
    try:
        await db.update_quote(
            quote_id, 
            content=content.strip(), 
            submitted_by=submitted_by.strip(),
            status=status_update, 
            verified_by=admin.email
        )
    except (MongoDBError, LocalDBError) as exc:
        handle_db_error(exc)
    
    # Preserve the current mode after redirect
    mode = request.query_params.get("mode", "moderation")
    return RedirectResponse(url=f"/admin?mode={mode}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/approve/{quote_id}")
async def admin_approve_web(
    request: Request,
    quote_id: str,
    content: str = Form(...),
    admin: AdminContext = Depends(get_admin),
    db: QuoteStore = Depends(get_db_client),
):
    # Keep for API compatibility or legacy, but we'll use /admin/update for web
    try:
        await db.update_quote(quote_id, content=content.strip(), status="APPROVED", verified_by=admin.email)
    except (MongoDBError, LocalDBError) as exc:
        handle_db_error(exc)
    
    mode = request.query_params.get("mode", "moderation")
    return RedirectResponse(url=f"/admin?mode={mode}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/reject/{quote_id}")
async def admin_reject_web(
    request: Request,
    quote_id: str,
    admin: AdminContext = Depends(get_admin),
    db: QuoteStore = Depends(get_db_client),
):
    try:
        await db.update_quote(quote_id, status="REJECTED", verified_by=admin.email)
    except (MongoDBError, LocalDBError) as exc:
        handle_db_error(exc)
    
    mode = request.query_params.get("mode", "moderation")
    return RedirectResponse(url=f"/admin?mode={mode}", status_code=status.HTTP_303_SEE_OTHER)
