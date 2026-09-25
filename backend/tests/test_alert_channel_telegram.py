"""LEHAR Phase 3: the Telegram channel — sendMessage, retries, the webhook's
secret check, the bot commands and the Acknowledge button.

No network: every Bot API call goes through a real httpx.Client over an
httpx.MockTransport (tests/_channel_fakes.py), so the assertions are on the
exact request LEHAR would have sent.
"""

from datetime import datetime, timezone

import httpx
import pytest

import app.config as config_module
from app.db import Alert, AlertSubscription, get_session_factory
from app.dependencies import get_telegram_bot
from app.main import app
from app.services.alerts.channels.telegram import (
    MAX_MESSAGE_CHARS,
    TELEGRAM_DISABLED,
    TelegramBot,
    TelegramChannel,
    deep_link,
    format_alert_message,
)
from app.services.alerts.levels import DISCLAIMER_EN, DISCLAIMER_UR
from app.services.alerts.rules import TYPE_FLOOD
from app.services.alerts.templates import render
from tests._channel_fakes import FakeProvider, SleepRecorder, telegram_ok

TOKEN = "123456:TEST-token-not-real"
SECRET = "webhook-secret-for-tests"
WEBHOOK = "/api/v1/alerts/telegram/webhook"
T0 = datetime(2026, 8, 12, 6, 0, tzinfo=timezone.utc)


def make_alert(alert_id=7, level=3, district="Multan", status="active", payload=None) -> Alert:
    message = render(TYPE_FLOOD, level, {"district": district, "score": 70.0, "anomaly_ratio": 2.1})
    return Alert(
        id=alert_id,
        district_code=district,
        type=TYPE_FLOOD,
        level=level,
        title_en=message.title_en,
        title_ur=message.title_ur,
        body_en=message.body_en,
        body_ur=message.body_ur,
        payload=payload if payload is not None else {},
        status=status,
        dedupe_key=f"{district}|{TYPE_FLOOD}|{level}|{alert_id}",
        created_at=T0,
    )


def subscriber(language="en", target="555", sub_id=1) -> AlertSubscription:
    return AlertSubscription(
        id=sub_id, channel="telegram", target=target, districts=["Multan"], min_level=2, language=language, verified=True
    )


# --- sending ------------------------------------------------------------------

def test_send_posts_an_html_sendmessage_with_an_acknowledge_button():
    provider = FakeProvider(telegram_ok())
    channel = TelegramChannel(token=TOKEN, client=provider.client(), sleep=SleepRecorder())

    result = channel.send(make_alert(), subscriber())

    assert result.status == "sent"
    assert result.attempts == 1
    assert result.sent_at is not None
    request = provider.requests[0]
    assert request.method == "POST"
    assert str(request.url) == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    body = provider.bodies()[0]
    assert body["chat_id"] == "555"
    assert body["parse_mode"] == "HTML"
    assert body["text"].startswith("<b>Flood warning: Multan</b>")
    assert DISCLAIMER_EN in body["text"]
    button = body["reply_markup"]["inline_keyboard"][0][0]
    assert button["text"] == "Acknowledge"
    assert button["callback_data"] == "ack:7"


def test_send_uses_the_urdu_text_for_an_urdu_subscriber():
    provider = FakeProvider(telegram_ok())
    channel = TelegramChannel(token=TOKEN, client=provider.client(), sleep=SleepRecorder())
    alert = make_alert()

    channel.send(alert, subscriber(language="ur"))

    text = provider.bodies()[0]["text"]
    assert alert.title_ur in text
    # Urdu body carries the Urdu disclaimer AND the exact English sentence.
    assert DISCLAIMER_UR in text
    assert DISCLAIMER_EN in text
    # Sent as real UTF-8 JSON, not mangled.
    assert "سیلاب" in text


def test_message_text_is_html_escaped():
    alert = make_alert()
    alert.body_en = "River <rising> & fast\n\n" + DISCLAIMER_EN
    text = format_alert_message(alert, "en")
    assert "&lt;rising&gt; &amp; fast" in text
    assert "<rising>" not in text


def test_an_oversized_message_is_trimmed_but_keeps_its_disclaimer():
    alert = make_alert()
    alert.body_en = "x" * 10_000 + "\n\n" + DISCLAIMER_EN
    text = format_alert_message(alert, "en")
    assert len(text) <= MAX_MESSAGE_CHARS
    assert text.endswith(DISCLAIMER_EN)


def test_a_reminder_is_labelled_as_one():
    text = format_alert_message(make_alert(level=5), "en", reminder=True)
    assert text.startswith("<i>Reminder: this alert is STILL ACTIVE.")


def test_send_retries_server_errors_with_backoff_then_succeeds():
    provider = FakeProvider(httpx.Response(500), httpx.Response(502), telegram_ok())
    sleep = SleepRecorder()
    channel = TelegramChannel(token=TOKEN, client=provider.client(), sleep=sleep)

    result = channel.send(make_alert(), subscriber())

    assert result.status == "sent"
    assert result.attempts == 3
    assert sleep.calls == [1.0, 2.0]


def test_send_gives_up_after_three_retries():
    provider = FakeProvider(httpx.Response(503, json={"ok": False, "description": "Service Unavailable"}))
    sleep = SleepRecorder()
    channel = TelegramChannel(token=TOKEN, client=provider.client(), sleep=sleep)

    result = channel.send(make_alert(), subscriber())

    assert result.status == "failed"
    assert result.attempts == 4  # the first try + 3 retries
    assert sleep.calls == [1.0, 2.0, 4.0]
    assert "503" in result.error


def test_send_retries_a_network_error():
    request = httpx.Request("POST", "https://api.telegram.org")
    provider = FakeProvider(httpx.ConnectTimeout("timed out", request=request), telegram_ok())
    channel = TelegramChannel(token=TOKEN, client=provider.client(), sleep=SleepRecorder())

    result = channel.send(make_alert(), subscriber())

    assert result.status == "sent"
    assert result.attempts == 2


def test_a_client_error_is_not_retried():
    """403 "bot was blocked by the user" cannot change by asking again."""
    provider = FakeProvider(
        httpx.Response(403, json={"ok": False, "description": "Forbidden: bot was blocked by the user"})
    )
    sleep = SleepRecorder()
    channel = TelegramChannel(token=TOKEN, client=provider.client(), sleep=sleep)

    result = channel.send(make_alert(), subscriber())

    assert result.status == "failed"
    assert result.attempts == 1
    assert sleep.calls == []
    assert "blocked" in result.error


def test_a_429_waits_the_time_telegram_asks_for():
    provider = FakeProvider(
        httpx.Response(429, json={"ok": False, "description": "Too Many Requests", "parameters": {"retry_after": 3}}),
        telegram_ok(),
    )
    sleep = SleepRecorder()
    channel = TelegramChannel(token=TOKEN, client=provider.client(), sleep=sleep)

    result = channel.send(make_alert(), subscriber())

    assert result.status == "sent"
    assert sleep.calls == [3.0]


def test_a_429_asking_for_a_long_wait_fails_instead_of_stalling_the_run():
    provider = FakeProvider(
        httpx.Response(429, json={"ok": False, "description": "Too Many Requests", "parameters": {"retry_after": 600}})
    )
    sleep = SleepRecorder()
    channel = TelegramChannel(token=TOKEN, client=provider.client(), sleep=sleep)

    result = channel.send(make_alert(), subscriber())

    assert result.status == "failed"
    assert result.attempts == 1
    assert sleep.calls == []


def test_the_bot_token_never_appears_in_an_error():
    request = httpx.Request("POST", f"https://api.telegram.org/bot{TOKEN}/sendMessage")
    provider = FakeProvider(httpx.ConnectError(f"cannot reach https://api.telegram.org/bot{TOKEN}", request=request))
    channel = TelegramChannel(token=TOKEN, client=provider.client(), sleep=SleepRecorder())

    result = channel.send(make_alert(), subscriber())

    assert result.status == "failed"
    assert TOKEN not in result.error
    assert "<redacted>" in result.error


def test_the_channel_disables_itself_without_a_token():
    provider = FakeProvider(telegram_ok())
    channel = TelegramChannel(token="", client=provider.client())

    result = channel.send(make_alert(), subscriber())

    assert channel.enabled is False
    assert result.status == "skipped"
    assert result.attempts == 0
    assert result.error == TELEGRAM_DISABLED
    assert "TELEGRAM_BOT_TOKEN" in result.error
    assert provider.requests == []


def test_deep_link_uses_the_district_code():
    assert deep_link("lehar_bot", "Dera Ghazi Khan") == "https://t.me/lehar_bot?start=dera_ghazi_khan"


# --- the webhook -------------------------------------------------------------------

@pytest.fixture
def webhook_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    config_module.get_settings.cache_clear()
    yield
    config_module.get_settings.cache_clear()


@pytest.fixture
def provider():
    return FakeProvider(telegram_ok())


@pytest.fixture
def bot(provider):
    telegram_bot = TelegramBot(TelegramChannel(token=TOKEN, client=provider.client(), sleep=SleepRecorder()))
    app.dependency_overrides[get_telegram_bot] = lambda: telegram_bot
    yield telegram_bot
    app.dependency_overrides.pop(get_telegram_bot, None)


@pytest.fixture
def db():
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def command(client, text, chat_id=555, secret=SECRET, update_id=1):
    headers = {"X-Telegram-Bot-Api-Secret-Token": secret} if secret is not None else {}
    update = {"update_id": update_id, "message": {"message_id": 1, "chat": {"id": chat_id}, "text": text}}
    return client.post(WEBHOOK, json=update, headers=headers)


def telegram_subscription(db, chat_id="555"):
    db.expire_all()
    return (
        db.query(AlertSubscription)
        .filter(AlertSubscription.channel == "telegram", AlertSubscription.target == chat_id)
        .one_or_none()
    )


def test_webhook_refuses_every_call_when_not_configured(client, bot):
    response = command(client, "/start multan")
    assert response.status_code == 503


def test_webhook_rejects_a_missing_secret(client, bot, webhook_env, provider):
    response = command(client, "/start multan", secret=None)
    assert response.status_code == 401
    assert provider.requests == []


def test_webhook_rejects_a_wrong_secret(client, bot, webhook_env, db):
    response = command(client, "/start multan", secret="guess")
    assert response.status_code == 401
    assert telegram_subscription(db) is None


def test_start_with_a_district_code_subscribes_the_chat(client, bot, webhook_env, provider, db):
    response = command(client, "/start dera_ghazi_khan")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "handled": "subscribed"}
    sub = telegram_subscription(db)
    assert sub.districts == ["Dera Ghazi Khan"]
    assert sub.verified is True
    assert sub.min_level == 2
    assert sub.language == "en"
    reply = provider.texts()[-1]
    assert "Subscribed to LEHAR alerts for Dera Ghazi Khan" in reply
    assert DISCLAIMER_EN in reply


def test_start_adds_a_second_district_to_the_same_chat(client, bot, webhook_env, db):
    command(client, "/start multan")
    command(client, "/start Sukkur")

    assert telegram_subscription(db).districts == ["Multan", "Sukkur"]
    assert db.query(AlertSubscription).count() == 1


def test_start_with_an_unknown_district_subscribes_nothing(client, bot, webhook_env, provider, db):
    response = command(client, "/start atlantis")

    assert response.json()["handled"] == "unknown_district"
    assert telegram_subscription(db) is None
    assert "Unknown district code" in provider.texts()[-1]


def test_a_bare_start_shows_help_and_never_subscribes_to_everything(client, bot, webhook_env, provider, db):
    response = command(client, "/start")

    assert response.json()["handled"] == "help"
    assert telegram_subscription(db) is None
    # Replies go out in HTML parse mode, so their angle brackets are escaped.
    assert "/level &lt;1-5&gt;" in provider.texts()[-1]


def test_stop_unsubscribes_and_start_resubscribes(client, bot, webhook_env, db):
    command(client, "/start multan")
    assert command(client, "/stop").json()["handled"] == "stopped"
    assert telegram_subscription(db).verified is False

    command(client, "/start lahore")
    sub = telegram_subscription(db)
    assert sub.verified is True
    assert sub.districts == ["Lahore"]


def test_level_sets_the_minimum_level(client, bot, webhook_env, provider, db):
    command(client, "/start multan")
    assert command(client, "/level 4").json()["handled"] == "level_set"
    assert telegram_subscription(db).min_level == 4
    assert "level 4 and above" in provider.texts()[-1]


def test_level_rejects_anything_but_1_to_5(client, bot, webhook_env, db):
    command(client, "/start multan")
    for bad in ("/level 0", "/level 6", "/level x", "/level"):
        assert command(client, bad).json()["handled"] == "level_invalid"
    assert telegram_subscription(db).min_level == 2


def test_level_1_is_accepted_but_explained(client, bot, webhook_env, provider, db):
    command(client, "/start multan")
    command(client, "/level 1")
    assert telegram_subscription(db).min_level == 1
    assert "level 1 advisories are shown in the app only" in provider.texts()[-1]


def test_level_before_subscribing_is_refused(client, bot, webhook_env):
    assert command(client, "/level 3").json()["handled"] == "not_subscribed"


def test_group_chat_command_form_is_understood(client, bot, webhook_env, db):
    command(client, "/start multan")
    assert command(client, "/level@lehar_bot 3").json()["handled"] == "level_set"
    assert telegram_subscription(db).min_level == 3


def test_lang_switches_to_urdu(client, bot, webhook_env, provider, db):
    command(client, "/start multan")
    assert command(client, "/lang ur").json()["handled"] == "lang_set"

    assert telegram_subscription(db).language == "ur"
    reply = provider.texts()[-1]
    assert "زبان اردو کر دی گئی" in reply
    assert DISCLAIMER_UR in reply and DISCLAIMER_EN in reply
    assert command(client, "/lang fr").json()["handled"] == "lang_invalid"


def test_status_reports_each_district_level(client, bot, webhook_env, provider, db):
    command(client, "/start multan")
    db.add(make_alert(alert_id=None, level=3))
    db.commit()

    assert command(client, "/status").json()["handled"] == "status"
    reply = provider.texts()[-1]
    assert "Subscription: active. Minimum level: 2. Language: en." in reply
    assert "Multan: level 3 (Warning)" in reply
    assert DISCLAIMER_EN in reply


def test_status_for_a_calm_district_reports_level_1(client, bot, webhook_env, provider):
    command(client, "/start lahore")
    command(client, "/status")
    assert "Lahore: level 1 (Early Advisory)" in provider.texts()[-1]


def test_plain_text_gets_the_help_reply(client, bot, webhook_env, provider):
    assert command(client, "hello").json()["handled"] == "help"


def test_a_malformed_update_is_ignored_with_200(client, bot, webhook_env):
    response = client.post(WEBHOOK, json={"update_id": 9}, headers={"X-Telegram-Bot-Api-Secret-Token": SECRET})
    assert response.status_code == 200
    assert response.json()["handled"] == "ignored"


def test_a_handler_crash_still_answers_200_so_telegram_does_not_redeliver_forever(client, webhook_env):
    class ExplodingBot:
        channel = TelegramChannel(token=TOKEN)

        def handle_update(self, db, update):
            raise RuntimeError("bug")

    app.dependency_overrides[get_telegram_bot] = lambda: ExplodingBot()
    try:
        response = command(client, "/start multan")
    finally:
        app.dependency_overrides.pop(get_telegram_bot, None)
    assert response.status_code == 200
    assert response.json() == {"ok": True, "handled": "error"}


# --- the Acknowledge button ----------------------------------------------------------

def press_ack(client, alert_id, chat_id=555):
    update = {
        "update_id": 50,
        "callback_query": {
            "id": "cbq-1",
            "from": {"id": chat_id},
            "message": {"message_id": 3, "chat": {"id": chat_id}},
            "data": f"ack:{alert_id}",
        },
    }
    return client.post(WEBHOOK, json=update, headers={"X-Telegram-Bot-Api-Secret-Token": SECRET})


def test_acknowledge_button_marks_the_alert_acknowledged(client, bot, webhook_env, provider, db):
    alert = make_alert(alert_id=None, level=4)
    db.add(alert)
    db.commit()

    response = press_ack(client, alert.id)

    assert response.json()["handled"] == "acknowledged"
    db.expire_all()
    stored = db.get(Alert, alert.id)
    assert stored.status == "acknowledged"
    assert stored.payload["acknowledged_by"] == ["telegram:555"]
    answer = provider.requests[-1]
    assert answer.url.path.endswith("/answerCallbackQuery")
    assert provider.bodies()[-1]["callback_query_id"] == "cbq-1"


def test_a_second_chat_acknowledging_is_recorded_too(client, bot, webhook_env, db):
    alert = make_alert(alert_id=None, level=5)
    db.add(alert)
    db.commit()

    press_ack(client, alert.id, chat_id=555)
    press_ack(client, alert.id, chat_id=777)
    press_ack(client, alert.id, chat_id=777)  # idempotent

    db.expire_all()
    assert db.get(Alert, alert.id).payload["acknowledged_by"] == ["telegram:555", "telegram:777"]


def test_acknowledging_a_resolved_alert_changes_nothing(client, bot, webhook_env, db):
    alert = make_alert(alert_id=None, level=3, status="resolved")
    db.add(alert)
    db.commit()

    assert press_ack(client, alert.id).json()["handled"] == "resolved"
    db.expire_all()
    assert db.get(Alert, alert.id).status == "resolved"


def test_acknowledging_an_unknown_alert_says_so(client, bot, webhook_env):
    assert press_ack(client, 999_999).json()["handled"] == "not_found"
