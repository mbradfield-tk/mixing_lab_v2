"""Bearer tokens for the admin principal.

``POST /auth/login`` exchanges the env-configured admin credentials for a signed,
expiring token; write endpoints read it from ``Authorization: Bearer <token>``.
Tokens are signed with ``MIXING_LAB_API_SECRET``; without it a random per-process
secret is used, so tokens stop working when the server restarts.
"""
from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException, status
from itsdangerous import BadSignature, URLSafeTimedSerializer

from core.auth import ANONYMOUS, Principal

SECRET_ENV = "MIXING_LAB_API_SECRET"
TOKEN_TTL_S = 8 * 3600

_serializer = URLSafeTimedSerializer(os.environ.get(SECRET_ENV) or secrets.token_urlsafe(32),
                                     salt="mixing-lab-admin")


def issue_token(principal: Principal) -> str:
    return _serializer.dumps({"sub": principal.name, "admin": principal.is_admin})


def principal_from_token(token: str) -> Principal | None:
    try:
        data = _serializer.loads(token, max_age=TOKEN_TTL_S)
    except BadSignature:  # also covers SignatureExpired
        return None
    return Principal(name=str(data.get("sub", "")), is_admin=bool(data.get("admin")))


def current_principal(authorization: str | None = Header(default=None)) -> Principal:
    """FastAPI dependency: the caller's principal. No header = anonymous; a bad or
    expired token is a 401 so the client knows to log in again."""
    if not authorization:
        return ANONYMOUS
    scheme, _, token = authorization.partition(" ")
    principal = principal_from_token(token.strip()) if scheme.lower() == "bearer" else None
    if principal is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.",
                            headers={"WWW-Authenticate": "Bearer"})
    return principal
