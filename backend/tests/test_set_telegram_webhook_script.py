"""LEHAR Phase 3: scripts/set_telegram_webhook.py registers the right URL with
the right secret — checked against a mocked Bot API, never the real one."""

import importlib.util
import sys
from pathlib import Path

import pytest

import app.config as config_module
from app.services.alerts.channels.telegram import TelegramChannel
from tests._channel_fakes import FakeProvider, SleepRecorder, telegram_ok

SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "set_telegram_webhook.py"


@pytest.fixture
def script(monkeypatch):
    spec = importlib.util.spec_from_file_location("set_telegram_webhook", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    config_module.get_settings.cache_clear()


def configure(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    config_module.get_settings.cache_clear()


def run(script, monkeypatch, provider, *argv):
    monkeypatch.setattr(
        script, "TelegramChannel", lambda: TelegramChannel(token="1:t", client=provider.client(), sleep=SleepRecorder())
    )
    monkeypatch.setattr(sys, "argv", ["set_telegram_webhook.py", *argv])
    return script.main()


def test_registers_the_webhook_with_its_secret_and_the_command_menu(script, monkeypatch):
    configure(monkeypatch, TELEGRAM_WEBHOOK_SECRET="s3cret", PUBLIC_BASE_URL="https://lehar-api.example/")
    provider = FakeProvider(telegram_ok())

    assert run(script, monkeypatch, provider) == 0

    methods = [request.url.path.rsplit("/", 1)[-1] for request in provider.requests]
    assert methods == ["setWebhook", "setMyCommands"]
    webhook = provider.bodies()[0]
    assert webhook["url"] == "https://lehar-api.example/api/v1/alerts/telegram/webhook"
    assert webhook["secret_token"] == "s3cret"
    assert webhook["allowed_updates"] == ["message", "callback_query"]
    assert {c["command"] for c in provider.bodies()[1]["commands"]} == {"start", "stop", "level", "lang", "status"}


def test_refuses_a_non_https_url(script, monkeypatch):
    configure(monkeypatch, TELEGRAM_WEBHOOK_SECRET="s3cret", PUBLIC_BASE_URL="http://localhost:8000")
    provider = FakeProvider(telegram_ok())

    assert run(script, monkeypatch, provider) == 1
    assert provider.requests == []


def test_refuses_to_register_without_a_secret(script, monkeypatch):
    configure(monkeypatch, TELEGRAM_WEBHOOK_SECRET="", PUBLIC_BASE_URL="https://lehar-api.example")
    provider = FakeProvider(telegram_ok())

    assert run(script, monkeypatch, provider) == 1
    assert provider.requests == []
