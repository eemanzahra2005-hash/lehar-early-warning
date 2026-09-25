# Fixtures are imported by name from sibling test modules (the pytest way to
# share them without a conftest); taking them as parameters reads as F811.
# ruff: noqa: F811
"""LEHAR Phase 4: the public subscription API, end to end.

Covers what Phase 4 added on top of Phase 3's double opt-in: bilingual JSON
messages, the ?format=json form of verify/unsubscribe, the typed Telegram
deep-link response, and per-IP rate limits on every public subscription
endpoint. The HTML pages from Phase 3 are unchanged, which
test_alert_channel_email.py keeps proving.

Offline: Brevo goes through an httpx.MockTransport (tests/_channel_fakes.py).
"""

import pytest

import app.config as config_module
from app.config import get_settings
from app.rate_limit import limiter
from app.services.alerts.levels import DISCLAIMER_EN, DISCLAIMER_UR

# The Phase 3 email fixtures: a Brevo-over-MockTransport channel wired into
# the app, and a DB session.
from tests.test_alert_channel_email import (  # noqa: F401
    SUBSCRIBE,
    db,
    email_rows,
    link_in,
    mail,
    path_and_token,
    provider,
)

VERIFY = "/api/v1/alerts/email/verify"
UNSUBSCRIBE = "/api/v1/alerts/email/unsubscribe"
TELEGRAM_LINK = "/api/v1/alerts/telegram/link"


def subscribe_and_get_verify_token(client, provider, email="farmer@example.com", **fields) -> str:
    payload = {"email": email, "districts": ["multan"], "min_level": 3, "language": "ur", **fields}
    response = client.post(SUBSCRIBE, json=payload)
    assert response.status_code == 202, response.text
    _path, token = path_and_token(link_in(provider.bodies()[-1]["textContent"], "verify"))
    return token


def unsubscribe_token_for(db, email: str) -> str:
    from app.services.alerts.channels.email import make_unsubscribe_token

    [row] = [row for row in email_rows(db) if row.target == email]
    return make_unsubscribe_token(row.id, email)


# --- subscribe ------------------------------------------------------------------------

def test_subscribe_answers_in_english_and_urdu(client, mail, provider):
    body = client.post(SUBSCRIBE, json={"email": "a@example.com", "districts": ["multan"]}).json()

    assert body["status"] == "verification_sent"
    assert body["message_en"] == body["detail"]  # Phase 3 field kept, same text
    assert "48 گھنٹوں" in body["message_ur"]
    assert body["disclaimer"] == DISCLAIMER_EN
    assert body["disclaimer_ur"] == DISCLAIMER_UR


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "districts": ["multan"]},
        {"email": "a@example.com", "districts": []},
        {"email": "a@example.com", "districts": ["multan"], "min_level": 1},
        {"email": "a@example.com", "districts": ["multan"], "language": "fr"},
    ],
)
def test_subscribe_input_is_validated_by_the_schema(client, mail, provider, payload):
    assert client.post(SUBSCRIBE, json=payload).status_code == 422
    assert provider.requests == []


# --- the full flow in JSON: subscribe -> verify -> verified -> unsubscribe ------------------

def test_full_email_flow_in_json(client, mail, provider, db):
    token = subscribe_and_get_verify_token(client, provider)
    [row] = email_rows(db)
    assert row.verified is False

    verified = client.get(VERIFY, params={"token": token, "format": "json"})
    assert verified.status_code == 200
    body = verified.json()
    assert body["status"] == "verified"
    assert body["districts"] == ["Multan"]
    assert body["min_level"] == 3
    assert body["language"] == "ur"
    assert "Multan" in body["message_en"] and "Multan" in body["message_ur"]
    assert body["disclaimer"] == DISCLAIMER_EN
    assert body["disclaimer_ur"] == DISCLAIMER_UR
    [row] = email_rows(db)
    assert row.verified is True

    unsubscribed = client.get(
        UNSUBSCRIBE, params={"token": unsubscribe_token_for(db, "farmer@example.com"), "format": "json"}
    )
    assert unsubscribed.status_code == 200
    assert unsubscribed.json()["status"] == "unsubscribed"
    assert unsubscribed.json()["message_ur"]
    [row] = email_rows(db)
    assert row.verified is False


def test_json_one_click_unsubscribe_by_post(client, mail, provider, db):
    token = subscribe_and_get_verify_token(client, provider, email="p@example.com")
    client.get(VERIFY, params={"token": token})

    response = client.post(UNSUBSCRIBE, params={"token": unsubscribe_token_for(db, "p@example.com"), "format": "json"})

    assert response.status_code == 200
    assert response.json()["status"] == "unsubscribed"


@pytest.mark.parametrize("path", [VERIFY, UNSUBSCRIBE])
def test_a_bad_token_in_json_is_a_400_with_both_languages(client, path):
    response = client.get(path, params={"token": "not-a-real-token", "format": "json"})

    assert response.status_code == 400
    body = response.json()
    assert body["status"] == "invalid_link"
    assert body["message_en"] and body["message_ur"]
    assert body["districts"] == []


def test_html_stays_the_default(client, mail, provider):
    token = subscribe_and_get_verify_token(client, provider, email="h@example.com")

    page = client.get(VERIFY, params={"token": token})

    assert page.headers["content-type"].startswith("text/html")
    assert "Subscription confirmed" in page.text
    assert DISCLAIMER_EN in page.text


def test_an_unknown_format_is_rejected(client):
    assert client.get(VERIFY, params={"token": "x", "format": "xml"}).status_code == 422


# --- Telegram deep link --------------------------------------------------------------------

@pytest.fixture
def telegram_username(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "@lehar_test_bot")
    config_module.get_settings.cache_clear()
    yield "lehar_test_bot"
    config_module.get_settings.cache_clear()


def test_telegram_link_returns_the_deep_link_and_bilingual_instructions(client, telegram_username):
    response = client.get(TELEGRAM_LINK, params={"district": "Dera Ghazi Khan"})

    assert response.status_code == 200
    body = response.json()
    assert body["url"] == "https://t.me/lehar_test_bot?start=dera_ghazi_khan"
    assert body["bot_username"] == "lehar_test_bot"
    assert body["district"] == "Dera Ghazi Khan"
    assert body["district_code"] == "dera_ghazi_khan"
    assert body["start_command"] == "/start dera_ghazi_khan"
    assert "/stop" in body["instructions_en"] and "/stop" in body["instructions_ur"]
    assert body["disclaimer"] == DISCLAIMER_EN
    assert body["disclaimer_ur"] == DISCLAIMER_UR


def test_telegram_link_accepts_a_district_code(client, telegram_username):
    assert client.get(TELEGRAM_LINK, params={"district": "multan"}).json()["district"] == "Multan"


def test_telegram_link_404s_an_unknown_district(client, telegram_username):
    assert client.get(TELEGRAM_LINK, params={"district": "Atlantis"}).status_code == 404


def test_telegram_link_is_503_when_the_bot_is_not_configured(client):
    response = client.get(TELEGRAM_LINK, params={"district": "multan"})
    assert response.status_code == 503
    assert "TELEGRAM_BOT_USERNAME" in response.json()["detail"]


def test_telegram_link_requires_a_district(client, telegram_username):
    assert client.get(TELEGRAM_LINK).status_code == 422


# --- rate limits ---------------------------------------------------------------------------

@pytest.fixture
def rate_limited():
    """Re-enable the limiter (conftest disables it suite-wide) with clean
    windows, and always switch it back off."""
    limiter.reset()
    limiter.enabled = True
    try:
        yield
    finally:
        limiter.enabled = False
        limiter.reset()


@pytest.mark.parametrize(
    "method,path,params",
    [
        ("get", VERIFY, {"token": "x", "format": "json"}),
        ("get", UNSUBSCRIBE, {"token": "x", "format": "json"}),
        ("post", UNSUBSCRIBE, {"token": "x", "format": "json"}),
        ("get", TELEGRAM_LINK, {"district": "multan"}),
    ],
)
def test_public_subscription_endpoints_are_rate_limited(client, rate_limited, method, path, params):
    limit = get_settings().rate_limit_subscription_per_minute
    last = None
    for _ in range(limit + 1):
        last = getattr(client, method)(path, params=params)
    assert last.status_code == 429, last.text


def test_subscribe_keeps_the_tighter_auth_rate_limit(client, mail, rate_limited):
    limit = get_settings().rate_limit_auth_per_minute
    last = None
    for i in range(limit + 1):
        last = client.post(SUBSCRIBE, json={"email": f"r{i}@example.com", "districts": ["multan"]})
    assert last.status_code == 429
