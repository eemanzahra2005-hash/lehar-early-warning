"""GET /api/v1/assistant/status and POST /api/v1/assistant/chat — the LEHAR
Assistant: a hybrid cloud+local LLM (Phase 6.6 — cloud first with automatic
fallback to local Ollama, see app/services/llm.py) grounded ONLY in real app
data injected as CONTEXT JSON (see app/services/assistant.py). Never
fabricates numbers; degrades to a clean 503 when no provider is reachable —
the rest of the app is completely unaffected."""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth import get_current_user_optional
from app.db import User, get_db
from app.dependencies import get_assistant_service, get_llm_service
from app.metrics import assistant_requests_total
from app.rate_limit import assistant_rate_limit, limiter
from app.schemas import AssistantChatRequest, AssistantChatResponse, AssistantStatusResponse, ProviderStatus
from app.services.assistant import SYSTEM_PROMPT, AssistantService
from app.services.llm import LLMService, LLMUnavailableError

logger = logging.getLogger("app.assistant_router")

router = APIRouter(prefix="/assistant", tags=["assistant"])

# Only the most recent turns are sent, both to keep CPU inference latency
# reasonable and because the system prompt already tells the model to answer
# only from CONTEXT, not from a long chat history.
MAX_HISTORY_TURNS = 6


@router.get("/status", response_model=AssistantStatusResponse)
def get_assistant_status(llm_service: LLMService = Depends(get_llm_service)) -> AssistantStatusResponse:
    return AssistantStatusResponse(
        mode=llm_service.provider,
        available=llm_service.is_available(),
        cloud=ProviderStatus(available=llm_service.cloud_available(), model=llm_service.cloud_model),
        local=ProviderStatus(available=llm_service.ollama_available(), model=llm_service.model),
    )


@router.post("/chat", response_model=AssistantChatResponse)
@limiter.limit(assistant_rate_limit)
def chat(
    request: Request,
    payload: AssistantChatRequest,
    current_user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
    llm_service: LLMService = Depends(get_llm_service),
    assistant_service: AssistantService = Depends(get_assistant_service),
) -> AssistantChatResponse:
    district = assistant_service.resolve_district(payload.message, payload.district)
    context = assistant_service.build_context(
        district=district, message=payload.message, user=current_user, db=db
    )
    if payload.prediction_context is not None:
        context["this_prediction"] = payload.prediction_context

    messages = [{"role": "system", "content": f"{SYSTEM_PROMPT}\n\nCONTEXT:\n{json.dumps(context)}"}]
    for turn in (payload.history or [])[-MAX_HISTORY_TURNS:]:
        messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": payload.message})

    try:
        result = llm_service.chat(messages, provider_override=payload.provider)
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    assistant_requests_total.labels(provider=result.provider_used).inc()

    return AssistantChatResponse(
        reply=result.reply, provider_used=result.provider_used, model=result.model, context_used=context
    )
