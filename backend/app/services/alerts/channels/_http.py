"""One HTTPS POST with timeouts and bounded retries, shared by the Telegram
and Brevo transports (LEHAR Phase 3).

Retry policy — the same for both providers, so a reader learns it once:

  * a network error or timeout, HTTP 429 or a 5xx is RETRIED, up to
    MAX_RETRIES times after the first attempt, with a doubling backoff
    (1 s, 2 s, 4 s). A 429 that names its own wait (Telegram's
    `parameters.retry_after`, or a `Retry-After` header) waits that long
    instead, as long as it is no more than MAX_RETRY_AFTER_SECONDS — a
    provider asking us to back off for minutes is answered with a failure,
    not a stalled alert run;
  * any other 4xx (bad token, chat not found, bot blocked, invalid sender)
    is NOT retried: asking again cannot change the answer.

It never raises. The caller gets a PostOutcome and decides what that means
for its delivery row.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

MAX_RETRIES = 3
BACKOFF_SECONDS = (1.0, 2.0, 4.0)
MAX_RETRY_AFTER_SECONDS = 10.0
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

# 5 s to connect, 10 s for everything else: long enough for a slow free-tier
# provider, short enough that one dead provider cannot hold an alert run for
# minutes (the dispatcher also pauses a channel after repeated failures).
DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

MAX_ERROR_CHARS = 300


@dataclass
class PostOutcome:
    ok: bool
    attempts: int
    status_code: int | None = None
    body: dict | None = None
    error: str | None = None


def _json_or_none(response: httpx.Response) -> dict | None:
    try:
        parsed = response.json()
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _retry_after_seconds(response: httpx.Response, body: dict | None) -> float | None:
    """The wait a 429 asked for, from Telegram's body or a standard header."""
    if body is not None:
        parameters = body.get("parameters") or {}
        if isinstance(parameters, dict) and parameters.get("retry_after") is not None:
            try:
                return float(parameters["retry_after"])
            except (TypeError, ValueError):
                pass
    header = response.headers.get("Retry-After")
    if header is not None:
        try:
            return float(header)
        except ValueError:
            return None
    return None


def _describe(response: httpx.Response, body: dict | None) -> str:
    """A short, human-readable error from a provider response. Telegram puts
    it in `description`, Brevo in `message`."""
    detail = None
    if body is not None:
        detail = body.get("description") or body.get("message") or body.get("code")
    if detail is None:
        detail = response.text
    return f"HTTP {response.status_code}: {detail}"[:MAX_ERROR_CHARS]


def post_json(
    url: str,
    payload: dict,
    headers: dict | None = None,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    redact: str | None = None,
) -> PostOutcome:
    """POST `payload` as JSON to `url`, retrying per the module policy.

    `client` is injectable so the tests can drive a real httpx.Client over
    an httpx.MockTransport — no network. `redact` is a secret that must
    never appear in an error string (the Telegram bot token lives in the URL
    path, and some httpx exceptions quote the URL)."""

    def clean(text: str) -> str:
        if redact:
            text = text.replace(redact, "<redacted>")
        return text[:MAX_ERROR_CHARS]

    def attempt_all(http: httpx.Client) -> PostOutcome:
        attempts = 0
        last_error = "no attempt made"
        last_status: int | None = None
        last_body: dict | None = None
        while True:
            attempts += 1
            wait: float | None = None
            try:
                response = http.post(url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                last_error = clean(f"{type(exc).__name__}: {exc}")
                last_status, last_body = None, None
            else:
                body = _json_or_none(response)
                if 200 <= response.status_code < 300:
                    return PostOutcome(ok=True, attempts=attempts, status_code=response.status_code, body=body)
                last_error = clean(_describe(response, body))
                last_status, last_body = response.status_code, body
                if response.status_code not in RETRYABLE_STATUS:
                    break
                if response.status_code == 429:
                    wait = _retry_after_seconds(response, body)
                    if wait is not None and wait > MAX_RETRY_AFTER_SECONDS:
                        last_error = clean(f"{last_error} (provider asked to wait {wait:g} s; not retried)")
                        break
            if attempts > MAX_RETRIES:
                break
            sleep(wait if wait is not None else BACKOFF_SECONDS[min(attempts - 1, len(BACKOFF_SECONDS) - 1)])
        return PostOutcome(ok=False, attempts=attempts, status_code=last_status, body=last_body, error=last_error)

    if client is not None:
        return attempt_all(client)
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as http:
        return attempt_all(http)
