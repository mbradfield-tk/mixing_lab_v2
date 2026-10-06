"""Server-side admin authentication and the write policy for the databases.

Credentials come only from the environment (``MIXING_LAB_ADMIN_USER`` /
``MIXING_LAB_ADMIN_PW``). With either unset, admin login is disabled (fail closed).
"""
from __future__ import annotations

import hmac
import os
from dataclasses import dataclass

ADMIN_USER_ENV = "MIXING_LAB_ADMIN_USER"
ADMIN_PW_ENV = "MIXING_LAB_ADMIN_PW"

# Tables whose writes need an admin principal; the rest are open to every user.
PROTECTED_TABLES = frozenset({"reactors", "reactions"})

NOT_CONFIGURED_MSG = (f"Admin editing is disabled on this server — set {ADMIN_USER_ENV} and "
                      f"{ADMIN_PW_ENV} to enable it.")


@dataclass(frozen=True)
class Principal:
    name: str = "anonymous"
    is_admin: bool = False


ANONYMOUS = Principal()


def admin_configured() -> bool:
    return bool(os.environ.get(ADMIN_USER_ENV)) and bool(os.environ.get(ADMIN_PW_ENV))


def admin_credentials_ok(user: str | None, password: str | None) -> bool:
    """Constant-time check of the admin username/password; False when not configured."""
    if not admin_configured():
        return False
    u = (user or "").strip().encode("utf-8")
    p = (password or "").encode("utf-8")
    user_ok = hmac.compare_digest(u, os.environ[ADMIN_USER_ENV].encode("utf-8"))
    pw_ok = hmac.compare_digest(p, os.environ[ADMIN_PW_ENV].encode("utf-8"))
    return user_ok and pw_ok


def login(user: str | None, password: str | None) -> Principal | None:
    """Admin principal for valid credentials, else None."""
    if admin_credentials_ok(user, password):
        return Principal(name=(user or "").strip(), is_admin=True)
    return None


def can_write(principal: Principal, table: str) -> bool:
    return principal.is_admin or table not in PROTECTED_TABLES


def authorize(principal: Principal, table: str) -> None:
    """Raise ``PermissionError`` (HTTP 403) when ``principal`` may not write ``table``."""
    if not can_write(principal, table):
        raise PermissionError("Editing is locked — unlock with admin credentials first.")
