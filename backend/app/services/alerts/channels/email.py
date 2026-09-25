"""Email delivery channel via Brevo's transactional API (LEHAR Phase 3).

HTTPS only — POST https://api.brevo.com/v3/smtp/email — never SMTP: Render's
free tier blocks outbound SMTP ports, and Brevo's free plan (300 emails/day)
is reachable over plain HTTPS from anywhere.

Double opt-in, so LEHAR never emails an address its owner did not confirm:

    POST /alerts/email/subscribe  -> an UNVERIFIED alert_subscriptions row,
                                     plus a verification email with a signed
                                     link that expires after 48 h
    GET  /alerts/email/verify     -> verified; alerts start
    GET  /alerts/email/unsubscribe-> unverified again; alerts stop

The links carry signed JWTs (the project's existing python-jose + JWT_SECRET,
see app/auth.py) with their own `type` claims, so a verification token can
never be used as a login token or vice versa. The requested preferences
(districts, level, language) travel INSIDE the verification token and are
only applied when the owner clicks — so someone who types another person's
address into the form can neither subscribe them nor change their settings.

The message text is the alert row's own title/body (templates.py, CLAUDE.md
rule 10), wrapped in a small fixed bilingual layout.
"""

import html
import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from jose import JWTError, jwt

from app.auth import JWT_ALGORITHM
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
)
from app.services.alerts.levels import CHANNEL_EMAIL, DISCLAIMER_EN, DISCLAIMER_UR

logger = logging.getLogger("app.alerts.email")

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"

TOKEN_TYPE_VERIFY = "alert_email_verify"
TOKEN_TYPE_UNSUBSCRIBE = "alert_email_unsubscribe"
VERIFY_TOKEN_TTL = timedelta(hours=48)

EMAIL_DISABLED = (
    "Email delivery (LEHAR Phase 3) is disabled: set BREVO_API_KEY, ALERT_FROM_EMAIL and PUBLIC_BASE_URL."
)

REMINDER_LINE = {
    LANGUAGE_EN: "Reminder: this alert is STILL ACTIVE. It is re-sent every 6 hours until it ends.",
    LANGUAGE_UR: "یاد دہانی: یہ الرٹ ابھی تک فعال ہے۔ ختم ہونے تک ہر 6 گھنٹے بعد دوبارہ بھیجا جاتا ہے۔",
}
UNSUBSCRIBE_TEXT = {LANGUAGE_EN: "Unsubscribe", LANGUAGE_UR: "رکنیت ختم کریں"}
FOOTER_EN = "You receive this because you subscribed to LEHAR research alerts and confirmed your address."
FOOTER_UR = "آپ کو یہ ای میل اس لیے ملی کیونکہ آپ نے لہر تحقیقی الرٹ کی رکنیت لی اور اپنے پتے کی تصدیق کی۔"


# --- signed links -------------------------------------------------------------

def make_verify_token(
    subscription_id: int,
    email: str,
    districts: list[str],
    min_level: int,
    language: str,
    now: datetime | None = None,
) -> str:
    issued = now or datetime.now(timezone.utc)
    payload = {
        "type": TOKEN_TYPE_VERIFY,
        "sid": subscription_id,
        "email": email,
        "districts": districts,
        "min_level": min_level,
        "language": language,
        "exp": int((issued + VERIFY_TOKEN_TTL).timestamp()),
    }
    return jwt.encode(payload, get_settings().jwt_secret, algorithm=JWT_ALGORITHM)


def make_unsubscribe_token(subscription_id: int, email: str) -> str:
    # No expiry on purpose: an unsubscribe link in a months-old email must
    # still work (it can only ever turn alerts OFF).
    payload = {"type": TOKEN_TYPE_UNSUBSCRIBE, "sid": subscription_id, "email": email}
    return jwt.encode(payload, get_settings().jwt_secret, algorithm=JWT_ALGORITHM)


def decode_token(token: str, expected_type: str) -> dict:
    """The token's claims. Raises jose.JWTError for a bad signature, an
    expired verification link, or a token of the wrong type."""
    payload = jwt.decode(token, get_settings().jwt_secret, algorithms=[JWT_ALGORITHM])
    if payload.get("type") != expected_type:
        raise JWTError("Unexpected token type")
    return payload


def _link(base_url: str, path: str, token: str) -> str:
    prefix = get_settings().api_v1_prefix
    return f"{base_url.rstrip('/')}{prefix}/alerts/email/{path}?{urlencode({'token': token})}"


# --- templates ------------------------------------------------------------------

def _html_block(text: str, language: str) -> str:
    direction = ' dir="rtl" lang="ur"' if language == LANGUAGE_UR else ' lang="en"'
    return f"<div{direction}>{html.escape(text).replace(chr(10), '<br>')}</div>"


def render_alert_email(
    alert: Alert, language: str, unsubscribe_url: str, reminder: bool = False
) -> tuple[str, str, str]:
    """(subject, html, text) for one alert. Bilingual: the subscriber's
    language first, the other one underneath, so a household member who
    reads the other language can still act on it."""
    other = LANGUAGE_EN if language == LANGUAGE_UR else LANGUAGE_UR
    sections = {
        LANGUAGE_EN: (alert.title_en, alert.body_en),
        LANGUAGE_UR: (alert.title_ur, alert.body_ur),
    }
    title, _ = sections[language]
    subject = f"[LEHAR level {alert.level}] {title}"
    if reminder:
        subject = f"{'یاد دہانی' if language == LANGUAGE_UR else 'Reminder'}: {subject}"

    html_parts = ["<!doctype html><html><body>"]
    text_parts: list[str] = []
    if reminder:
        html_parts.append(f"<p><strong>{html.escape(REMINDER_LINE[language])}</strong></p>")
        text_parts.append(REMINDER_LINE[language])
    for lang in (language, other):
        section_title, section_body = sections[lang]
        html_parts.append(f"<h2>{html.escape(section_title)}</h2>")
        html_parts.append(_html_block(section_body, lang))
        html_parts.append("<hr>")
        text_parts.append(f"{section_title}\n\n{section_body}")

    # The bodies already end with the disclaimer (templates.py); the footer
    # repeats it so it is present even in a client that clips long mail.
    footer_text = f"{DISCLAIMER_EN}\n{DISCLAIMER_UR}\n{FOOTER_EN}\n{FOOTER_UR}"
    html_parts.append(_html_block(footer_text, LANGUAGE_EN))
    html_parts.append(
        f'<p><a href="{html.escape(unsubscribe_url)}">'
        f"{UNSUBSCRIBE_TEXT[LANGUAGE_EN]} / {UNSUBSCRIBE_TEXT[LANGUAGE_UR]}</a></p>"
    )
    html_parts.append("</body></html>")
    text_parts.append(footer_text)
    text_parts.append(f"{UNSUBSCRIBE_TEXT[LANGUAGE_EN]} / {UNSUBSCRIBE_TEXT[LANGUAGE_UR]}: {unsubscribe_url}")

    separator = "\n\n" + "-" * 40 + "\n\n"
    return subject, "".join(html_parts), separator.join(text_parts)


def render_verification_email(verify_url: str, districts: list[str], min_level: int) -> tuple[str, str, str]:
    """(subject, html, text) for the double opt-in email — fixed text in
    both languages, nothing sent until the link is clicked."""
    district_list = ", ".join(districts)
    en = (
        f"Please confirm that you want LEHAR research alerts for: {district_list} "
        f"(level {min_level} and above).\n\nConfirm: {verify_url}\n\n"
        "This link expires in 48 hours. If you did not ask for this, ignore this email — nothing will be sent."
    )
    ur = (
        f"براہ کرم تصدیق کریں کہ آپ ان اضلاع کے لیے لہر تحقیقی الرٹ چاہتے ہیں: {district_list} "
        f"(درجہ {min_level} اور اس سے زیادہ)۔\n\nتصدیق: {verify_url}\n\n"
        "یہ لنک 48 گھنٹے میں ختم ہو جائے گا۔ اگر آپ نے یہ درخواست نہیں کی تو اس ای میل کو نظر انداز کریں — کچھ نہیں بھیجا جائے گا۔"
    )
    footer = f"{DISCLAIMER_EN}\n{DISCLAIMER_UR}"
    subject = "Confirm your LEHAR alert subscription / لہر الرٹ کی تصدیق"
    body_html = (
        "<!doctype html><html><body>"
        f"{_html_block(en, LANGUAGE_EN)}"
        f'<p><a href="{html.escape(verify_url)}">Confirm subscription / تصدیق کریں</a></p><hr>'
        f"{_html_block(ur, LANGUAGE_UR)}<hr>{_html_block(footer, LANGUAGE_EN)}"
        "</body></html>"
    )
    return subject, body_html, f"{en}\n\n{'-' * 40}\n\n{ur}\n\n{footer}"


# --- the channel ------------------------------------------------------------------

class EmailChannel(AlertChannel):
    """Sends alert and verification emails through Brevo. Disabled (and
    honest about it) until BREVO_API_KEY, ALERT_FROM_EMAIL and
    PUBLIC_BASE_URL are all set."""

    name = CHANNEL_EMAIL

    def __init__(
        self,
        api_key: str | None = None,
        from_email: str | None = None,
        from_name: str | None = None,
        public_base_url: str | None = None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.brevo_api_key
        self._from_email = from_email if from_email is not None else settings.alert_from_email
        self._from_name = from_name if from_name is not None else settings.alert_from_name
        self.public_base_url = public_base_url if public_base_url is not None else settings.public_base_url
        self._client = client
        self._sleep = sleep

    @property
    def enabled(self) -> bool:
        return bool(self._api_key and self._from_email and self.public_base_url)

    def send_email(
        self, to: str, subject: str, html_content: str, text_content: str, unsubscribe_url: str | None = None
    ) -> PostOutcome:
        if not self.enabled:
            return PostOutcome(ok=False, attempts=0, error=EMAIL_DISABLED)
        payload: dict = {
            "sender": {"name": self._from_name, "email": self._from_email},
            "to": [{"email": to}],
            "subject": subject,
            "htmlContent": html_content,
            "textContent": text_content,
            "tags": ["lehar-alert"],
        }
        if unsubscribe_url is not None:
            # RFC 8058 one-click unsubscribe: mail clients show their own
            # "Unsubscribe" button and POST to this URL.
            payload["headers"] = {
                "List-Unsubscribe": f"<{unsubscribe_url}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            }
        headers = {"api-key": self._api_key, "accept": "application/json"}
        return post_json(
            BREVO_SEND_URL, payload, headers=headers, client=self._client, sleep=self._sleep, redact=self._api_key
        )

    def unsubscribe_url(self, subscription: AlertSubscription) -> str:
        return _link(self.public_base_url, "unsubscribe", make_unsubscribe_token(subscription.id, subscription.target))

    def verify_url(self, subscription: AlertSubscription, districts: list[str], min_level: int, language: str) -> str:
        token = make_verify_token(subscription.id, subscription.target, districts, min_level, language)
        return _link(self.public_base_url, "verify", token)

    def send_verification(
        self, subscription: AlertSubscription, districts: list[str], min_level: int, language: str
    ) -> PostOutcome:
        subject, body_html, body_text = render_verification_email(
            self.verify_url(subscription, districts, min_level, language), districts, min_level
        )
        return self.send_email(subscription.target, subject, body_html, body_text)

    def send(
        self, alert: Alert, subscription: AlertSubscription | None, reminder: bool = False
    ) -> DeliveryResult:
        if not self.enabled:
            return DeliveryResult(channel=self.name, status=STATUS_SKIPPED, attempts=0, error=EMAIL_DISABLED)
        if subscription is None:
            return DeliveryResult(channel=self.name, status=STATUS_SKIPPED, attempts=0, error="No subscriber.")

        unsubscribe_url = self.unsubscribe_url(subscription)
        subject, body_html, body_text = render_alert_email(
            alert, message_language(subscription), unsubscribe_url, reminder
        )
        outcome = self.send_email(subscription.target, subject, body_html, body_text, unsubscribe_url)
        logger.info(
            "alert.delivery channel=email alert_id=%s subscription_id=%s ok=%s attempts=%s",
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
