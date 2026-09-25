"""Delivery channels and the dispatcher that records every attempt.

Phase 2 ships ONE working channel — in-app (the alert row itself, which the
console and the local frontend read through GET /api/v1/alerts) — plus a
structured log line. Telegram and email arrive in Phase 3.

The point of this file in Phase 2 is the *interface*: `AlertChannel` is what
Phase 3's TelegramChannel and EmailChannel implement, and the dispatcher
already walks real alert_subscriptions rows, already writes real
alert_deliveries rows, and already isolates per-channel failures. A channel
that is not wired up yet records an honest `status="skipped"` delivery with
the reason — never a fabricated "sent" (CLAUDE.md rule 4).
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from app.db import Alert, AlertDelivery, AlertSubscription
from app.services.alerts.levels import CHANNEL_EMAIL, CHANNEL_IN_APP, CHANNEL_TELEGRAM, channels_for

logger = logging.getLogger("app.alerts.delivery")

STATUS_SENT = "sent"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

LANGUAGE_EN = "en"
LANGUAGE_UR = "ur"

# Phase 3 replaces these with real transports; until then the dispatcher
# records a skipped delivery naming the phase, so a console showing
# "skipped — Telegram delivery arrives in Phase 3" is telling the truth.
NOT_YET_IMPLEMENTED = "Channel not enabled in Phase 2 — delivery transport arrives in Phase 3."


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
    gives Phase 3 its per-channel failure isolation for free — the
    dispatcher below treats every channel the same way."""

    name: str = "abstract"

    def send(self, alert: Alert, subscription: AlertSubscription | None) -> DeliveryResult:  # pragma: no cover
        raise NotImplementedError


class InAppChannel(AlertChannel):
    """The alert row IS the in-app delivery — it is already committed by the
    time this runs, and the console reads it through GET /api/v1/alerts. So
    this channel performs no I/O and always succeeds; it exists so that
    every delivery, including the in-app one, has an auditable
    alert_deliveries row rather than being implicit."""

    name = CHANNEL_IN_APP

    def send(self, alert: Alert, subscription: AlertSubscription | None) -> DeliveryResult:
        started = time.monotonic()
        logger.info(
            "alert.delivery channel=%s alert_id=%s district=%s type=%s level=%s",
            self.name,
            alert.id,
            alert.district_code,
            alert.type,
            alert.level,
        )
        return DeliveryResult(
            channel=self.name,
            status=STATUS_SENT,
            latency_ms=int((time.monotonic() - started) * 1000),
            sent_at=datetime.now(timezone.utc),
        )


class PendingChannel(AlertChannel):
    """A channel declared by the level metadata whose transport does not
    exist yet. Records a skipped delivery naming why — the honest
    placeholder Phase 3 replaces."""

    def __init__(self, name: str):
        self.name = name

    def send(self, alert: Alert, subscription: AlertSubscription | None) -> DeliveryResult:
        logger.info(
            "alert.delivery channel=%s alert_id=%s status=skipped reason=not_implemented",
            self.name,
            alert.id,
        )
        return DeliveryResult(channel=self.name, status=STATUS_SKIPPED, attempts=0, error=NOT_YET_IMPLEMENTED)


def default_channels() -> dict[str, AlertChannel]:
    """The channel registry the dispatcher uses. Phase 3 swaps the two
    PendingChannel entries for real transports and changes nothing else."""
    return {
        CHANNEL_IN_APP: InAppChannel(),
        CHANNEL_TELEGRAM: PendingChannel(CHANNEL_TELEGRAM),
        CHANNEL_EMAIL: PendingChannel(CHANNEL_EMAIL),
    }


def subscription_matches(subscription: AlertSubscription, alert: Alert) -> bool:
    """True when this subscription should receive this alert: the channel is
    one the alert's level actually uses, the level is at or above the
    subscriber's min_level, and the district is one they asked for (an empty
    or null district list means "every district")."""
    if subscription.channel not in channels_for(alert.level):
        return False
    if alert.level < subscription.min_level:
        return False
    districts = subscription.districts or []
    return not districts or alert.district_code in districts


class DeliveryDispatcher:
    """Fans one alert out to every channel its level declares, records an
    alert_deliveries row per attempt, and returns the results.

    Failure isolation is the contract: one channel raising, timing out or
    returning FAILED never stops the others and never fails the alert run.
    """

    def __init__(self, channels: dict[str, AlertChannel] | None = None):
        self._channels = channels if channels is not None else default_channels()

    def _record(
        self,
        db,
        alert: Alert,
        result: DeliveryResult,
        subscription: AlertSubscription | None,
    ) -> AlertDelivery:
        delivery = AlertDelivery(
            alert_id=alert.id,
            subscription_id=subscription.id if subscription is not None else None,
            channel=result.channel,
            status=result.status,
            attempts=result.attempts,
            latency_ms=result.latency_ms,
            sent_at=result.sent_at,
            error=result.error,
        )
        db.add(delivery)
        return delivery

    def _attempt(self, channel: AlertChannel, alert: Alert, subscription: AlertSubscription | None) -> DeliveryResult:
        try:
            return channel.send(alert, subscription)
        except Exception as exc:  # channel bugs must not break the run
            logger.exception("Channel %s raised while delivering alert %s", channel.name, alert.id)
            return DeliveryResult(channel=channel.name, status=STATUS_FAILED, error=str(exc)[:500])

    def dispatch(self, db, alert: Alert, subscriptions: list[AlertSubscription]) -> list[DeliveryResult]:
        """Deliver `alert` and write one alert_deliveries row per attempt.

        In-app is delivered once per alert with no subscription. Every other
        channel this level declares is delivered once per MATCHING verified
        subscription — an unverified subscriber is skipped, so Phase 3 can
        never message an address nobody confirmed."""
        results: list[DeliveryResult] = []
        level_channels = channels_for(alert.level)

        if CHANNEL_IN_APP in level_channels:
            result = self._attempt(self._channels[CHANNEL_IN_APP], alert, None)
            self._record(db, alert, result, None)
            results.append(result)

        for subscription in subscriptions:
            if not subscription_matches(subscription, alert):
                continue
            channel = self._channels.get(subscription.channel)
            if channel is None:
                continue
            if not subscription.verified:
                result = DeliveryResult(
                    channel=subscription.channel,
                    status=STATUS_SKIPPED,
                    attempts=0,
                    error="Subscription is not verified.",
                )
            else:
                result = self._attempt(channel, alert, subscription)
            self._record(db, alert, result, subscription)
            results.append(result)

        return results
