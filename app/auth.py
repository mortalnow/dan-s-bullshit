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
    def __init__(self, email: str, token: str, claims: dict):
        self.email = email
        self.token = token
        self.claims = claims


class AuthSettings:
    def __init__(
        self,
        jwks_url: Optional[str],
        admin_emails: List[str],
        local_mode: bool,
        admin_password: Optional[str],
    ):
        self.jwks_url = jwks_url
        self.admin_emails = [e.strip().lower() for e in admin_emails if e.strip()]
        self.local_mode = local_mode
        self.admin_password = admin_password


def build_auth_settings(env: dict) -> AuthSettings:
    jwks_url = env.get("INSTANTDB_JWKS_URL") or env.get("INSTANTDB_TOKEN_VERIFY_URL")
    admin_emails = (env.get(ADMIN_EMAILS_ENV) or "").split(",")
    local_raw = (env.get(LOCAL_MODE_ENV) or "").strip().lower()
    local_mode = local_raw in ("1", "true", "yes", "on")
    admin_password = env.get(ADMIN_PASSWORD_ENV)
    return AuthSettings(
        jwks_url=jwks_url,
        admin_emails=admin_emails,
        local_mode=local_mode,
        admin_password=admin_password,
    )


@functools.lru_cache(maxsize=1)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url)


async def verify_token(
    token: str,
    settings: AuthSettings,
) -> dict:
    if settings.local_mode:
        if not settings.admin_password:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ADMIN_PASSWORD not configured for LOCAL_MODE.",
            )
        if token != settings.admin_password:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin password")
        return {"email": "local-admin"}

    if not settings.jwks_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWKS URL not configured; set INSTANTDB_JWKS_URL or INSTANTDB_TOKEN_VERIFY_URL.",
        )
    try:
        signing_key = _jwks_client(settings.jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256", "HS256"],
            options={"verify_aud": False},
        )
        return claims
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def provide_auth_settings() -> AuthSettings:
    env = {
        "INSTANTDB_JWKS_URL": os.getenv("INSTANTDB_JWKS_URL"),
        "INSTANTDB_TOKEN_VERIFY_URL": os.getenv("INSTANTDB_TOKEN_VERIFY_URL"),
        "ADMIN_EMAILS": os.getenv("ADMIN_EMAILS", ""),
        "LOCAL_MODE": os.getenv("LOCAL_MODE", ""),
        "ADMIN_PASSWORD": os.getenv("ADMIN_PASSWORD"),
    }
    return build_auth_settings(env)


async def get_current_admin(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    admin_token: Optional[str] = Cookie(default=None, alias="admin_token"),
    settings: AuthSettings = Depends(provide_auth_settings),
) -> AdminContext:
    token: Optional[str] = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
    elif admin_token:
        token = admin_token

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    claims = await verify_token(token, settings)
    email = (claims.get("email") or "").lower()

    if settings.local_mode:
        return AdminContext(email=email or "local-admin", token=token, claims=claims)

    if not settings.admin_emails:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ADMIN_EMAILS not configured.",
        )
    if email not in settings.admin_emails:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not an admin")
    return AdminContext(email=email, token=token, claims=claims)
