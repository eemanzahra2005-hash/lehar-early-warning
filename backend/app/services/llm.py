"""LLM assistant client — hybrid cloud + local (Phase 6.6, extends the
Phase 6.5 local-only client). Three real providers behind one interface, plus
"none" to disable the assistant entirely:

  - "ollama": local Ollama server (unchanged transport from Phase 6.5).
  - "cloud": any OpenAI-compatible chat-completions endpoint (Groq by
    default) — needs LLM_CLOUD_API_KEY, never falls back.
  - "hybrid" (default): tries cloud first when a key is configured, and on
    ANY cloud error/timeout/rate-limit automatically falls back to local
    Ollama so the user still gets a reply; behaves exactly like "ollama"
    when no cloud key is set.

HARD RULE (CLAUDE.md rule 4 / Phase 6.5 brief, unchanged in 6.6): this module
NEVER invents data — it's a plain transport layer for whatever CONTEXT JSON
app/services/assistant.py assembled. Any failure to reach/parse a provider
raises LLMUnavailableError, which the assistant router turns into a clean
503. The cloud API key is read once from Settings, used only in an outgoing
Authorization header, and is NEVER logged or included in any return value.

Phase 15: the default cloud model migrated to openai/gpt-oss-120b (Groq
retired llama-3.3-70b-versatile on 2026-08-16) — a reasoning model, so
_chat_cloud() sends reasoning_effort=low and strips any leading
<think>...</think> block before returning the reply. A cloud response
naming a retired/unknown model (model_decommissioned/model_not_found) logs
one warning and falls through the existing error handling into hybrid's
local fallback, same as any other cloud failure. When NEITHER provider can
answer, ASSISTANT_NOT_CONFIGURED_MESSAGE tells the user how to fix it
(add a Groq key or install Ollama) instead of a technical connection error.
"""

import logging
import re
from dataclasses import dataclass

import requests

from app.config import get_settings

logger = logging.getLogger("app.llm")

# Short timeout for status pings (Ollama's /api/tags, the cloud provider's
# /models) — these are liveness checks, not inference calls, so they should
# never make a user wait long to find out a provider is offline.
STATUS_TIMEOUT_SECONDS = 5.0

# Same sampling temperature for both providers (Phase 6.6 brief) — low
# enough to keep replies grounded/consistent rather than creative, since the
# system prompt already restricts the model to CONTEXT-only facts.
TEMPERATURE = 0.3

VALID_CHAT_OVERRIDES = {"hybrid", "local", "cloud"}

# Groq's recommended replacement for llama-3.3-70b-versatile (retired
# 2026-08-16, see https://console.groq.com/docs/deprecations) is a reasoning
# model family: openai/gpt-oss-120b and openai/gpt-oss-20b. Both need an
# explicit reasoning_effort (Groq/OpenAI default to "medium", which is
# slower and more verbose than this assistant's brief-farmer-friendly-reply
# brief needs) and both narrate their reasoning in a leading <think>...</think>
# block that must be stripped before the reply is shown to a user (Phase 15).
CLOUD_REASONING_MODEL_PREFIX = "openai/gpt-oss"
CLOUD_REASONING_EFFORT = "low"
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)

# Shown to the user (never a stack trace/technical detail) whenever NEITHER
# provider can answer — the most common state for a fresh release-zip
# install (no Groq key pasted in yet, no Ollama installed). Phase 15.
ASSISTANT_NOT_CONFIGURED_MESSAGE = (
    "Assistant is not configured: add a free Groq API key (console.groq.com) "
    "to backend\\.env as LLM_CLOUD_API_KEY, or install Ollama — see RUN-ME-FIRST.txt."
)


class LLMUnavailableError(Exception):
    """Raised when the effective provider can't be reached, times out, is
    rate-limited, or returns something unparseable. Callers turn this into a
    clean 503. In "hybrid" mode this is only raised once BOTH providers have
    failed (or the fallback also failed) — see LLMService.chat()."""


@dataclass
class LLMChatResult:
    """chat()'s return value: the reply text plus which provider actually
    produced it, so the router/UI can show an honest "cloud" vs "local"
    badge instead of assuming whatever was configured."""

    reply: str
    provider_used: str  # "cloud" | "local"
    model: str


class LLMService:
    """Thin HTTP client wrapping Ollama's native chat API and any
    OpenAI-compatible chat-completions endpoint behind one interface."""

    def __init__(
        self,
        provider: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        cloud_base_url: str | None = None,
        cloud_model: str | None = None,
        cloud_api_key: str | None = None,
        cloud_timeout_seconds: float | None = None,
    ):
        settings = get_settings()
        self.provider = provider if provider is not None else settings.llm_provider

        self.base_url = (base_url if base_url is not None else settings.ollama_base_url).rstrip("/")
        self.model = model if model is not None else settings.llm_model
        self.timeout = timeout_seconds if timeout_seconds is not None else settings.llm_timeout_seconds

        self.cloud_base_url = (
            cloud_base_url if cloud_base_url is not None else settings.llm_cloud_base_url
        ).rstrip("/")
        self.cloud_model = cloud_model if cloud_model is not None else settings.llm_cloud_model
        self._cloud_api_key = cloud_api_key if cloud_api_key is not None else settings.llm_cloud_api_key
        self.cloud_timeout = (
            cloud_timeout_seconds if cloud_timeout_seconds is not None else settings.llm_cloud_timeout_seconds
        )

    def has_cloud_key(self) -> bool:
        return bool(self._cloud_api_key)

    def ollama_available(self) -> bool:
        """Pings Ollama's tag-listing endpoint. Never raises — returns False
        for any failure (server down, connection refused, timeout, non-200).
        Checked regardless of `self.provider` so status reporting always
        reflects real local-server reachability, independent of which mode
        is configured."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=STATUS_TIMEOUT_SECONDS)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def cloud_available(self) -> bool:
        """Pings the cloud provider's model-listing endpoint. Never raises,
        never logs the key. Returns False immediately (no network call) if
        no key is configured."""
        if not self.has_cloud_key():
            return False
        try:
            response = requests.get(
                f"{self.cloud_base_url}/models",
                headers={"Authorization": f"Bearer {self._cloud_api_key}"},
                timeout=STATUS_TIMEOUT_SECONDS,
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    def is_available(self) -> bool:
        """Whether the assistant can respond right now, given the
        configured `self.provider` (no client override applied — see
        _resolve_effective_provider for override handling in chat())."""
        if self.provider == "none":
            return False
        if self.provider == "ollama":
            return self.ollama_available()
        if self.provider == "cloud":
            return self.cloud_available()
        if self.provider == "hybrid":
            if self.has_cloud_key():
                return self.cloud_available() or self.ollama_available()
            return self.ollama_available()
        return False

    def _resolve_effective_provider(self, override: str | None) -> str:
        """A client-supplied `provider` preference ("hybrid"/"local"/"cloud")
        is honored only if that provider is actually available right now;
        otherwise it's ignored and the server's configured `self.provider`
        decides, same as if no override were sent. "none" always wins — a
        server explicitly disabled by LLM_PROVIDER=none can't be re-enabled
        by a client override."""
        if self.provider == "none":
            return "none"
        if override in VALID_CHAT_OVERRIDES:
            if override == "hybrid":
                return "hybrid"
            if override == "cloud" and self.cloud_available():
                return "cloud"
            if override == "local" and self.ollama_available():
                return "ollama"
        return self.provider

    def chat(self, messages: list[dict], provider_override: str | None = None) -> LLMChatResult:
        """Sends `messages` ({"role", "content"} dicts) to the effective
        provider and returns its reply. Raises LLMUnavailableError on
        failure — never returns a fabricated reply.

        `provider_override` is the optional client preference from the
        request (see AssistantChatRequest.provider); resolved against real
        availability first (see _resolve_effective_provider)."""
        effective = self._resolve_effective_provider(provider_override)

        if effective == "none":
            raise LLMUnavailableError("The AI assistant is disabled (LLM_PROVIDER=none).")
        if effective == "cloud":
            return self._chat_cloud(messages)
        if effective == "ollama":
            return self._chat_ollama(messages)

        # "hybrid": try cloud first when a key is configured, and on ANY
        # cloud failure fall back to local so the user still gets a reply —
        # the whole point of hybrid mode. No key at all -> local only,
        # identical behavior to plain "ollama".
        if self.has_cloud_key():
            try:
                return self._chat_cloud(messages)
            except LLMUnavailableError:
                logger.warning("Hybrid mode: cloud LLM failed, falling back to local Ollama", exc_info=True)
        return self._chat_ollama(messages)

    def _chat_ollama(self, messages: list[dict]) -> LLMChatResult:
        """Non-streaming call to Ollama's native POST /api/chat."""
        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": TEMPERATURE},
                },
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise LLMUnavailableError(
                "The local AI model timed out — CPU inference can be slow, try again."
            ) from exc
        except requests.RequestException as exc:
            # No Ollama server reachable at all (vs. running-but-slow/broken,
            # handled by the Timeout/non-200/unparseable branches below) —
            # for the release-zip's default hybrid config with no cloud key,
            # this IS "the assistant has no working provider at all."
            raise LLMUnavailableError(ASSISTANT_NOT_CONFIGURED_MESSAGE) from exc

        if response.status_code != 200:
            raise LLMUnavailableError(f"Ollama returned an error (HTTP {response.status_code}).")

        try:
            data = response.json()
            reply = data["message"]["content"].strip()
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMUnavailableError("Unexpected response from Ollama.") from exc

        return LLMChatResult(reply=reply, provider_used="local", model=self.model)

    def _chat_cloud(self, messages: list[dict]) -> LLMChatResult:
        """Non-streaming call to an OpenAI-compatible POST /chat/completions
        endpoint. The API key is used only in this request's Authorization
        header — never logged (exceptions below carry only a generic
        message, never the request/response object), never returned."""
        if not self.has_cloud_key():
            raise LLMUnavailableError("No cloud API key is configured (LLM_CLOUD_API_KEY).")

        payload = {
            "model": self.cloud_model,
            "messages": messages,
            "temperature": TEMPERATURE,
        }
        if self.cloud_model.startswith(CLOUD_REASONING_MODEL_PREFIX):
            # Groq/OpenAI-compatible reasoning models default to "medium"
            # effort, which is slower and more verbose than this assistant's
            # brief, farmer-friendly replies need.
            payload["reasoning_effort"] = CLOUD_REASONING_EFFORT

        try:
            response = requests.post(
                f"{self.cloud_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._cloud_api_key}"},
                json=payload,
                timeout=self.cloud_timeout,
            )
        except requests.Timeout as exc:
            raise LLMUnavailableError("The cloud AI provider timed out.") from exc
        except requests.RequestException as exc:
            raise LLMUnavailableError("Could not reach the cloud AI provider.") from exc

        if response.status_code == 429:
            raise LLMUnavailableError("The cloud AI provider is rate-limited right now.")
        if response.status_code in (400, 404):
            self._warn_if_model_error(response)
        if response.status_code != 200:
            raise LLMUnavailableError(f"Cloud AI provider returned an error (HTTP {response.status_code}).")

        try:
            data = response.json()
            reply = data["choices"][0]["message"]["content"].strip()
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailableError("Unexpected response from the cloud AI provider.") from exc

        reply = _THINK_BLOCK_RE.sub("", reply).strip()

        return LLMChatResult(reply=reply, provider_used="cloud", model=self.cloud_model)

    def _warn_if_model_error(self, response: requests.Response) -> None:
        """Groq (and other OpenAI-compatible providers) return a structured
        error body naming the bad model when it's been retired or mistyped —
        logs ONE clear warning naming the model so an operator can fix
        LLM_CLOUD_MODEL, then returns; the caller's normal HTTP-status
        handling still raises LLMUnavailableError right after this, which
        hybrid mode already turns into an automatic local fallback."""
        try:
            error = (response.json() or {}).get("error") or {}
        except ValueError:
            return
        code = error.get("code")
        if code in ("model_decommissioned", "model_not_found"):
            logger.warning(
                "Cloud LLM model '%s' is unavailable (%s) — update LLM_CLOUD_MODEL in backend/.env.",
                self.cloud_model,
                code,
            )
