"""Telegram delivery channel + bot commands (LEHAR Phase 3).

Two halves, one file, because they share one bot token:

  * TelegramChannel — sends an alert with the Bot API's sendMessage over
    HTTPS (HTML parse mode, so Urdu and English text both go through
    unchanged), with an inline "Acknowledge" button whose callback marks the
    alert acknowledged.
  * TelegramBot — handles the updates Telegram POSTs to
    /api/v1/alerts/telegram/webhook: /start <DISTRICT_CODE>, /stop,
    /level <1-5>, /lang en|ur, /status, and the Acknowledge button.

Webhook mode only, never polling: a polling loop is a second always-on
process a 512 MB free host cannot afford (CLAUDE.md rule 11), and Render
free sleeps idle services anyway.

Nothing here writes alert text. The message body is the alert row's own
title/body, rendered by templates.py when the alert was raised (CLAUDE.md
rule 10); this module only chooses the language and escapes it for HTML.
"""

import html
import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Alert, AlertSubscription
from app.services.alerts.channels._http import PostOutcome, post_json
from app.services.alerts.channels.base import (
    LANGUAGE_EN,
    LANGUAGE_UR,
    STATUS_FAILED,
    STATUS_SENT,
    STATUS_SKIPPED,
    AlertChannel,
    DeliveryResult,
    message_language,
    resolve_district,
)
from app.services.alerts.levels import CHANNEL_TELEGRAM, DISCLAIMER_EN, DISCLAIMER_UR, get_level
from ml.districts import district_code

logger = logging.getLogger("app.alerts.telegram")

# httpx logs every request line at INFO — and a Bot API URL contains the bot
# token. Quieten it so the token can never reach a log file.
logging.getLogger("httpx").setLevel(logging.WARNING)

API_BASE = "https://api.telegram.org"
MAX_MESSAGE_CHARS = 4096  # Bot API hard limit for sendMessage text
ACK_CALLBACK_PREFIX = "ack:"

# Worded to contain "Phase 3" so a delivery row makes clear which phase's
# transport is switched off — and it is the literal truth.
TELEGRAM_DISABLED = "Telegram delivery (LEHAR Phase 3) is disabled: TELEGRAM_BOT_TOKEN is not set."

ACK_BUTTON = {LANGUAGE_EN: "Acknowledge", LANGUAGE_UR: "Acknowledge — موصول ہو گیا"}

REMINDER_LINE = {
    LANGUAGE_EN: "Reminder: this alert is STILL ACTIVE. Re-sent every 6 hours until it ends or you press Acknowledge.",
    LANGUAGE_UR: "یاد دہانی: یہ الرٹ ابھی تک فعال ہے۔ ختم ہونے یا Acknowledge دبانے تک ہر 6 گھنٹے بعد دوبارہ بھیجا جاتا ہے۔",
}


def _disclaimer(language: str) -> str:
    # The Urdu line is followed by the exact English sentence, the same
    # convention templates.py uses (CLAUDE.md rule 12).
    if language == LANGUAGE_UR:
        return f"{DISCLAIMER_UR}\n{DISCLAIMER_EN}"
    return DISCLAIMER_EN


def format_alert_message(alert: Alert, language: str, reminder: bool = False) -> str:
    """The HTML sendMessage text for one alert: bold title, then the body the
    alert was raised with, escaped. Trimmed to Telegram's 4096-character
    limit from the middle of the body so the disclaimer always survives."""
    if language == LANGUAGE_UR:
        title, body = alert.title_ur, alert.body_ur
    else:
        title, body = alert.title_en, alert.body_en

    head = f"<b>{html.escape(title)}</b>\n\n"
    if reminder:
        head = f"<i>{html.escape(REMINDER_LINE[language])}</i>\n\n{head}"

    text = head + html.escape(body)
    if len(text) <= MAX_MESSAGE_CHARS:
        return text

    tail = "…\n\n" + html.escape(_disclaimer(language))
    raw = body
    while raw and len(head) + len(html.escape(raw)) + len(tail) > MAX_MESSAGE_CHARS:
        raw = raw[: max(0, len(raw) - 200)]
    return head + html.escape(raw) + tail


class TelegramChannel(AlertChannel):
    """Sends alerts through the Telegram Bot API. Disabled (and honest about
    it) when TELEGRAM_BOT_TOKEN is empty."""

    name = CHANNEL_TELEGRAM

    def __init__(
        self,
        token: str | None = None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._token = token if token is not None else get_settings().telegram_bot_token
        self._client = client
        self._sleep = sleep

    @property
    def enabled(self) -> bool:
        return bool(self._token)

    def api_call(self, method: str, payload: dict) -> PostOutcome:
        """One Bot API method call, with the shared retry policy. Telegram
        answers HTTP 200 with {"ok": true} on success."""
        if not self.enabled:
            return PostOutcome(ok=False, attempts=0, error=TELEGRAM_DISABLED)
        outcome = post_json(
            f"{API_BASE}/bot{self._token}/{method}",
            payload,
            client=self._client,
            sleep=self._sleep,
            redact=self._token,
        )
        if outcome.ok and outcome.body is not None and outcome.body.get("ok") is False:
            outcome.ok = False
            outcome.error = str(outcome.body.get("description") or "Telegram returned ok=false")[:300]
        return outcome

    def send_text(self, chat_id: str | int, text: str, reply_markup: dict | None = None) -> PostOutcome:
        payload: dict = {
            "chat_id": chat_id,
            "text": text[:MAX_MESSAGE_CHARS],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self.api_call("sendMessage", payload)

    def send(
        self, alert: Alert, subscription: AlertSubscription | None, reminder: bool = False
    ) -> DeliveryResult:
        if not self.enabled:
            return DeliveryResult(channel=self.name, status=STATUS_SKIPPED, attempts=0, error=TELEGRAM_DISABLED)
        if subscription is None:
            return DeliveryResult(channel=self.name, status=STATUS_SKIPPED, attempts=0, error="No subscriber.")

        language = message_language(subscription)
        keyboard = {
            "inline_keyboard": [
                [{"text": ACK_BUTTON[language], "callback_data": f"{ACK_CALLBACK_PREFIX}{alert.id}"}]
            ]
        }
        outcome = self.send_text(subscription.target, format_alert_message(alert, language, reminder), keyboard)
        logger.info(
            "alert.delivery channel=telegram alert_id=%s subscription_id=%s ok=%s attempts=%s",
            alert.id,
            subscription.id,
            outcome.ok,
            outcome.attempts,
        )
        if outcome.ok:
            return DeliveryResult(
                channel=self.name,
                status=STATUS_SENT,
                attempts=outcome.attempts,
                sent_at=datetime.now(timezone.utc),
            )
        return DeliveryResult(channel=self.name, status=STATUS_FAILED, attempts=outcome.attempts, error=outcome.error)


# --- the bot: commands and the Acknowledge button --------------------------

# Every reply is a fixed string (CLAUDE.md rule 10 applies to the bot's
# words too), in the subscriber's language, and ends with the disclaimer.
REPLIES: dict[str, tuple[str, str]] = {
    "help": (
        "LEHAR research early-warning bot.\n"
        "/start <district_code> — get alerts for a district (e.g. /start multan)\n"
        "/stop — stop all alerts\n"
        "/level <1-5> — only alerts at this level or higher (level 1 stays in the app)\n"
        "/lang en|ur — English or Urdu\n"
        "/status — your subscription and today's levels",
        "لہر تحقیقی ابتدائی انتباہ بوٹ۔\n"
        "/start <district_code> — کسی ضلع کے الرٹ حاصل کریں (مثلاً /start multan)\n"
        "/stop — تمام الرٹ بند کریں\n"
        "/level <1-5> — صرف اس درجے یا اس سے زیادہ کے الرٹ (درجہ 1 صرف ایپ میں)\n"
        "/lang en|ur — انگریزی یا اردو\n"
        "/status — آپ کی رکنیت اور آج کے درجے",
    ),
    "subscribed": (
        "Subscribed to LEHAR alerts for {district}. You will receive level {min_level} and above. "
        "Level 1 advisories stay in the app.",
        "{district} کے لیے لہر الرٹ کی رکنیت ہو گئی۔ آپ کو درجہ {min_level} اور اس سے زیادہ کے الرٹ ملیں گے۔ "
        "درجہ 1 کی اطلاعات صرف ایپ میں رہتی ہیں۔",
    ),
    "unknown_district": (
        "Unknown district code \"{code}\". Use the code from the LEHAR app, e.g. /start multan or "
        "/start dera_ghazi_khan.",
        "ضلع کا کوڈ \"{code}\" نہیں ملا۔ لہر ایپ والا کوڈ استعمال کریں، مثلاً /start multan یا "
        "/start dera_ghazi_khan۔",
    ),
    "stopped": (
        "Alerts stopped. Send /start <district_code> to subscribe again.",
        "الرٹ بند کر دیے گئے۔ دوبارہ رکنیت کے لیے /start <district_code> بھیجیں۔",
    ),
    "not_subscribed": (
        "You are not subscribed. Send /start <district_code> first.",
        "آپ کی رکنیت نہیں ہے۔ پہلے /start <district_code> بھیجیں۔",
    ),
    "level_set": (
        "You will now receive level {min_level} and above.",
        "اب آپ کو درجہ {min_level} اور اس سے زیادہ کے الرٹ ملیں گے۔",
    ),
    "level_one_note": (
        "Note: level 1 advisories are shown in the app only, so Telegram starts at level 2.",
        "نوٹ: درجہ 1 کی اطلاعات صرف ایپ میں دکھائی جاتی ہیں، اس لیے ٹیلیگرام پر درجہ 2 سے الرٹ آتے ہیں۔",
    ),
    "level_invalid": (
        "Send /level followed by a number from 1 to 5, e.g. /level 3.",
        "/level کے بعد 1 سے 5 تک کوئی نمبر بھیجیں، مثلاً /level 3۔",
    ),
    "lang_set": ("Language set to English.", "زبان اردو کر دی گئی۔"),
    "lang_invalid": ("Send /lang en or /lang ur.", "/lang en یا /lang ur بھیجیں۔"),
    "status_head": (
        "Subscription: {state}. Minimum level: {min_level}. Language: {lang_code}.",
        "رکنیت: {state}۔ کم از کم درجہ: {min_level}۔ زبان: {lang_code}۔",
    ),
    "status_line": ("{district}: level {level} ({name})", "{district}: درجہ {level} ({name})"),
    "status_all": (
        "All districts — {alerting} currently alerting.",
        "تمام اضلاع — اس وقت {alerting} میں الرٹ فعال ہے۔",
    ),
}
STATE_WORDS = {True: ("active", "فعال"), False: ("stopped", "بند")}

ACK_ANSWERS: dict[str, tuple[str, str]] = {
    "acknowledged": ("Acknowledged. Reminders for this alert are stopped for you.", "موصول ہو گیا۔ اس الرٹ کی یاد دہانیاں آپ کے لیے بند۔"),
    "resolved": ("This alert has already ended.", "یہ الرٹ پہلے ہی ختم ہو چکا ہے۔"),
    "not_found": ("Alert not found.", "الرٹ نہیں ملا۔"),
}

DEFAULT_MIN_LEVEL = 2  # level 1 is in-app only (levels.py), so 2 is the first level Telegram ever carries


def _reply(key: str, language: str, **values) -> str:
    en, ur = REPLIES[key]
    return (ur if language == LANGUAGE_UR else en).format(**values)


def _ack_key(chat_id: str) -> str:
    """How a Telegram acknowledgement is recorded in alert.payload
    ["acknowledged_by"] — the same "<channel>:<target>" shape the dispatcher
    compares against when deciding who still gets level 4/5 reminders."""
    return f"{CHANNEL_TELEGRAM}:{chat_id}"


def deep_link(bot_username: str, district: str) -> str:
    """https://t.me/<bot>?start=<code> — tapping it opens the bot and sends
    /start <code>, which subscribes in one tap."""
    return f"https://t.me/{bot_username}?start={district_code(district)}"


class TelegramBot:
    """Handles one webhook update at a time. Stateless — everything lives in
    alert_subscriptions (one row per chat: channel="telegram",
    target=<chat id>) and in the alerts table."""

    def __init__(self, channel: TelegramChannel):
        self.channel = channel

    def _subscription(self, db: Session, chat_id: str) -> AlertSubscription | None:
        return (
            db.query(AlertSubscription)
            .filter(AlertSubscription.channel == CHANNEL_TELEGRAM, AlertSubscription.target == chat_id)
            .order_by(AlertSubscription.id)
            .first()
        )

    def _say(self, chat_id: str, language: str, text: str) -> None:
        # Plain text escaped for HTML mode, then the disclaimer: every bot
        # reply can mention an alert level, so every one carries it
        # (CLAUDE.md rule 12).
        self.channel.send_text(chat_id, html.escape(f"{text}\n\n{_disclaimer(language)}"))

    def handle_update(self, db: Session, update: dict) -> str:
        """Process one Telegram Update. Returns a short label of what was
        done (for the log line and the tests). Never raises on a malformed
        update — Telegram re-delivers anything that is not answered 200."""
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            return self._handle_callback(db, callback)

        message = update.get("message")
        if not isinstance(message, dict):
            return "ignored"
        text = message.get("text")
        chat = message.get("chat") or {}
        if not isinstance(text, str) or chat.get("id") is None:
            return "ignored"
        chat_id = str(chat["id"])

        parts = text.strip().split()
        if not parts or not parts[0].startswith("/"):
            return self._help(db, chat_id)
        # "/level@lehar_bot 3" is how commands arrive in group chats.
        command = parts[0].split("@", 1)[0].lower()
        args = parts[1:]

        handlers = {
            "/start": self._start,
            "/stop": self._stop,
            "/level": self._level,
            "/lang": self._lang,
            "/status": self._status,
        }
        handler = handlers.get(command)
        if handler is None:
            return self._help(db, chat_id)
        return handler(db, chat_id, args)

    def _language_for(self, db: Session, chat_id: str) -> str:
        return message_language(self._subscription(db, chat_id))

    def _help(self, db: Session, chat_id: str, args: list[str] | None = None) -> str:
        self._say(chat_id, self._language_for(db, chat_id), _reply("help", self._language_for(db, chat_id)))
        return "help"

    def _start(self, db: Session, chat_id: str, args: list[str]) -> str:
        subscription = self._subscription(db, chat_id)
        language = message_language(subscription)
        if not args:
            # A bare /start never subscribes: "every district" would be a
            # flood of alerts nobody asked for.
            return self._help(db, chat_id)
        district = resolve_district(args[0])
        if district is None:
            self._say(chat_id, language, _reply("unknown_district", language, code=args[0][:64]))
            return "unknown_district"

        if subscription is None:
            subscription = AlertSubscription(
                channel=CHANNEL_TELEGRAM,
                target=chat_id,
                districts=[district],
                min_level=DEFAULT_MIN_LEVEL,
                language=LANGUAGE_EN,
                # Messaging the bot IS the opt-in: Telegram only lets a bot
                # write to a chat that started a conversation with it.
                verified=True,
            )
            db.add(subscription)
        else:
            districts = list(subscription.districts or [])
            if subscription.verified and districts and district not in districts:
                districts.append(district)
            elif not subscription.verified or not districts:
                # Re-subscribing after /stop starts fresh with this district.
                districts = [district]
            subscription.districts = districts  # reassigned: JSON columns don't track in-place edits
            subscription.verified = True
        db.commit()
        self._say(
            chat_id,
            language,
            _reply("subscribed", language, district=district, min_level=max(subscription.min_level, DEFAULT_MIN_LEVEL)),
        )
        return "subscribed"

    def _stop(self, db: Session, chat_id: str, args: list[str]) -> str:
        subscription = self._subscription(db, chat_id)
        language = message_language(subscription)
        if subscription is not None and subscription.verified:
            # Unverified == never messaged (the dispatcher's existing rule),
            # so /stop needs no new column and keeps the delivery history.
            subscription.verified = False
            db.commit()
        self._say(chat_id, language, _reply("stopped", language))
        return "stopped"

    def _level(self, db: Session, chat_id: str, args: list[str]) -> str:
        subscription = self._subscription(db, chat_id)
        language = message_language(subscription)
        if subscription is None or not subscription.verified:
            self._say(chat_id, language, _reply("not_subscribed", language))
            return "not_subscribed"
        if len(args) != 1 or args[0] not in {"1", "2", "3", "4", "5"}:
            self._say(chat_id, language, _reply("level_invalid", language))
            return "level_invalid"
        subscription.min_level = int(args[0])
        db.commit()
        text = _reply("level_set", language, min_level=subscription.min_level)
        if subscription.min_level == 1:
            text = f"{text}\n{_reply('level_one_note', language)}"
        self._say(chat_id, language, text)
        return "level_set"

    def _lang(self, db: Session, chat_id: str, args: list[str]) -> str:
        subscription = self._subscription(db, chat_id)
        language = message_language(subscription)
        if subscription is None or not subscription.verified:
            self._say(chat_id, language, _reply("not_subscribed", language))
            return "not_subscribed"
        if len(args) != 1 or args[0].lower() not in {LANGUAGE_EN, LANGUAGE_UR}:
            self._say(chat_id, language, _reply("lang_invalid", language))
            return "lang_invalid"
        subscription.language = args[0].lower()
        db.commit()
        self._say(chat_id, subscription.language, _reply("lang_set", subscription.language))
        return "lang_set"

    def _status(self, db: Session, chat_id: str, args: list[str]) -> str:
        # Imported here, not at module top: engine.py imports the channels
        # package, so a top-level import would be circular.
        from app.services.alerts.engine import highest_active_by_district

        subscription = self._subscription(db, chat_id)
        language = message_language(subscription)
        if subscription is None:
            self._say(chat_id, language, _reply("not_subscribed", language))
            return "not_subscribed"

        state_en, state_ur = STATE_WORDS[bool(subscription.verified)]
        lines = [
            _reply(
                "status_head",
                language,
                state=state_ur if language == LANGUAGE_UR else state_en,
                min_level=subscription.min_level,
                lang_code=subscription.language,
            )
        ]
        levels = {row["district"]: row for row in highest_active_by_district(db)}
        districts = subscription.districts or []
        if districts:
            for district in districts:
                row = levels.get(district)
                if row is None:
                    continue
                meta = get_level(row["level"])
                lines.append(
                    _reply(
                        "status_line",
                        language,
                        district=district,
                        level=row["level"],
                        name=meta.name_ur if language == LANGUAGE_UR else meta.name_en,
                    )
                )
        else:
            alerting = sum(1 for row in levels.values() if row["source"] == "alert")
            lines.append(_reply("status_all", language, alerting=alerting))
        self._say(chat_id, language, "\n".join(lines))
        return "status"

    def _handle_callback(self, db: Session, callback: dict) -> str:
        """The inline Acknowledge button. Marks the alert acknowledged — the
        same state change POST /api/v1/alerts/{id}/ack makes — and records
        WHICH chat acknowledged it, so level 4/5 reminders stop for that
        chat without stopping them for everyone else subscribed."""
        from app.services.alerts.engine import STATUS_ACKNOWLEDGED, STATUS_ACTIVE, STATUS_RESOLVED

        callback_id = callback.get("id")
        data = callback.get("data") or ""
        message = callback.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id") or (callback.get("from") or {}).get("id")
        if not isinstance(data, str) or not data.startswith(ACK_CALLBACK_PREFIX) or chat_id is None:
            return "ignored"
        chat_id = str(chat_id)
        language = self._language_for(db, chat_id)

        try:
            alert_id = int(data[len(ACK_CALLBACK_PREFIX):])
        except ValueError:
            alert_id = None
        alert = db.get(Alert, alert_id) if alert_id is not None else None

        if alert is None:
            outcome = "not_found"
        elif alert.status == STATUS_RESOLVED:
            outcome = "resolved"
        else:
            outcome = "acknowledged"
            if alert.status == STATUS_ACTIVE:
                alert.status = STATUS_ACKNOWLEDGED
            acknowledged_by = list((alert.payload or {}).get("acknowledged_by") or [])
            if _ack_key(chat_id) not in acknowledged_by:
                acknowledged_by.append(_ack_key(chat_id))
            alert.payload = {**(alert.payload or {}), "acknowledged_by": acknowledged_by}
            db.commit()

        if callback_id is not None:
            en, ur = ACK_ANSWERS[outcome]
            self.channel.api_call(
                "answerCallbackQuery",
                {"callback_query_id": callback_id, "text": ur if language == LANGUAGE_UR else en},
            )
        return outcome
