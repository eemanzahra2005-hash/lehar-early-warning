"""Alert delivery channel endpoints (LEHAR Phase 3) — all additive.

    POST     /api/v1/alerts/telegram/webhook   Telegram -> LEHAR updates
    GET      /api/v1/alerts/telegram/link      t.me deep link for a district
    POST     /api/v1/alerts/email/subscribe    start the email double opt-in
    GET      /api/v1/alerts/email/verify       confirm (link in the email)
    GET/POST /api/v1/alerts/email/unsubscribe  stop (link in every email)

Auth model:
  - the webhook is called by Telegram's servers, which have no account here.
    It is guarded by TELEGRAM_WEBHOOK_SECRET, which Telegram echoes in the
    X-Telegram-Bot-Api-Secret-Token header because scripts/
    set_telegram_webhook.py registered it. Unset secret = 503, never open.
  - the email endpoints are open (a farmer subscribes without an account),
    and safe to be: subscribe only ever sends a confirmation email, and
    verify/unsubscribe act only on a token LEHAR signed. subscribe shares the
    auth endpoints' per-IP rate limit, so it cannot be used to spray
    confirmation emails.
"""

import hmac
import html
import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from jose import JWTError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import AlertSubscription, get_db
from app.dependencies import get_email_channel, get_telegram_bot
from app.rate_limit import auth_rate_limit, limiter
from app.schemas import EmailSubscribeRequest, EmailSubscribeResponse, TelegramWebhookResponse
from app.services.alerts.channels.base import resolve_district
from app.services.alerts.levels import CHANNEL_EMAIL, DISCLAIMER_EN, DISCLAIMER_UR
from ml.districts import DISTRICTS, district_code

logger = logging.getLogger("app.alerts.channels")

router = APIRouter(prefix="/alerts", tags=["alerts"])


# --- Telegram ------------------------------------------------------------------

@router.post("/telegram/webhook", response_model=TelegramWebhookResponse)
def telegram_webhook(
    update: dict[str, Any] = Body(...),
    x_telegram_bot_api_secret_token: str | None = Header(default=None, alias="X-Telegram-Bot-Api-Secret-Token"),
    db: Session = Depends(get_db),
    bot=Depends(get_telegram_bot),
) -> TelegramWebhookResponse:
    """Receives one Telegram Update (a command message or an Acknowledge
    button press).

    Once authenticated it always answers 200, even when handling failed:
    Telegram re-delivers any update that is not answered 200, so a single
    bad update would otherwise be retried at us indefinitely. The failure
    is logged instead."""
    settings = get_settings()
    expected = settings.telegram_webhook_secret
    if not expected or not bot.channel.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram webhook is not configured: set TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET.",
        )
    # Constant-time compare, the same standard as POST /alerts/run.
    if x_telegram_bot_api_secret_token is None or not hmac.compare_digest(
        x_telegram_bot_api_secret_token, expected
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret.")

    try:
        handled = bot.handle_update(db, update)
    except Exception:
        db.rollback()
        logger.exception("Telegram update %s could not be handled", update.get("update_id"))
        handled = "error"
    logger.info("telegram.webhook update_id=%s handled=%s", update.get("update_id"), handled)
    return TelegramWebhookResponse(ok=True, handled=handled)


@router.get("/telegram/link")
def telegram_link(district: str = Query(..., min_length=1, max_length=64)) -> dict:
    """The one-tap subscribe link for a district, for the console and the
    local frontend to show next to a district's alert level."""
    username = get_settings().telegram_bot_username.lstrip("@")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram is not configured: set TELEGRAM_BOT_USERNAME.",
        )
    name = resolve_district(district)
    if name is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown district: {district}")
    code = district_code(name)
    return {
        "district": name,
        "district_code": code,
        "url": f"https://t.me/{username}?start={code}",
        "disclaimer": DISCLAIMER_EN,
    }


# --- Email double opt-in ----------------------------------------------------------

def _page(status_code: int, heading_en: str, text_en: str, heading_ur: str, text_ur: str) -> HTMLResponse:
    """A tiny bilingual result page for the links people click in email."""
    body = (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>LEHAR alerts</title></head><body>"
        f"<h1>{html.escape(heading_en)}</h1><p>{html.escape(text_en)}</p>"
        f"<div dir=\"rtl\" lang=\"ur\"><h1>{html.escape(heading_ur)}</h1><p>{html.escape(text_ur)}</p></div>"
        f"<hr><p>{html.escape(DISCLAIMER_EN)}</p><p dir=\"rtl\" lang=\"ur\">{html.escape(DISCLAIMER_UR)}</p>"
        "</body></html>"
    )
    return HTMLResponse(content=body, status_code=status_code)


def _invalid_link_page() -> HTMLResponse:
    return _page(
        status.HTTP_400_BAD_REQUEST,
        "Link invalid or expired",
        "This link is not valid, or it has expired. Please subscribe again from the LEHAR app.",
        "لنک درست نہیں یا ختم ہو چکا ہے",
        "یہ لنک درست نہیں یا اس کی مدت ختم ہو چکی ہے۔ براہ کرم لہر ایپ سے دوبارہ رکنیت لیں۔",
    )


def _subscription_for(db: Session, claims: dict) -> AlertSubscription | None:
    """The row a token names — and only if it is still the same address the
    token was issued for."""
    subscription = db.get(AlertSubscription, claims.get("sid"))
    if subscription is None or subscription.channel != CHANNEL_EMAIL or subscription.target != claims.get("email"):
        return None
    return subscription


@router.post("/email/subscribe", response_model=EmailSubscribeResponse, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(auth_rate_limit)
def subscribe_email(
    request: Request,
    payload: EmailSubscribeRequest,
    db: Session = Depends(get_db),
    channel=Depends(get_email_channel),
) -> EmailSubscribeResponse:
    """Start the double opt-in: send a confirmation email and nothing else.

    The requested districts/level/language ride inside the signed link and
    are applied only when it is clicked, so an existing, verified
    subscription is never changed by someone who merely knows the address.
    The response is identical whether or not the address was already
    subscribed, so it can't be used to probe who is."""
    if not channel.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email alerts are not configured: set BREVO_API_KEY, ALERT_FROM_EMAIL and PUBLIC_BASE_URL.",
        )

    districts: list[str] = []
    for raw in payload.districts:
        name = resolve_district(raw)
        if name is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown district: {raw}")
        if name not in districts:
            districts.append(name)

    email = payload.email.strip().lower()
    subscription = (
        db.query(AlertSubscription)
        .filter(AlertSubscription.channel == CHANNEL_EMAIL, AlertSubscription.target == email)
        .order_by(AlertSubscription.id)
        .first()
    )
    if subscription is None:
        subscription = AlertSubscription(
            channel=CHANNEL_EMAIL,
            target=email,
            districts=districts,
            min_level=payload.min_level,
            language=payload.language,
            verified=False,
        )
        db.add(subscription)
        db.commit()
        db.refresh(subscription)

    outcome = channel.send_verification(subscription, districts, payload.min_level, payload.language)
    if not outcome.ok:
        logger.warning("Verification email for subscription %s failed: %s", subscription.id, outcome.error)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The confirmation email could not be sent. Please try again later.",
        )
    return EmailSubscribeResponse(
        status="verification_sent",
        detail="Check your inbox and click the confirmation link within 48 hours. No alerts are sent until you do.",
        disclaimer=DISCLAIMER_EN,
    )


@router.get("/email/verify", response_class=HTMLResponse)
def verify_email(token: str = Query(..., max_length=4096), db: Session = Depends(get_db)) -> HTMLResponse:
    from app.services.alerts.channels.email import TOKEN_TYPE_VERIFY, decode_token

    try:
        claims = decode_token(token, TOKEN_TYPE_VERIFY)
    except JWTError:
        return _invalid_link_page()
    subscription = _subscription_for(db, claims)
    districts = claims.get("districts") or []
    min_level = claims.get("min_level")
    language = claims.get("language")
    if (
        subscription is None
        or not districts
        or any(name not in DISTRICTS for name in districts)
        or min_level not in (2, 3, 4, 5)
        or language not in ("en", "ur")
    ):
        return _invalid_link_page()

    subscription.districts = list(districts)
    subscription.min_level = min_level
    subscription.language = language
    subscription.verified = True
    db.commit()
    return _page(
        status.HTTP_200_OK,
        "Subscription confirmed",
        f"You will receive LEHAR research alerts for {', '.join(districts)} at level {min_level} and above. "
        "Every email has an unsubscribe link.",
        "رکنیت کی تصدیق ہو گئی",
        f"آپ کو {', '.join(districts)} کے لیے درجہ {min_level} اور اس سے زیادہ کے لہر تحقیقی الرٹ ملیں گے۔ "
        "ہر ای میل میں رکنیت ختم کرنے کا لنک موجود ہے۔",
    )


@router.api_route("/email/unsubscribe", methods=["GET", "POST"], response_class=HTMLResponse)
def unsubscribe_email(token: str = Query(..., max_length=4096), db: Session = Depends(get_db)) -> HTMLResponse:
    """GET for the link in the email body; POST for mail clients' one-click
    List-Unsubscribe button (RFC 8058). Both only ever turn alerts OFF."""
    from app.services.alerts.channels.email import TOKEN_TYPE_UNSUBSCRIBE, decode_token

    try:
        claims = decode_token(token, TOKEN_TYPE_UNSUBSCRIBE)
    except JWTError:
        return _invalid_link_page()
    subscription = _subscription_for(db, claims)
    if subscription is None:
        return _invalid_link_page()
    if subscription.verified:
        # Unverified == never messaged, so no new column is needed and the
        # delivery history stays intact.
        subscription.verified = False
        db.commit()
    return _page(
        status.HTTP_200_OK,
        "Unsubscribed",
        "You will not receive any more LEHAR alert emails. You can subscribe again at any time from the LEHAR app.",
        "رکنیت ختم ہو گئی",
        "آپ کو لہر الرٹ کی مزید ای میلز نہیں ملیں گی۔ آپ کسی بھی وقت لہر ایپ سے دوبارہ رکنیت لے سکتے ہیں۔",
    )
