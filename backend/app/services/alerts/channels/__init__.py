"""Delivery channels and the dispatcher that records every attempt.

Phase 2 shipped the in-app channel (the alert row itself, which the console
and the local frontend read through GET /api/v1/alerts) plus the
`AlertChannel` interface. LEHAR Phase 3 drops the real transports in behind
that same interface, unchanged:

    telegram.py   Telegram Bot API sendMessage + the webhook bot commands
    email.py      Brevo transactional email + the double opt-in links
    _http.py      the shared HTTPS POST with timeouts and retries
    base.py       DeliveryResult / AlertChannel / status constants

The dispatcher walks alert_subscriptions rows, writes one alert_deliveries
row per attempt (including skips — "why didn't I get this?" always has an
answer in the data), and isolates per-channel failures. A channel whose
credentials are not configured records an honest `status="skipped"`
delivery naming what is missing — never a fabricated "sent" (CLAUDE.md
rule 4).

What a Phase 3 run delivers, in order of priority (highest level first,
because a send budget that runs out should run out on the least urgent):

  * every NEW alert at level >= 2 to every matching verified subscriber;
  * every still-open level 4/5 alert again, every RESEND_INTERVAL (6 h),
    to each subscriber who has not pressed Acknowledge on it;
  * anything a previous run deferred (budget exhausted, or its channel
    paused after repeated failures).

Level 1 is NEVER pushed to Telegram or email: it is the calm baseline and
the per-field irrigation advisory, and stays in the app (levels.py).
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.db import Alert, AlertDelivery, AlertSubscription
from app.metrics import deliveries_total, delivery_latency_seconds
from app.services.alerts.channels.base import (
    LANGUAGE_EN,
    LANGUAGE_UR,
    STATUS_FAILED,
    STATUS_SENT,
    STATUS_SKIPPED,
    AlertChannel,
    DeliveryResult,
)
from app.services.alerts.levels import CHANNEL_EMAIL, CHANNEL_IN_APP, CHANNEL_TELEGRAM, channels_for

__all__ = [
    "LANGUAGE_EN",
    "LANGUAGE_UR",
    "STATUS_FAILED",
    "STATUS_SENT",
    "STATUS_SKIPPED",
    "AlertChannel",
    "DeliveryResult",
]

logger = logging.getLogger("app.alerts.delivery")

# Kept from Phase 2 for PendingChannel, which remains available for any
# future channel that is declared before its transport exists.
NOT_YET_IMPLEMENTED = "Channel not enabled in Phase 2 — delivery transport arrives in Phase 3."

# The lowest level that may ever leave the app. Level 1 is in-app only —
# levels.py already says so through each level's channel list; this is the
# same rule stated a second time, deliberately, at the point of sending.
MIN_PUSH_LEVEL = 2

# Level 4 (Purple, "move people now") and 5 (Black, emergency) are re-sent
# while they stay open: a phone that was off, or a message buried under a
# family group chat, must not be the reason a farmer missed an evacuation.
RESEND_MIN_LEVEL = 4
RESEND_INTERVAL = timedelta(hours=6)

# After this many FAILED sends in a row on one channel within one run, the
# rest of that channel's sends in the run are deferred instead of each
# waiting out its own timeouts and retries. The other channels carry on.
CONSECUTIVE_FAILURES_TO_PAUSE = 3

# Every "deferred" skip starts with this, and a later run's re-send pass
# looks for it: a deferred delivery is owed, not abandoned.
DEFERRED_PREFIX = "Deferred:"
BUDGET_DEFERRED = (
    f"{DEFERRED_PREFIX} ALERT_MAX_SENDS_PER_RUN was reached in this run; it is retried on the next run."
)
PAUSED_DEFERRED = (
    f"{DEFERRED_PREFIX} this channel failed {CONSECUTIVE_FAILURES_TO_PAUSE} times in a row in this run; "
    "it is retried on the next run."
)

# alert.status values, spelled out here because engine.py imports this
# package (importing engine.py back would be circular).
_OPEN_STATUSES = ("active", "acknowledged")


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
    exist yet. Records a skipped delivery naming why."""

    enabled = False

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
    """The channel registry the dispatcher uses. Telegram and email read
    their credentials from Settings and disable themselves cleanly when
    those are empty (see telegram.py / email.py)."""
    # Imported here so that importing this package for its types never
    # pulls in httpx — only building real channels does.
    from app.services.alerts.channels.email import EmailChannel
    from app.services.alerts.channels.telegram import TelegramChannel

    return {
        CHANNEL_IN_APP: InAppChannel(),
        CHANNEL_TELEGRAM: TelegramChannel(),
        CHANNEL_EMAIL: EmailChannel(),
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


def acknowledged_by(alert: Alert, subscription: AlertSubscription) -> bool:
    """Has THIS subscriber pressed Acknowledge on this alert? (Telegram's
    button records "<channel>:<target>" in the alert payload.) Only affects
    re-sends; the first send always goes out."""
    marks = (alert.payload or {}).get("acknowledged_by") or []
    return f"{subscription.channel}:{subscription.target}" in marks


class SendBudget:
    """How many external sends (Telegram + email, re-sends included) one run
    may still make. `limit=None` is unlimited — used by the single-alert
    dispatch() kept from Phase 2."""

    def __init__(self, limit: int | None):
        self.limit = limit
        self.used = 0

    def take(self) -> bool:
        if self.limit is not None and self.used >= self.limit:
            return False
        self.used += 1
        return True


@dataclass
class _SendJob:
    alert: Alert
    subscription: AlertSubscription
    channel: AlertChannel
    # True when this subscriber was already sent (or attempted) this alert,
    # so the message is labelled a reminder.
    reminder: bool = False
    # True for anything owed from an earlier run (re-send or deferred).
    carried_over: bool = False

    @property
    def priority(self) -> tuple:
        # Highest level first; within a level, this run's new alerts before
        # carried-over sends; then a stable, reproducible order.
        return (-self.alert.level, self.carried_over, self.alert.id, self.subscription.id)


def _as_utc(value: datetime) -> datetime:
    # SQLite hands back naive datetimes even from DateTime(timezone=True).
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class DeliveryDispatcher:
    """Fans alerts out to every channel their level declares, records an
    alert_deliveries row per attempt, and returns the results.

    Failure isolation is the contract: one channel raising, timing out or
    returning FAILED never stops the others and never fails the alert run.
    """

    def __init__(
        self,
        channels: dict[str, AlertChannel] | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self._channels = channels if channels is not None else default_channels()
        # Injectable so tests can measure latency against a pinned clock.
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def channels(self) -> dict[str, AlertChannel]:
        return self._channels

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
        deliveries_total.labels(channel=result.channel, status=result.status).inc()
        if result.status == STATUS_SENT and result.channel != CHANNEL_IN_APP and result.latency_ms is not None:
            delivery_latency_seconds.labels(channel=result.channel).observe(result.latency_ms / 1000)
        return delivery

    def _attempt(
        self,
        channel: AlertChannel,
        alert: Alert,
        subscription: AlertSubscription | None,
        reminder: bool = False,
    ) -> DeliveryResult:
        try:
            if reminder:
                return channel.send(alert, subscription, reminder=True)
            return channel.send(alert, subscription)
        except Exception as exc:  # channel bugs must not break the run
            logger.exception("Channel %s raised while delivering alert %s", channel.name, alert.id)
            return DeliveryResult(channel=channel.name, status=STATUS_FAILED, error=str(exc)[:500])

    def dispatch(self, db, alert: Alert, subscriptions: list[AlertSubscription]) -> list[DeliveryResult]:
        """Deliver ONE `alert` with no send budget and no re-send pass — the
        Phase 2 entry point, kept for any caller that delivers a single
        alert. The engine uses dispatch_run()."""
        return self.dispatch_run(db, [alert], subscriptions)

    def dispatch_run(
        self,
        db,
        alerts: list[Alert],
        subscriptions: list[AlertSubscription],
        now: datetime | None = None,
        budget: SendBudget | None = None,
        include_resends: bool = False,
    ) -> list[DeliveryResult]:
        """Deliver every alert raised by one run, plus (with
        `include_resends`) the level 4/5 re-sends and deferred retries that
        are due at `now`.

        In-app is delivered once per alert with no subscription and costs
        no budget. Every other channel the level declares is delivered once
        per MATCHING verified subscription — an unverified subscriber is
        recorded as skipped and never messaged."""
        now = now or self._clock()
        budget = budget or SendBudget(None)
        results: list[DeliveryResult] = []
        jobs: list[_SendJob] = []

        for alert in alerts:
            if CHANNEL_IN_APP in channels_for(alert.level):
                result = self._attempt(self._channels[CHANNEL_IN_APP], alert, None)
                self._record(db, alert, result, None)
                results.append(result)

            for subscription in subscriptions:
                if subscription.channel == CHANNEL_IN_APP or alert.level < MIN_PUSH_LEVEL:
                    continue
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
                    self._record(db, alert, result, subscription)
                    results.append(result)
                    continue
                jobs.append(_SendJob(alert, subscription, channel))

        if include_resends:
            jobs.extend(self._due_resends(db, subscriptions, now, exclude={alert.id for alert in alerts}))

        consecutive_failures: dict[str, int] = {}
        for job in sorted(jobs, key=lambda item: item.priority):
            channel = job.channel
            if not channel.enabled:
                # The channel's own honest "not configured" skip; no budget
                # is spent on a send that cannot happen.
                result = self._attempt(channel, job.alert, job.subscription)
            elif consecutive_failures.get(channel.name, 0) >= CONSECUTIVE_FAILURES_TO_PAUSE:
                result = DeliveryResult(channel=channel.name, status=STATUS_SKIPPED, attempts=0, error=PAUSED_DEFERRED)
            elif not budget.take():
                result = DeliveryResult(channel=channel.name, status=STATUS_SKIPPED, attempts=0, error=BUDGET_DEFERRED)
            else:
                result = self._attempt(channel, job.alert, job.subscription, reminder=job.reminder)
                if result.status == STATUS_FAILED:
                    consecutive_failures[channel.name] = consecutive_failures.get(channel.name, 0) + 1
                else:
                    consecutive_failures[channel.name] = 0
                if result.status == STATUS_SENT:
                    # Latency = raised -> provider accepted. A reminder is
                    # measured from the run that re-sent it instead, or the
                    # histogram would fill with 6 h, 12 h, 18 h...
                    accepted_at = self._clock()
                    reference = now if job.reminder else job.alert.created_at
                    result.latency_ms = max(0, int((accepted_at - _as_utc(reference)).total_seconds() * 1000))
                    # One time source for the whole run, so the 6 h re-send
                    # arithmetic never mixes two clocks.
                    result.sent_at = accepted_at
            self._record(db, job.alert, result, job.subscription)
            results.append(result)

        return results

    def _due_resends(
        self, db, subscriptions: list[AlertSubscription], now: datetime, exclude: set[int]
    ) -> list[_SendJob]:
        """Sends owed from earlier runs, decided from the alert_deliveries
        history alone (so a restarted process picks up exactly where it
        left off):

          * a delivery a previous run DEFERRED (budget or paused channel),
            at any pushed level, that has not been attempted since;
          * a level 4/5 alert still open, to each matching subscriber who
            has not acknowledged it, once RESEND_INTERVAL has passed since
            the last successful send — and never more often than one send
            per interval since the alert was raised, even if every earlier
            attempt failed. A subscriber who joins while an emergency is
            open gets it on the next run.

        Only enabled channels: a switched-off channel is not "owed" a send
        every run."""
        open_alerts = (
            db.query(Alert)
            .filter(Alert.status.in_(_OPEN_STATUSES), Alert.level >= MIN_PUSH_LEVEL)
            .order_by(Alert.id)
            .all()
        )
        open_alerts = [alert for alert in open_alerts if alert.id not in exclude]
        if not open_alerts:
            return []

        history: dict[tuple[int, int], list[AlertDelivery]] = {}
        rows = (
            db.query(AlertDelivery)
            .filter(
                AlertDelivery.alert_id.in_([alert.id for alert in open_alerts]),
                AlertDelivery.subscription_id.isnot(None),
            )
            .order_by(AlertDelivery.id)
            .all()
        )
        for row in rows:
            history.setdefault((row.alert_id, row.subscription_id), []).append(row)

        jobs: list[_SendJob] = []
        for alert in open_alerts:
            for subscription in subscriptions:
                if not subscription.verified or not subscription_matches(subscription, alert):
                    continue
                channel = self._channels.get(subscription.channel)
                if channel is None or not channel.enabled or subscription.channel == CHANNEL_IN_APP:
                    continue
                rows_for_pair = history.get((alert.id, subscription.id), [])
                if self._resend_due(alert, subscription, rows_for_pair, now):
                    reminder = any(row.status in (STATUS_SENT, STATUS_FAILED) for row in rows_for_pair)
                    jobs.append(_SendJob(alert, subscription, channel, reminder=reminder, carried_over=True))
        return jobs

    def _resend_due(
        self, alert: Alert, subscription: AlertSubscription, rows: list[AlertDelivery], now: datetime
    ) -> bool:
        attempted = [row for row in rows if row.status in (STATUS_SENT, STATUS_FAILED)]
        last = rows[-1] if rows else None
        deferred_since_last_attempt = (
            last is not None
            and last.status == STATUS_SKIPPED
            and (last.error or "").startswith(DEFERRED_PREFIX)
        )
        if deferred_since_last_attempt:
            return True
        if alert.level < RESEND_MIN_LEVEL or acknowledged_by(alert, subscription):
            return False
        if not attempted:
            return True
        # One send per interval since the alert was raised, at most...
        if now - _as_utc(alert.created_at) < RESEND_INTERVAL * len(attempted):
            return False
        # ...and never within an interval of the last one that got through.
        sent_times = [_as_utc(row.sent_at) for row in attempted if row.status == STATUS_SENT and row.sent_at]
        return not sent_times or now - max(sent_times) >= RESEND_INTERVAL
