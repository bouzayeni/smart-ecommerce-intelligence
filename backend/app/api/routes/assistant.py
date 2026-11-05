"""AI business assistant: natural-language questions answered from read-only analytics tools.

Without an LLM key the assistant runs in tools-only mode: /assistant/tools and
/assistant/tools/{name} still work (the same validated tools, no model), /assistant/query
returns 503 assistant_unavailable.
"""

import logging
from typing import Annotated

import anthropic
from fastapi import APIRouter, Body, Path, Request, Response

from app.api.deps import AppSession, ReadConn, Viewer
from app.assistant import service
from app.assistant.provider import ProviderUnavailableError, get_provider
from app.assistant.tools import TOOLS_BY_NAME
from app.core.config import get_settings
from app.core.errors import ApiError, not_found
from app.core.rate_limit import limiter
from app.schemas.assistant import AssistantAnswer, AssistantQuery

router = APIRouter(prefix="/assistant", tags=["assistant"])
log = logging.getLogger("app.assistant")
ASSISTANT_LIMIT = get_settings().rate_limit_assistant

EXAMPLE_QUESTIONS = [
    "Which product categories generated the most GMV?",
    "Show the revenue trend for the last six months of data.",
    "Which states have the highest late-delivery rate?",
    "How reliable is the churn model?",
    "What GMV do the models forecast for the next 30 days?",
    "Which anomaly days were flagged in November 2017?",
    "Which high-value customers are most at risk of churning?",
]


def _provider_or_none():
    try:
        return get_provider()
    except ProviderUnavailableError:
        return None


@router.get("/status")
def status(_: Viewer):
    s = get_settings()
    enabled = _provider_or_none() is not None
    return {
        "llm_enabled": enabled,
        "provider": s.llm_provider,
        "model": s.anthropic_model if enabled else None,
        "effort": s.assistant_effort,
        "max_iterations": s.assistant_max_iterations,
        "mode": "assistant" if enabled else "tools_only",
        "example_questions": EXAMPLE_QUESTIONS,
    }


@router.get("/tools")
def list_tools(user: Viewer):
    """Tools available to the current role, with their argument schemas."""
    return {
        "items": [
            {
                "name": t.name,
                "description": t.description,
                "min_role": t.min_role,
                "input_schema": t.args_model.model_json_schema(),
            }
            for t in service.allowed_tools(user)
        ]
    }


@router.post("/tools/{name}")
@limiter.limit(ASSISTANT_LIMIT)
def run_tool(
    request: Request,
    response: Response,
    user: Viewer,
    conn: ReadConn,
    session: AppSession,
    name: str = Path(pattern=r"^[a-z_]{1,64}$"),
    args: Annotated[dict | None, Body()] = None,
):
    """Run one tool directly (no LLM). Same role checks and validation as the assistant."""
    if name not in TOOLS_BY_NAME:
        raise not_found("Tool")
    payload, is_error = service.execute_tool(conn, session, request, user, name, args or {})
    if is_error:
        session.commit()  # keep denial/rejected-SQL audit rows: the error response rolls back
        status_code = 403 if payload.get("code") == "forbidden" else 422
        raise ApiError(
            status_code, payload.get("code", "tool_error"), payload["error"], payload.get("details")
        )
    return payload


@router.post("/query", response_model=AssistantAnswer)
@limiter.limit(ASSISTANT_LIMIT)
def query(
    request: Request,
    response: Response,
    body: AssistantQuery,
    user: Viewer,
    conn: ReadConn,
    session: AppSession,
):
    provider = _provider_or_none()
    if provider is None:
        raise ApiError(
            503,
            "assistant_unavailable",
            "The AI assistant is not configured (no LLM API key). Use the tools catalog instead.",
        )
    history = [t.model_dump() for t in body.history]
    try:
        result = service.run(body.question, history, user, conn, session, request, provider)
    except anthropic.APIStatusError as exc:
        _log_failure(session, request, user, body.question, f"provider {exc.status_code}")
        code = 429 if exc.status_code == 429 else 502
        raise ApiError(
            code, "llm_error", "The language model service returned an error. Try again later."
        ) from exc
    except anthropic.APIConnectionError as exc:  # includes timeouts
        _log_failure(session, request, user, body.question, "provider connection/timeout")
        raise ApiError(504, "llm_timeout", "The language model did not respond in time.") from exc
    service.log_result(session, request, user, body.question, result)
    return AssistantAnswer(
        status=result.status,
        answer=result.answer,
        model=result.model,
        served_by_fallback=result.served_by_fallback,
        tool_calls=result.tool_calls,
        iterations=result.iterations,
        latency_ms=result.latency_ms,
        usage={"input_tokens": result.input_tokens, "output_tokens": result.output_tokens},
    )


def _log_failure(session, request, user, question: str, error: str) -> None:
    """Error responses roll the request session back, so persist the log row first."""
    log.warning("assistant query failed: %s", error)
    service.log_result(session, request, user, question, None, error=error)
    session.commit()
