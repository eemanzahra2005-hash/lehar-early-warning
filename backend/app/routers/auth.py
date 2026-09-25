"""User registration, login, and access-token refresh (Phase 11)."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.auth import (
    TOKEN_TYPE_REFRESH,
    create_access_token,
    create_refresh_token,
    decode_username_from_token,
    hash_password,
    verify_password,
)
from app.db import User, get_db
from app.rate_limit import auth_rate_limit, limiter
from app.schemas import LoginRequest, RefreshRequest, RefreshResponse, RegisterRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(auth_rate_limit)
def register(request: Request, payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

    password_hash, password_salt = hash_password(payload.password)
    user = User(
        username=payload.username,
        password_hash=password_hash,
        password_salt=password_salt,
        email=payload.email,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return TokenResponse(
        access_token=create_access_token(user.username),
        refresh_token=create_refresh_token(user.username),
        username=user.username,
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit(auth_rate_limit)
def login(request: Request, payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.username == payload.username).first()
    if user is None or not verify_password(payload.password, user.password_hash, user.password_salt):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    return TokenResponse(
        access_token=create_access_token(user.username),
        refresh_token=create_refresh_token(user.username),
        username=user.username,
    )


@router.post("/refresh", response_model=RefreshResponse)
@limiter.limit(auth_rate_limit)
def refresh(request: Request, payload: RefreshRequest, db: Session = Depends(get_db)) -> RefreshResponse:
    """Exchanges a valid, unexpired refresh token for a new access token.

    Does NOT rotate the refresh token — the client keeps using the same one
    until it expires (JWT_REFRESH_EXPIRE_MINUTES) or the user logs in again.
    401 (not 422) on any failure — expired, malformed, wrong-type (an access
    token presented here), or a since-deleted user — so the frontend's
    generic 401 handling (see frontend/js/api.js) applies uniformly."""
    unauthorized = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")
    try:
        username = decode_username_from_token(payload.refresh_token, TOKEN_TYPE_REFRESH)
    except JWTError:
        raise unauthorized
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise unauthorized

    return RefreshResponse(access_token=create_access_token(user.username), username=user.username)
