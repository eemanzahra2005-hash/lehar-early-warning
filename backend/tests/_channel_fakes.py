"""Shared offline fakes for the LEHAR Phase 3 delivery-channel tests.

Every channel under test talks to a REAL httpx.Client whose transport is an
httpx.MockTransport, so the request each channel builds (URL, headers, JSON
body) is exactly what would go over the wire — only the network is fake.
"""

import json

import httpx


class FakeProvider:
    """Answers each request with the next scripted response (the last one
    repeats), and records every request it saw. A scripted Exception is
    raised instead, the way httpx surfaces a network failure."""

    def __init__(self, *responses):
        self.responses = list(responses) or [httpx.Response(200, json={"ok": True, "result": {}})]
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(response, Exception):
            raise response
        return response

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    def bodies(self) -> list[dict]:
        return [json.loads(request.content) for request in self.requests]

    def texts(self) -> list[str]:
        """The `text` of every Telegram sendMessage call, in order."""
        return [body["text"] for request, body in zip(self.requests, self.bodies()) if request.url.path.endswith("/sendMessage")]


class SleepRecorder:
    """Stands in for time.sleep so retry backoff is asserted, not waited."""

    def __init__(self):
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def telegram_ok() -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})


def brevo_ok() -> httpx.Response:
    # Brevo answers 201 Created with the message id.
    return httpx.Response(201, json={"messageId": "<test@smtp-relay.brevo.com>"})
