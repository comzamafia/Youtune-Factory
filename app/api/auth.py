"""API authentication — Bearer token validation + simple login."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.config import settings

_bearer_scheme = HTTPBearer()

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    message: str


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest):
    """Authenticate with username & password, returns Bearer token."""
    if (
        hmac.compare_digest(body.username.encode("utf-8"), settings.admin_username.encode("utf-8"))
        and hmac.compare_digest(body.password.encode("utf-8"), settings.admin_password.encode("utf-8"))
    ):
        return LoginResponse(
            token=settings.api_secret_key,
            message="Login successful",
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid username or password",
    )


async def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> str:
    """
    FastAPI dependency that validates the Bearer token against ``API_SECRET_KEY``.

    Returns the token string if valid; raises 401 otherwise.
    """
    if not hmac.compare_digest(credentials.credentials.encode("utf-8"), settings.api_secret_key.encode("utf-8")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return credentials.credentials
