"""LEHAR Phase 3: the Brevo email channel and the double opt-in flow.

No network and no SMTP: every Brevo call goes through a real httpx.Client
over an httpx.MockTransport (tests/_channel_fakes.py), so the assertions are
on the exact HTTPS request LEHAR would have sent to /v3/smtp/email.
"""

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.db import AlertSubscription, get_session_factory
from app.dependencies import get_email_channel
from app.main import app
from app.services.alerts.channels.email import (
    BREVO_SEND_URL,
    EMAIL_DISABLED,
    EmailChannel,
    make_unsubscribe_token,
    make_verify_token,
)
from app.services.alerts.levels import DISCLAIMER_EN, DISCLAIMER_UR
from tests._channel_fakes import FakeProvider, SleepRecorder, brevo_ok
from tests.test_alert_channel_telegram import make_alert

API_KEY = "xkeysib-test-key-not-real"
FROM = "alerts@lehar.example"
BASE = "https://lehar-api.example"


def email_channel(provider: FakeProvider, **overrides) -> EmailChannel:
    settings = {"api_key": API_KEY, "from_email": FROM, "from_name": "LEHAR Alerts", "public_base_url": BASE}
    settings.update(overrides)
    return EmailChannel(client=provider.client(), sleep=SleepRecorder(), **settings)


def subscriber(language="en", sub_id=3, email="farmer@example.com") -> AlertSubscription:
    return AlertSubscription(
        id=sub_id, channel="email", target=email, districts=["Multan"], min_level=2, language=language, verified=True
    )


def link_in(text: str, path: str) -> str:
    match = re.search(rf"https://\S+/api/v1/alerts/email/{path}\?token=\S+", text)
    assert match, f"no {path} link in email text"
    return match.group(0)


def path_and_token(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    return parsed.path, parse_qs(parsed.query)["token"][0]


# --- sending ------------------------------------------------------------------------

def test_send_posts_to_brevo_over_https_with_both_bodies_and_an_unsubscribe_link():
    provider = FakeProvider(brevo_ok())
    alert = make_alert()

    result = email_channel(provider).send(alert, subscriber())

    assert result.status == "sent"
    assert result.attempts == 1
    request = provider.requests[0]
    assert str(request.url) == BREVO_SEND_URL == "https://api.brevo.com/v3/smtp/email"
    assert request.headers["api-key"] == API_KEY
    body = provider.bodies()[0]
    assert body["sender"] == {"name": "LEHAR Alerts", "email": FROM}
    assert body["to"] == [{"email": "farmer@example.com"}]
    assert body["subject"] == "[LEHAR level 3] Flood warning: Multan"

    unsubscribe = link_in(body["textContent"], "unsubscribe")
    assert unsubscribe.startswith(f"{BASE}/api/v1/alerts/email/unsubscribe?token=")
    assert body["headers"]["List-Unsubscribe"] == f"<{unsubscribe}>"
    assert body["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert "unsubscribe?token=" in body["htmlContent"]


def test_every_alert_email_is_bilingual_and_carries_the_disclaimer():
    provider = FakeProvider(brevo_ok())
    alert = make_alert()

    email_channel(provider).send(alert, subscriber())
    body = provider.bodies()[0]

    for content in (body["htmlContent"], body["textContent"]):
        assert DISCLAIMER_EN in content
        assert DISCLAIMER_UR in content
    assert alert.title_en in body["textContent"]
    assert alert.title_ur in body["textContent"]
    assert 'dir="rtl"' in body["htmlContent"]
    # The alert text is the stored template text, escaped — not rewritten.
    assert alert.body_en.splitlines()[0] in body["textContent"]


def test_an_urdu_subscriber_gets_urdu_first():
    provider = FakeProvider(brevo_ok())
    alert = make_alert()

    email_channel(provider).send(alert, subscriber(language="ur"))
    body = provider.bodies()[0]

    assert body["subject"] == f"[LEHAR level 3] {alert.title_ur}"
    text = body["textContent"]
    assert text.index(alert.title_ur) < text.index(alert.title_en)


def test_a_reminder_email_is_labelled():
    provider = FakeProvider(brevo_ok())
    email_channel(provider).send(make_alert(level=5), subscriber(), reminder=True)
    body = provider.bodies()[0]
    assert body["subject"].startswith("Reminder: [LEHAR level 5]")
    assert "STILL ACTIVE" in body["textContent"]


def test_send_retries_a_brevo_outage_then_succeeds():
    provider = FakeProvider(httpx.Response(503, json={"message": "unavailable"}), brevo_ok())
    sleep = SleepRecorder()
    channel = EmailChannel(
        api_key=API_KEY, from_email=FROM, public_base_url=BASE, client=provider.client(), sleep=sleep
    )

    result = channel.send(make_alert(), subscriber())

    assert result.status == "sent"
    assert result.attempts == 2
    assert sleep.calls == [1.0]


def test_a_rejected_sender_is_not_retried_and_the_reason_is_kept():
    provider = FakeProvider(httpx.Response(400, json={"code": "invalid_parameter", "message": "sender is not valid"}))
    result = email_channel(provider).send(make_alert(), subscriber())

    assert result.status == "failed"
    assert result.attempts == 1
    assert "sender is not valid" in result.error
    assert API_KEY not in result.error


@pytest.mark.parametrize("missing", ["api_key", "from_email", "public_base_url"])
def test_the_channel_disables_itself_when_any_setting_is_missing(missing):
    provider = FakeProvider(brevo_ok())
    channel = email_channel(provider, **{missing: ""})

    result = channel.send(make_alert(), subscriber())

    assert channel.enabled is False
    assert result.status == "skipped"
    assert result.attempts == 0
    assert result.error == EMAIL_DISABLED
    assert provider.requests == []


# --- the double opt-in flow, through the API -------------------------------------------

@pytest.fixture
def provider():
    return FakeProvider(brevo_ok())


@pytest.fixture
def mail(provider):
    channel = email_channel(provider)
    app.dependency_overrides[get_email_channel] = lambda: channel
    yield channel
    app.dependency_overrides.pop(get_email_channel, None)


@pytest.fixture
def db():
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


SUBSCRIBE = "/api/v1/alerts/email/subscribe"


def email_rows(db):
    db.expire_all()
    return db.query(AlertSubscription).filter(AlertSubscription.channel == "email").all()


def test_subscribe_creates_an_unverified_row_and_sends_only_a_verification_email(client, mail, provider, db):
    response = client.post(
        SUBSCRIBE,
        json={"email": "Farmer@Example.com", "districts": ["multan", "Dera Ghazi Khan"], "min_level": 3, "language": "ur"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "verification_sent"
    assert response.json()["disclaimer"] == DISCLAIMER_EN
    [row] = email_rows(db)
    assert row.target == "farmer@example.com"
    assert row.verified is False
    [sent] = provider.bodies()
    assert sent["to"] == [{"email": "farmer@example.com"}]
    assert "Confirm your LEHAR alert subscription" in sent["subject"]
    assert "Multan, Dera Ghazi Khan" in sent["textContent"]
    assert DISCLAIMER_EN in sent["textContent"]


def test_the_verification_link_verifies_and_applies_the_requested_preferences(client, mail, provider, db):
    client.post(SUBSCRIBE, json={"email": "a@example.com", "districts": ["sukkur"], "min_level": 4, "language": "ur"})
    path, token = path_and_token(link_in(provider.bodies()[0]["textContent"], "verify"))

    page = client.get(path, params={"token": token})

    assert page.status_code == 200
    assert "Subscription confirmed" in page.text
    assert DISCLAIMER_EN in page.text
    [row] = email_rows(db)
    assert row.verified is True
    assert row.districts == ["Sukkur"]
    assert row.min_level == 4
    assert row.language == "ur"


def test_the_unsubscribe_link_in_an_alert_email_stops_alerts(client, mail, provider, db):
    client.post(SUBSCRIBE, json={"email": "a@example.com", "districts": ["multan"]})
    path, token = path_and_token(link_in(provider.bodies()[0]["textContent"], "verify"))
    client.get(path, params={"token": token})
    [row] = email_rows(db)

    mail.send(make_alert(), row)
    unsubscribe_path, unsubscribe_token = path_and_token(link_in(provider.bodies()[-1]["textContent"], "unsubscribe"))
    page = client.get(unsubscribe_path, params={"token": unsubscribe_token})

    assert page.status_code == 200
    assert "Unsubscribed" in page.text
    assert email_rows(db)[0].verified is False


def test_one_click_unsubscribe_accepts_post(client, mail, db):
    row = AlertSubscription(channel="email", target="b@example.com", districts=["Multan"], min_level=2, verified=True)
    db.add(row)
    db.commit()

    response = client.post(
        "/api/v1/alerts/email/unsubscribe", params={"token": make_unsubscribe_token(row.id, "b@example.com")}
    )

    assert response.status_code == 200
    assert email_rows(db)[0].verified is False


def test_an_expired_verification_link_is_refused(client, mail, db):
    row = AlertSubscription(channel="email", target="c@example.com", districts=["Multan"], min_level=2, verified=False)
    db.add(row)
    db.commit()
    stale = make_verify_token(
        row.id, "c@example.com", ["Multan"], 2, "en", now=datetime.now(timezone.utc) - timedelta(hours=49)
    )

    page = client.get("/api/v1/alerts/email/verify", params={"token": stale})

    assert page.status_code == 400
    assert "invalid or expired" in page.text
    assert email_rows(db)[0].verified is False


def test_an_unsubscribe_token_cannot_be_used_to_verify(client, mail, db):
    row = AlertSubscription(channel="email", target="d@example.com", districts=["Multan"], min_level=2, verified=False)
    db.add(row)
    db.commit()

    page = client.get(
        "/api/v1/alerts/email/verify", params={"token": make_unsubscribe_token(row.id, "d@example.com")}
    )

    assert page.status_code == 400
    assert email_rows(db)[0].verified is False


def test_a_token_for_a_different_address_is_refused(client, mail, db):
    row = AlertSubscription(channel="email", target="e@example.com", districts=["Multan"], min_level=2, verified=False)
    db.add(row)
    db.commit()

    token = make_verify_token(row.id, "attacker@example.com", ["Multan"], 2, "en")
    assert client.get("/api/v1/alerts/email/verify", params={"token": token}).status_code == 400
    assert client.get("/api/v1/alerts/email/verify", params={"token": "not-a-token"}).status_code == 400


def test_resubscribing_a_verified_address_changes_nothing_until_the_owner_clicks(client, mail, provider, db):
    row = AlertSubscription(channel="email", target="f@example.com", districts=["Multan"], min_level=2, verified=True)
    db.add(row)
    db.commit()

    response = client.post(SUBSCRIBE, json={"email": "f@example.com", "districts": ["lahore"], "min_level": 5})

    assert response.status_code == 202
    [stored] = email_rows(db)
    assert stored.verified is True
    assert stored.districts == ["Multan"]
    assert stored.min_level == 2
    assert len(provider.requests) == 1  # just the confirmation email


def test_subscribe_is_503_when_email_is_not_configured(client, db):
    # No override: the real dependency, built from the blank test settings.
    get_email_channel.cache_clear()
    try:
        response = client.post(SUBSCRIBE, json={"email": "g@example.com", "districts": ["multan"]})
    finally:
        get_email_channel.cache_clear()
    assert response.status_code == 503
    assert "BREVO_API_KEY" in response.json()["detail"]
    assert email_rows(db) == []


def test_subscribe_rejects_an_unknown_district(client, mail, provider):
    response = client.post(SUBSCRIBE, json={"email": "h@example.com", "districts": ["atlantis"]})
    assert response.status_code == 400
    assert provider.requests == []


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "districts": ["multan"]},
        {"email": "i@example.com", "districts": []},
        {"email": "i@example.com", "districts": ["multan"], "min_level": 1},
        {"email": "i@example.com", "districts": ["multan"], "language": "fr"},
    ],
)
def test_subscribe_validates_its_input(client, mail, provider, payload):
    assert client.post(SUBSCRIBE, json=payload).status_code == 422
    assert provider.requests == []


def test_subscribe_reports_a_brevo_failure_as_502(client, db):
    failing = FakeProvider(httpx.Response(401, json={"code": "unauthorized", "message": "Key not found"}))
    channel = email_channel(failing)
    app.dependency_overrides[get_email_channel] = lambda: channel
    try:
        response = client.post(SUBSCRIBE, json={"email": "j@example.com", "districts": ["multan"]})
    finally:
        app.dependency_overrides.pop(get_email_channel, None)
    assert response.status_code == 502
    assert email_rows(db)[0].verified is False
