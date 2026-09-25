"""LEHAR Phase 3: the delivery pipeline — fan-out matching, the per-run send
budget, level 4/5 re-sends, failure isolation, latency and the Prometheus
delivery metrics.

Driven through the real AlertEngine with the same offline fakes as
test_alerts_engine.py. The channels are either recording fakes, or the REAL
Telegram/email channels over an httpx.MockTransport — never the network.
The clock is pinned per run, and the dispatcher reads the same pinned clock,
so the 6-hour re-send arithmetic is exact.
"""

from datetime import timedelta

import pytest
from prometheus_client import REGISTRY

import app.config as config_module
from app.db import Alert, AlertDelivery, AlertSubscription, get_session_factory
from app.services.alerts import engine as engine_module
from app.services.alerts.channels import (
    BUDGET_DEFERRED,
    PAUSED_DEFERRED,
    AlertChannel,
    DeliveryDispatcher,
    DeliveryResult,
    InAppChannel,
)
from app.services.alerts.channels.email import EmailChannel
from app.services.alerts.channels.telegram import TelegramChannel
from app.services.alerts.engine import AlertEngine
from app.services.alerts.levels import DISCLAIMER_EN, DISCLAIMER_UR
from app.services.alerts.rules import TYPE_FLOOD, TYPE_IRRIGATION_DUE
from tests._channel_fakes import FakeProvider, SleepRecorder, brevo_ok, telegram_ok
from tests.test_alerts_engine import (
    T0,
    TEST_DISTRICTS,
    FakeFloodService,
    FakeModelService,
    FakeWeatherService,
    flood_entry,
)

LEVEL_3 = flood_entry("HIGH", 70.0)
LEVEL_5 = flood_entry("HIGH", 90.0)  # extreme sub-band -> level 5


@pytest.fixture(autouse=True)
def _small_district_set(monkeypatch):
    from ml.districts import DISTRICTS as REAL_DISTRICTS

    monkeypatch.setattr(engine_module, "DISTRICTS", {name: REAL_DISTRICTS[name] for name in TEST_DISTRICTS})


@pytest.fixture(autouse=True)
def _isolated_ops_events(tmp_path, monkeypatch):
    monkeypatch.setenv("ALERT_OPS_EVENTS_PATH", str(tmp_path / "ops_events.jsonl"))
    config_module.get_settings.cache_clear()
    yield
    config_module.get_settings.cache_clear()


@pytest.fixture
def db():
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


class Clock:
    """One pinned "now", shared by the engine run and the dispatcher."""

    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class RecordingChannel(AlertChannel):
    """Records every send; answers sent, failed, or raises."""

    def __init__(self, name, mode="ok", enabled=True):
        self.name = name
        self.mode = mode
        self.enabled = enabled
        self.sent: list[tuple[int, int, bool]] = []

    def send(self, alert, subscription, reminder=False):
        self.sent.append((alert.id, subscription.id, reminder))
        if self.mode == "raise":
            raise RuntimeError("transport bug")
        if self.mode == "fail":
            return DeliveryResult(channel=self.name, status="failed", attempts=4, error="HTTP 502: bad gateway")
        return DeliveryResult(channel=self.name, status="sent", attempts=1)


def build(clock, telegram=None, email=None, flood=None, model=None):
    channels = {
        "in_app": InAppChannel(),
        "telegram": telegram or RecordingChannel("telegram"),
        "email": email or RecordingChannel("email"),
    }
    engine = AlertEngine(
        flood_service=flood or FakeFloodService({"Multan": LEVEL_3}),
        weather_service=FakeWeatherService(),
        model_service=model,
        dispatcher=DeliveryDispatcher(channels=channels, clock=clock),
    )
    return engine, channels


def subscribe(db, channel, target, districts=("Multan",), min_level=2, language="en", verified=True):
    row = AlertSubscription(
        channel=channel,
        target=target,
        districts=list(districts),
        min_level=min_level,
        language=language,
        verified=verified,
    )
    db.add(row)
    db.commit()
    return row


def external_deliveries(db):
    db.expire_all()
    return (
        db.query(AlertDelivery)
        .filter(AlertDelivery.channel != "in_app")
        .order_by(AlertDelivery.id)
        .all()
    )


# --- fan-out matching --------------------------------------------------------------

def test_fan_out_reaches_exactly_the_matching_subscribers(db):
    wanted_tg = subscribe(db, "telegram", "100")
    wanted_email = subscribe(db, "email", "ur@example.com", language="ur")
    everywhere = subscribe(db, "email", "all@example.com", districts=())  # empty = every district
    subscribe(db, "telegram", "200", districts=("Sukkur",))  # other district
    subscribe(db, "email", "high@example.com", min_level=4)  # level too low for them
    unverified = subscribe(db, "telegram", "300", verified=False)
    clock = Clock(T0)
    engine, channels = build(clock)

    engine.run(db, now=T0)

    assert [sub for _, sub, _ in channels["telegram"].sent] == [wanted_tg.id]
    assert sorted(sub for _, sub, _ in channels["email"].sent) == sorted([wanted_email.id, everywhere.id])
    rows = {row.subscription_id: row for row in external_deliveries(db)}
    assert set(rows) == {wanted_tg.id, wanted_email.id, everywhere.id, unverified.id}
    assert rows[unverified.id].status == "skipped"
    assert all(rows[sub].status == "sent" for sub in (wanted_tg.id, wanted_email.id, everywhere.id))


def test_each_subscriber_gets_the_alert_in_their_own_language(db):
    """End to end with the REAL channels: one Urdu Telegram chat, one English
    inbox, one level-3 alert."""
    subscribe(db, "telegram", "100", language="ur")
    subscribe(db, "email", "en@example.com", language="en")
    telegram_api, brevo_api = FakeProvider(telegram_ok()), FakeProvider(brevo_ok())
    clock = Clock(T0)
    engine, _ = build(
        clock,
        telegram=TelegramChannel(token="1:t", client=telegram_api.client(), sleep=SleepRecorder()),
        email=EmailChannel(
            api_key="k", from_email="a@lehar.example", public_base_url="https://lehar.example",
            client=brevo_api.client(), sleep=SleepRecorder(),
        ),
    )

    engine.run(db, now=T0)

    alert = db.query(Alert).filter(Alert.type == TYPE_FLOOD).one()
    [telegram_text] = telegram_api.texts()
    assert telegram_text.startswith(f"<b>{alert.title_ur}</b>")
    assert DISCLAIMER_UR in telegram_text and DISCLAIMER_EN in telegram_text
    [email_body] = brevo_api.bodies()
    assert email_body["subject"] == f"[LEHAR level 3] {alert.title_en}"
    assert [row.status for row in external_deliveries(db)] == ["sent", "sent"]


def test_level_1_is_never_emailed_or_telegrammed_even_with_live_channels(db):
    from tests.test_alerts_engine import _save_fields

    _save_fields(db, "farmer_p3", ("North", "Multan"))
    subscribe(db, "telegram", "100", districts=(), min_level=1)
    subscribe(db, "email", "a@example.com", districts=(), min_level=1)
    clock = Clock(T0)
    engine, channels = build(clock, flood=FakeFloodService(), model=FakeModelService(12.0))

    engine.run(db, now=T0)

    assert db.query(Alert).filter(Alert.type == TYPE_IRRIGATION_DUE).count() == 1
    assert channels["telegram"].sent == [] and channels["email"].sent == []
    assert external_deliveries(db) == []


def test_latency_is_measured_from_the_alert_being_raised_to_the_provider_accepting(db):
    subscribe(db, "telegram", "100")
    clock = Clock(T0 + timedelta(seconds=2.5))  # provider answers 2.5 s after the alert was raised
    engine, _ = build(clock)

    engine.run(db, now=T0)

    [row] = external_deliveries(db)
    assert row.latency_ms == 2500
    assert row.attempts == 1
    assert row.error is None


# --- failure isolation --------------------------------------------------------------

def test_a_failing_channel_never_blocks_the_other_channel_or_the_alert(db):
    subscribe(db, "telegram", "100")
    subscribe(db, "email", "a@example.com")
    engine, channels = build(Clock(T0), telegram=RecordingChannel("telegram", mode="raise"))

    result = engine.run(db, now=T0)

    assert result.alerts_raised == 1
    by_channel = {row.channel: row for row in external_deliveries(db)}
    assert by_channel["telegram"].status == "failed"
    assert "transport bug" in by_channel["telegram"].error
    assert by_channel["email"].status == "sent"


def test_a_channel_that_keeps_failing_is_paused_for_the_rest_of_the_run(db):
    for chat in range(5):
        subscribe(db, "telegram", str(chat))
    subscribe(db, "email", "a@example.com")
    telegram = RecordingChannel("telegram", mode="fail")
    engine, channels = build(Clock(T0), telegram=telegram)

    engine.run(db, now=T0)

    assert len(telegram.sent) == 3  # three real failures, then it stops trying
    statuses = [(row.channel, row.status, row.error) for row in external_deliveries(db)]
    assert [s for c, s, _ in statuses if c == "telegram"].count("failed") == 3
    assert [e for c, _, e in statuses if c == "telegram"].count(PAUSED_DEFERRED) == 2
    assert ("email", "sent", None) in statuses


# --- the per-run send budget -------------------------------------------------------------

def set_budget(monkeypatch, limit):
    monkeypatch.setenv("ALERT_MAX_SENDS_PER_RUN", str(limit))
    config_module.get_settings.cache_clear()


def test_the_budget_caps_external_sends_and_spends_it_on_the_highest_level_first(db, monkeypatch):
    set_budget(monkeypatch, 2)
    for chat in range(3):
        subscribe(db, "telegram", str(chat), districts=())  # every district
    flood = FakeFloodService({"Multan": LEVEL_3, "Sukkur": LEVEL_5})
    engine, channels = build(Clock(T0), flood=flood)

    engine.run(db, now=T0)

    level_of = {alert.id: alert.level for alert in db.query(Alert).all()}
    assert len(channels["telegram"].sent) == 2
    assert all(level_of[alert_id] == 5 for alert_id, _, _ in channels["telegram"].sent)
    rows = external_deliveries(db)
    assert sum(row.status == "sent" for row in rows) == 2
    deferred = [row for row in rows if row.error == BUDGET_DEFERRED]
    assert len(deferred) == 4
    assert all(row.status == "skipped" and row.attempts == 0 for row in deferred)


def test_deferred_sends_are_delivered_by_the_next_run(db, monkeypatch):
    set_budget(monkeypatch, 1)
    first, second = subscribe(db, "telegram", "1"), subscribe(db, "telegram", "2")
    clock = Clock(T0)
    engine, channels = build(clock)

    engine.run(db, now=T0)
    assert [sub for _, sub, _ in channels["telegram"].sent] == [first.id]

    clock.now = T0 + timedelta(hours=1)
    engine.run(db, now=clock.now)

    # Same condition an hour later: no new alert, but the owed send goes out
    # — as a first message, not a "reminder" (they never got the first one).
    assert db.query(Alert).filter(Alert.type == TYPE_FLOOD).count() == 1
    assert channels["telegram"].sent[1:] == [(channels["telegram"].sent[0][0], second.id, False)]

    clock.now = T0 + timedelta(hours=2)
    engine.run(db, now=clock.now)
    assert len(channels["telegram"].sent) == 2  # level 3: nothing more is owed


def test_a_disabled_channel_spends_no_budget(db, monkeypatch):
    set_budget(monkeypatch, 1)
    subscribe(db, "email", "a@example.com")
    subscribe(db, "telegram", "1")
    engine, channels = build(Clock(T0), email=EmailChannel(api_key="", from_email="", public_base_url=""))

    engine.run(db, now=T0)

    by_channel = {row.channel: row for row in external_deliveries(db)}
    assert by_channel["email"].status == "skipped"
    assert "BREVO_API_KEY" in by_channel["email"].error
    assert by_channel["telegram"].status == "sent"


# --- level 4/5 re-sends --------------------------------------------------------------------

def test_level_5_is_resent_every_6_hours_while_it_stays_open(db):
    sub = subscribe(db, "telegram", "100")
    clock = Clock(T0)
    engine, channels = build(clock, flood=FakeFloodService({"Multan": LEVEL_5}))
    telegram = channels["telegram"]

    engine.run(db, now=T0)
    assert len(telegram.sent) == 1
    alert_id = telegram.sent[0][0]

    for hours in (1, 3, 5):
        clock.now = T0 + timedelta(hours=hours)
        engine.run(db, now=clock.now)
    assert len(telegram.sent) == 1  # nothing inside the 6 h window

    clock.now = T0 + timedelta(hours=6)
    engine.run(db, now=clock.now)
    assert telegram.sent[-1] == (alert_id, sub.id, True)  # a labelled reminder

    clock.now = T0 + timedelta(hours=7)
    engine.run(db, now=clock.now)
    assert len(telegram.sent) == 2


def test_a_level_3_alert_is_never_resent(db):
    subscribe(db, "telegram", "100")
    clock = Clock(T0)
    engine, channels = build(clock)

    engine.run(db, now=T0)
    clock.now = T0 + timedelta(hours=7)
    engine.run(db, now=clock.now)

    assert len(channels["telegram"].sent) == 1


def test_acknowledging_stops_reminders_for_that_subscriber_only(db):
    acked = subscribe(db, "telegram", "100")
    other = subscribe(db, "telegram", "200")
    clock = Clock(T0)
    engine, channels = build(clock, flood=FakeFloodService({"Multan": LEVEL_5}))

    engine.run(db, now=T0)
    alert = db.query(Alert).filter(Alert.type == TYPE_FLOOD).one()
    alert.status = "acknowledged"
    alert.payload = {**alert.payload, "acknowledged_by": ["telegram:100"]}
    db.commit()

    clock.now = T0 + timedelta(hours=6)
    engine.run(db, now=clock.now)

    reminders = [(sub, reminder) for _, sub, reminder in channels["telegram"].sent[2:]]
    assert reminders == [(other.id, True)]
    assert acked.id not in [sub for sub, _ in reminders]


def test_a_subscriber_who_joins_during_an_emergency_gets_it_on_the_next_run(db):
    clock = Clock(T0)
    engine, channels = build(clock, flood=FakeFloodService({"Multan": LEVEL_5}))
    engine.run(db, now=T0)

    late = subscribe(db, "telegram", "900")
    clock.now = T0 + timedelta(hours=1)
    engine.run(db, now=clock.now)

    assert [(sub, reminder) for _, sub, reminder in channels["telegram"].sent] == [(late.id, False)]


def test_resolved_alerts_are_never_resent(db):
    subscribe(db, "telegram", "100")
    clock = Clock(T0)
    engine, channels = build(clock, flood=FakeFloodService({"Multan": LEVEL_5}))
    engine.run(db, now=T0)

    alert = db.query(Alert).filter(Alert.type == TYPE_FLOOD).one()
    alert.status = "resolved"
    db.commit()
    clock.now = T0 + timedelta(hours=7)
    engine.run(db, now=clock.now)

    assert len(channels["telegram"].sent) == 1


def test_a_disabled_channel_is_not_owed_reminders(db):
    subscribe(db, "telegram", "100")
    clock = Clock(T0)
    telegram = RecordingChannel("telegram", enabled=False)
    engine, _ = build(clock, telegram=telegram, flood=FakeFloodService({"Multan": LEVEL_5}))

    engine.run(db, now=T0)
    count_after_first_run = len(external_deliveries(db))
    clock.now = T0 + timedelta(hours=7)
    engine.run(db, now=clock.now)

    assert len(external_deliveries(db)) == count_after_first_run


# --- Prometheus ----------------------------------------------------------------------------

def sample(name, **labels):
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_deliveries_and_latency_are_exported_to_prometheus(db, client):
    subscribe(db, "telegram", "100")
    subscribe(db, "email", "a@example.com")
    subscribe(db, "email", "b@example.com", verified=False)
    before = {
        "tg_sent": sample("lehar_deliveries_total", channel="telegram", status="sent"),
        "email_sent": sample("lehar_deliveries_total", channel="email", status="sent"),
        "email_skipped": sample("lehar_deliveries_total", channel="email", status="skipped"),
        "in_app": sample("lehar_deliveries_total", channel="in_app", status="sent"),
        "latency_count": sample("lehar_delivery_latency_seconds_count", channel="telegram"),
        "latency_sum": sample("lehar_delivery_latency_seconds_sum", channel="telegram"),
    }
    engine, _ = build(Clock(T0 + timedelta(seconds=4)))

    engine.run(db, now=T0)

    assert sample("lehar_deliveries_total", channel="telegram", status="sent") == before["tg_sent"] + 1
    assert sample("lehar_deliveries_total", channel="email", status="sent") == before["email_sent"] + 1
    assert sample("lehar_deliveries_total", channel="email", status="skipped") == before["email_skipped"] + 1
    assert sample("lehar_deliveries_total", channel="in_app", status="sent") == before["in_app"] + 1
    assert sample("lehar_delivery_latency_seconds_count", channel="telegram") == before["latency_count"] + 1
    assert sample("lehar_delivery_latency_seconds_sum", channel="telegram") == pytest.approx(before["latency_sum"] + 4.0)

    exposition = client.get("/metrics").text
    assert "lehar_deliveries_total" in exposition
    assert "lehar_delivery_latency_seconds_bucket" in exposition
