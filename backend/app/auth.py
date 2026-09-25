"""Password hashing and JWT issuance/validation.

Passwords are hashed with PBKDF2-HMAC-SHA256 (hashlib, stdlib — no extra
dependency needed) using a random per-user salt and a constant-time compare.
Plaintext passwords are never stored or logged.
"""

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import User, get_db

PBKDF2_ITERATIONS = 600_000
JWT_ALGORITHM = "HS256"

# Distinct "type" claims (Phase 11) so an access token can never be replayed
# as a refresh token (or vice versa) even though both are signed with the
# same JWT_SECRET — decode_username_from_token rejects a type mismatch.
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"

# auto_error=False so a missing/malformed Authorization header falls through
# to our own 401 handling in get_current_user, instead of FastAPI's default.
_bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """Returns (password_hash_hex, salt_hex). Generates a fresh random salt
    when none is given (registration); pass the stored salt to re-derive the
    same hash for verification."""
    salt = salt if salt is not None else os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return derived.hex(), salt.hex()


def verify_password(password: str, password_hash_hex: str, salt_hex: str) -> bool:
    salt = bytes.fromhex(salt_hex)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return hmac.compare_digest(derived.hex(), password_hash_hex)


def _create_token(username: str, token_type: str, expire_minutes: int) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    payload = {"sub": username, "type": token_type, "exp": int(expire.timestamp())}
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def create_access_token(username: str) -> str:
    settings = get_settings()
    return _create_token(username, TOKEN_TYPE_ACCESS, settings.jwt_expire_minutes)


def create_refresh_token(username: str) -> str:
    settings = get_settings()
    return _create_token(username, TOKEN_TYPE_REFRESH, settings.jwt_refresh_expire_minutes)


def decode_username_from_token(token: str, expected_type: str = TOKEN_TYPE_ACCESS) -> str:
    """Returns the username (sub claim). Raises jose.JWTError on any failure
    (bad signature, malformed token, expired, wrong `type` claim — e.g. a
    refresh token presented where an access token is required, or vice
    versa)."""
    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
    if payload.get("type") != expected_type:
        raise JWTError("Unexpected token type")
    return payload["sub"]


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """401 if the request has no valid bearer access token, or the user no longer exists."""
    unauthorized = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if credentials is None:
        raise unauthorized
    try:
        username = decode_username_from_token(credentials.credentials, TOKEN_TYPE_ACCESS)
    except JWTError:
        raise unauthorized
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise unauthorized
    return user


def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    """None (never raises) if there's no token or it's invalid — used by
    endpoints like /predict that work both logged-in and anonymous."""
    if credentials is None:
        return None
    try:
        username = decode_username_from_token(credentials.credentials, TOKEN_TYPE_ACCESS)
    except JWTError:
        return None
    return db.query(User).filter(User.username == username).first()
