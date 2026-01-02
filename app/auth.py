import functools
import os
from typing import List, Optional

import jwt
from fastapi import Cookie, Depends, Header, HTTPException, status
from jwt import PyJWKClient

ADMIN_EMAILS_ENV = "ADMIN_EMAILS"
LOCAL_MODE_ENV = "LOCAL_MODE"
ADMIN_PASSWORD_ENV = "ADMIN_PASSWORD"


class AdminContext:
    def __init__(self, email: str, token: str, claims: dict, name: Optional[str] = None, is_admin: bool = False, status: str = "APPROVED"):
        self.email = email
        self.token = token
        self.claims = claims
        self.name = name or email.split("@")[0] if "@" in email else email
        self.is_admin = is_admin
        self.status = status


class AuthSettings:
    def __init__(
        self,
        jwks_url: Optional[str],
        admin_emails: List[str],
        local_mode: bool,
        admin_password: Optional[str],
        admin_name: str = "Qiao",
    ):
        self.jwks_url = jwks_url
        self.admin_emails = [e.strip().lower() for e in admin_emails if e.strip()]
        self.local_mode = local_mode
        self.admin_password = admin_password
        self.admin_name = admin_name


def build_auth_settings(env: dict) -> AuthSettings:
    admin_emails = (env.get(ADMIN_EMAILS_ENV) or "").split(",")
    local_raw = (env.get(LOCAL_MODE_ENV) or "").strip().lower()
    local_mode = local_raw in ("1", "true", "yes", "on")
    admin_password = env.get(ADMIN_PASSWORD_ENV)
    admin_name = env.get("ADMIN_NAME", "Qiao")
    return AuthSettings(
        jwks_url=None,
        admin_emails=admin_emails,
        local_mode=local_mode,
        admin_password=admin_password,
        admin_name=admin_name,
    )


@functools.lru_cache(maxsize=1)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url)


async def verify_token(
    token: str,
    settings: AuthSettings,
    db: Optional[object] = None,
) -> dict:
    # Handle role-suffixed tokens from main.py
    role = "user"
    original_token = token
    if ":" in token:
        parts = token.split(":")
        if len(parts) == 3: # email:password:role
            email, password, role = parts
            token = password
        elif len(parts) == 2 and parts[1] in ("admin", "user"): # password:role
            token, role = parts

    if settings.local_mode or role == "admin":
        # Build creds map from environment similar to main.py
        creds = {}
        creds_raw = os.getenv("ADMIN_CREDENTIALS", "")
        if creds_raw:
            for pair in creds_raw.split(","):
                if ":" in pair:
                    e, p = pair.split(":", 1)
                    creds[e.strip().lower()] = p.strip()
        
        if not creds and settings.admin_password:
            emails = settings.admin_emails
            passwords = [p.strip() for p in settings.admin_password.split(",")]
            if len(passwords) == len(emails):
                for e, p in zip(emails, passwords):
                    creds[e.lower()] = p
            else:
                p = passwords[0]
                for e in emails:
                    creds[e.lower()] = p

        # Check if the token (password) matches any admin in .env
        for email, password in creds.items():
            if token == password:
                return {"email": email, "name": settings.admin_name, "is_admin": True, "status": "APPROVED"}
        
        # Fallback for single password case if not already caught
        if settings.admin_password and token == settings.admin_password:
            email = settings.admin_emails[0] if settings.admin_emails else "local-admin"
            return {"email": email, "name": settings.admin_name, "is_admin": True, "status": "APPROVED"}

    # Database Check - look up user in unified collection
    if db and hasattr(db, "get_user_by_email"):
        if ":" in original_token:
            parts = original_token.split(":")
            if len(parts) == 3:
                email, password, role = parts
                # First try to find the user (don't filter by is_admin, check after)
                user = await db.get_user_by_email(email, is_admin=False)
                # If looking for admin but user exists and is not admin, reject
                if user and user.password == password:
                    if role == "admin" and not user.is_admin:
                        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not an admin")
                    status_value = user.status.value if hasattr(user.status, 'value') else user.status
                    return {"email": user.email, "name": user.admin_name, "is_admin": user.is_admin, "status": status_value}

    # Production Mode Logic (JWT)
    if settings.jwks_url:
        try:
            signing_key = _jwks_client(settings.jwks_url).get_signing_key_from_jwt(original_token)
            claims = jwt.decode(
                original_token,
                signing_key.key,
                algorithms=["RS256", "ES256", "HS256"],
                options={"verify_aud": False},
            )
            return claims
        except jwt.PyJWTError:
            pass

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing authentication")


def provide_auth_settings() -> AuthSettings:
    env = {
        "ADMIN_EMAILS": os.getenv("ADMIN_EMAILS", ""),
        "LOCAL_MODE": os.getenv("LOCAL_MODE", ""),
        "ADMIN_PASSWORD": os.getenv("ADMIN_PASSWORD"),
        "ADMIN_NAME": os.getenv("ADMIN_NAME", "Qiao"),
    }
    return build_auth_settings(env)


async def get_current_admin(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    admin_token: Optional[str] = Cookie(default=None, alias="admin_token"),
    settings: AuthSettings = Depends(provide_auth_settings),
    db: Optional[object] = None,  # Can be passed by dependency in main.py
) -> AdminContext:
    token: Optional[str] = None
    
    # Handle both manual calls and FastAPI injection
    auth_str = str(authorization) if authorization and not hasattr(authorization, "default") else None
    cookie_str = str(admin_token) if admin_token and not hasattr(admin_token, "default") else None

    if auth_str and auth_str.lower().startswith("bearer "):
        token = auth_str.split(" ", 1)[1]
    elif cookie_str:
        token = cookie_str

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    claims = await verify_token(token, settings, db=db)
    email = (claims.get("email") or "").lower()
    name = claims.get("name")
    is_admin = claims.get("is_admin", False)
    user_status = claims.get("status", "PENDING")

    if not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not an admin")

    return AdminContext(email=email, token=token, claims=claims, name=name, is_admin=is_admin, status=user_status)


async def get_current_user(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    admin_token: Optional[str] = Cookie(default=None, alias="admin_token"),
    settings: AuthSettings = Depends(provide_auth_settings),
    db: Optional[object] = None,
) -> AdminContext:
    token: Optional[str] = None

    # Handle both manual calls and FastAPI injection
    auth_str = str(authorization) if authorization and not hasattr(authorization, "default") else None
    cookie_str = str(admin_token) if admin_token and not hasattr(admin_token, "default") else None

    if auth_str and auth_str.lower().startswith("bearer "):
        token = auth_str.split(" ", 1)[1]
    elif cookie_str:
        token = cookie_str

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required")
    
    claims = await verify_token(token, settings, db=db)
    email = (claims.get("email") or "").lower()
    name = claims.get("name")
    is_admin = claims.get("is_admin", False)
    user_status = claims.get("status", "PENDING")

    if user_status != "APPROVED" and not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account pending approval")

    return AdminContext(email=email, token=token, claims=claims, name=name, is_admin=is_admin, status=user_status)
