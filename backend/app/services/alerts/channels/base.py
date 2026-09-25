"""The types every delivery channel shares.

Split out of channels/__init__.py (LEHAR Phase 3) only so that telegram.py
and email.py can import them without importing the dispatcher that in turn
imports them — a circular import. Everything here is re-exported from
app.services.alerts.channels, so `from app.services.alerts.channels import
DeliveryResult` keeps working exactly as it did in Phase 2.
"""

from dataclasses import dataclass
from datetime import datetime

from app.db import Alert, AlertSubscription
from ml.districts import DISTRICTS, district_for_code

STATUS_SENT = "sent"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

LANGUAGE_EN = "en"
LANGUAGE_UR = "ur"


@dataclass
class DeliveryResult:
    """One channel's attempt at one alert, for one subscription (or None
    for in-app, which has no subscriber)."""

    channel: str
    status: str  # STATUS_SENT | STATUS_FAILED | STATUS_SKIPPED
    attempts: int = 1
    latency_ms: int | None = None
    error: str | None = None
    sent_at: datetime | None = None


class AlertChannel:
    """Interface every delivery channel implements.

    `send` must NEVER raise: a channel that cannot deliver returns a
    DeliveryResult with STATUS_FAILED and a short error string. That is what
    gives per-channel failure isolation for free — the dispatcher treats
    every channel the same way.

    `enabled` is False for a channel that is declared but cannot deliver
    (its credentials are not configured). A disabled channel still answers
    send() with an honest skipped result; the dispatcher just never spends
    the per-run send budget on it and never schedules re-sends through it.
    """

    name: str = "abstract"
    enabled: bool = True

    def send(self, alert: Alert, subscription: AlertSubscription | None) -> DeliveryResult:  # pragma: no cover
        raise NotImplementedError


def message_language(subscription: AlertSubscription | None) -> str:
    """The language a subscriber asked for; anything unrecognised falls back
    to English rather than failing the send."""
    if subscription is not None and subscription.language == LANGUAGE_UR:
        return LANGUAGE_UR
    return LANGUAGE_EN


def resolve_district(code: str) -> str | None:
    """A district name from a code ("dera_ghazi_khan", the form Telegram
    deep links carry — see ml/districts.py's district_code), tolerant of case
    and of the plain name ("Multan"). None when nothing matches."""
    cleaned = code.strip().lower()
    name = district_for_code(cleaned)
    if name is not None:
        return name
    for candidate in DISTRICTS:
        if candidate.lower() == cleaned:
            return candidate
    return None
