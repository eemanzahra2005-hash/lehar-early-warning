"""Tests for POST /api/v1/auth/register, /api/v1/auth/login, and
/api/v1/auth/refresh (Phase 11 — access/refresh token lifecycle)."""

from datetime import datetime, timedelta, timezone

from jose import jwt as jose_jwt

from app.auth import JWT_ALGORITHM, TOKEN_TYPE_ACCESS, TOKEN_TYPE_REFRESH
from app.config import get_settings


def _token_with_type_and_offset(username: str, token_type: str, minutes_from_now: float) -> str:
    """Hand-crafts a JWT with the given type claim and expiry, signed with
    the real test JWT_SECRET — used to exercise expired/wrong-type refresh
    tokens without waiting for a real 60-minute/7-day expiry."""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)
    payload = {"sub": username, "type": token_type, "exp": int(expire.timestamp())}
    return jose_jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def test_register_returns_token(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"username": "alice", "password": "password123"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "alice"
    assert body["access_token"]


def test_register_duplicate_username_returns_409(client, register_user):
    register_user(username="bob")

    response = client.post(
        "/api/v1/auth/register",
        json={"username": "bob", "password": "password123"},
    )

    assert response.status_code == 409


def test_register_short_password_returns_422(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"username": "shortpw", "password": "abc"},
    )

    assert response.status_code == 422


def test_login_succeeds_with_correct_password(client, register_user):
    register_user(username="carol", password="correct-password")

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "carol", "password": "correct-password"},
    )

    assert response.status_code == 200
    assert response.json()["access_token"]


def test_login_fails_with_wrong_password(client, register_user):
    register_user(username="dave", password="correct-password")

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "dave", "password": "wrong-password"},
    )

    assert response.status_code == 401


def test_login_fails_for_unknown_username(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "ghost", "password": "whatever1"},
    )

    assert response.status_code == 401


# --- Refresh tokens (Phase 11) ---------------------------------------------


def test_register_returns_refresh_token(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"username": "refreshuser1", "password": "password123"},
    )

    assert response.status_code == 201
    assert response.json()["refresh_token"]
    assert response.json()["refresh_token"] != response.json()["access_token"]


def test_login_returns_refresh_token(client, register_user):
    register_user(username="refreshuser2", password="password123")

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "refreshuser2", "password": "password123"},
    )

    assert response.status_code == 200
    assert response.json()["refresh_token"]


def test_refresh_returns_new_access_token_that_works(client):
    register_response = client.post(
        "/api/v1/auth/register",
        json={"username": "refreshuser3", "password": "password123"},
    )
    refresh_token = register_response.json()["refresh_token"]

    refresh_response = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})

    assert refresh_response.status_code == 200, refresh_response.text
    body = refresh_response.json()
    assert body["access_token"]
    assert body["username"] == "refreshuser3"
    assert "refresh_token" not in body  # refresh does not rotate the refresh token — see docs/SECURITY.md

    # The freshly-minted access token works end-to-end against a real
    # auth-required endpoint, not just structurally well-formed.
    new_access_token = body["access_token"]
    fields_response = client.get(
        "/api/v1/fields", headers={"Authorization": f"Bearer {new_access_token}"}
    )
    assert fields_response.status_code == 200


def test_refresh_rejects_malformed_token(client):
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-real-jwt"})

    assert response.status_code == 401


def test_refresh_rejects_expired_refresh_token(client, register_user):
    register_user(username="refreshuser4")
    expired_refresh = _token_with_type_and_offset("refreshuser4", TOKEN_TYPE_REFRESH, minutes_from_now=-1)

    response = client.post("/api/v1/auth/refresh", json={"refresh_token": expired_refresh})

    assert response.status_code == 401


def test_refresh_rejects_an_access_token_used_as_refresh(client):
    """Type-confusion guard: an access token must never work where a refresh
    token is required, even though both are signed with the same secret —
    see app/auth.py's `type` claim check."""
    register_response = client.post(
        "/api/v1/auth/register",
        json={"username": "refreshuser5", "password": "password123"},
    )
    access_token = register_response.json()["access_token"]

    response = client.post("/api/v1/auth/refresh", json={"refresh_token": access_token})

    assert response.status_code == 401


def test_refresh_rejects_a_refresh_token_used_as_access_token(client):
    """The reverse direction: a refresh token must never work as a bearer
    access token on a normal authenticated endpoint."""
    register_response = client.post(
        "/api/v1/auth/register",
        json={"username": "refreshuser6", "password": "password123"},
    )
    refresh_token = register_response.json()["refresh_token"]

    response = client.get("/api/v1/fields", headers={"Authorization": f"Bearer {refresh_token}"})

    assert response.status_code == 401


def test_refresh_rejects_token_for_deleted_user(client):
    """A refresh token signed for a username that no longer exists (e.g. the
    account was deleted after the token was issued) must not be honored."""
    ghost_refresh = _token_with_type_and_offset("never-registered-user", TOKEN_TYPE_REFRESH, minutes_from_now=60)

    response = client.post("/api/v1/auth/refresh", json={"refresh_token": ghost_refresh})

    assert response.status_code == 401


def test_access_token_expiry_is_configured_short(client):
    """Regression guard for the Phase 11 lifecycle change: access tokens are
    minutes-scale (60 by default), not the old 7-day default — verified by
    decoding the real issued token's exp/iat gap rather than re-asserting
    the config value against itself."""
    response = client.post(
        "/api/v1/auth/register",
        json={"username": "refreshuser7", "password": "password123"},
    )
    access_token = response.json()["access_token"]
    settings = get_settings()
    payload = jose_jwt.decode(access_token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])

    assert payload["type"] == TOKEN_TYPE_ACCESS
    ttl_minutes = (payload["exp"] - datetime.now(timezone.utc).timestamp()) / 60
    assert 0 < ttl_minutes <= 60
