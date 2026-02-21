from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from robot.app.db import connect

# ======================
# Config
# ======================

JWT_SECRET = os.environ.get("TALENCE_JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("TALENCE_JWT_SECRET is required")

JWT_ALG = "HS256"
ACCESS_TOKEN_MINUTES = int(os.environ.get("TALENCE_ACCESS_TOKEN_MINUTES", "30"))
REFRESH_TOKEN_DAYS = int(os.environ.get("TALENCE_REFRESH_TOKEN_DAYS", "30"))

ph = PasswordHasher()
bearer_scheme = HTTPBearer()


def now() -> datetime:
    return datetime.now(timezone.utc)


# ======================
# Password helpers (Argon2)
# ======================

def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


# ======================
# JWT helpers
# ======================

def create_access_token(user_id: str) -> str:
    issued = now()
    payload = {
        "sub": user_id,
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(minutes=ACCESS_TOKEN_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")


# ======================
# Refresh token helpers
# ======================

def _hash_refresh_token(token: str) -> str:
    """
    Store only a hash of the refresh token in DB.
    Use a server-side pepper (JWT_SECRET) to prevent rainbow-table reuse.
    """
    h = hashlib.sha256()
    h.update(JWT_SECRET.encode("utf-8"))
    h.update(token.encode("utf-8"))
    return h.hexdigest()


def mint_refresh_token() -> str:
    # Opaque token; not a JWT. 32 bytes URL-safe.
    return secrets.token_urlsafe(32)


def create_refresh_session(
    *,
    user_id: str,
    user_agent: str | None = None,
    ip: str | None = None,
) -> dict:
    """
    Creates a DB-backed refresh session and returns:
      { session_id, refresh_token, refresh_token_hash, expires_at_iso }
    """
    con = connect()
    session_id = str(uuid.uuid4())
    refresh_token = mint_refresh_token()
    refresh_hash = _hash_refresh_token(refresh_token)

    created = now()
    expires = created + timedelta(days=REFRESH_TOKEN_DAYS)

    con.execute(
        """
        INSERT INTO auth_sessions (
          id, user_id, refresh_token_hash,
          created_at, last_used_at, expires_at,
          revoked_at, user_agent, ip
        )
        VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
        """,
        (
            session_id,
            user_id,
            refresh_hash,
            created.isoformat(),
            created.isoformat(),
            expires.isoformat(),
            user_agent,
            ip,
        ),
    )
    con.commit()

    return {
        "session_id": session_id,
        "refresh_token": refresh_token,
        "refresh_token_hash": refresh_hash,
        "expires_at": expires.isoformat(),
    }


def rotate_refresh_session(
    *,
    refresh_token: str,
    user_agent: str | None = None,
    ip: str | None = None,
) -> dict:
    """
    Validates refresh token, revokes old session, creates a new one.
    Returns: { user_id, new_session_id, refresh_token, expires_at }
    """
    con = connect()
    incoming_hash = _hash_refresh_token(refresh_token)

    row = con.execute(
        """
        SELECT id, user_id, expires_at, revoked_at
        FROM auth_sessions
        WHERE refresh_token_hash = ?
        """,
        (incoming_hash,),
    ).fetchone()

    # Do not leak which part failed.
    if not row:
        raise HTTPException(401, "Invalid refresh token")

    if row["revoked_at"] is not None:
        raise HTTPException(401, "Invalid refresh token")

    # Expiry check
    try:
        exp = datetime.fromisoformat(row["expires_at"])
    except Exception:
        raise HTTPException(401, "Invalid refresh token")

    if exp < now():
        raise HTTPException(401, "Invalid refresh token")

    old_session_id = row["id"]
    user_id = row["user_id"]

    # Revoke old session
    con.execute(
        "UPDATE auth_sessions SET revoked_at = ?, last_used_at = ? WHERE id = ?",
        (now().isoformat(), now().isoformat(), old_session_id),
    )
    con.commit()

    # Create new session
    new_session = create_refresh_session(user_id=user_id, user_agent=user_agent, ip=ip)

    return {
        "user_id": user_id,
        "new_session_id": new_session["session_id"],
        "refresh_token": new_session["refresh_token"],
        "expires_at": new_session["expires_at"],
    }


def revoke_refresh_session(refresh_token: str) -> None:
    con = connect()
    incoming_hash = _hash_refresh_token(refresh_token)
    con.execute(
        """
        UPDATE auth_sessions
        SET revoked_at = ?
        WHERE refresh_token_hash = ? AND revoked_at IS NULL
        """,
        (now().isoformat(), incoming_hash),
    )
    con.commit()


# ======================
# Dependency
# ======================

def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    token = creds.credentials
    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(401, "Invalid token payload")

    con = connect()
    row = con.execute(
        "SELECT id, email, handle, is_active FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()

    if not row or not row["is_active"]:
        raise HTTPException(401, "User not found or inactive")

    return row