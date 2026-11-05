"""The assistant loop: question -> model -> validated read-only tool calls -> grounded answer.

Safety properties (tested in backend/tests/test_assistant.py):
- the model only sees tools the user's role allows; a call to any other tool is refused and
  audited (never executed);
- every tool input is validated (pydantic) before a query runs; invalid input, unsafe SQL and
  database errors go back to the model as error results, never raw exceptions;
- the loop is bounded (assistant_max_iterations); refusals and truncation are reported;
- every question is logged to app.assistant_log with tool calls, tokens, latency and status.
"""

import json
import logging
import time
from dataclasses import dataclass, field

import sqlalchemy as sa
from fastapi import Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.assistant.prompts import SYSTEM_PROMPT
from app.assistant.provider import LLMProvider
from app.assistant.sql_guard import UnsafeQueryError
from app.assistant.tools import TOOLS, TOOLS_BY_NAME, Tool
from app.core.config import get_settings
from app.models.entities import ROLES, AssistantLog, User
from app.services import audit

log = logging.getLogger("app.assistant")
RANK = {r: i for i, r in enumerate(ROLES)}
MAX_RESULT_CHARS = 60_000  # bound what one tool result adds to the model's context


@dataclass
class AssistantResult:
    status: str
    answer: str
    model: str | None
    tool_calls: list[dict] = field(default_factory=list)
    iterations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    served_by_fallback: bool = False


def allowed_tools(user: User) -> list[Tool]:
    return [t for t in TOOLS if RANK[user.role] >= RANK[t.min_role]]


def execute_tool(
    conn: sa.Connection,
    session: Session,
    request: Request | None,
    user: User,
    name: str,
    raw_args: dict,
) -> tuple[dict, bool]:
    """Run one tool for `user`. Returns (payload, is_error). Never raises for bad input."""
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        return {"error": f"Unknown tool {name!r}"}, True
    if RANK[user.role] < RANK[tool.min_role]:
        audit.record(
            session,
            request,
            "assistant_tool",
            "denied",
            user.id,
            tool=name,
            required=tool.min_role,
            role=user.role,
        )
        return {
            "code": "forbidden",
            "error": f"Tool {name} requires the {tool.min_role} role; "
            "this user cannot access that data.",
        }, True
    try:
        args = tool.args_model.model_validate(raw_args or {})
    except ValidationError as exc:
        return {"error": "Invalid arguments", "details": exc.errors(include_url=False)}, True
    try:
        return tool.handler(conn, args), False
    except UnsafeQueryError as exc:
        audit.record(session, request, "assistant_sql", "denied", user.id, reason=str(exc))
        return {"error": f"Query rejected: {exc}"}, True
    except sa.exc.DBAPIError as exc:
        conn.rollback()
        timeout = "statement timeout" in str(exc.orig).lower() or "annul" in str(exc.orig).lower()
        reason = "Query timed out (5 s limit)" if timeout else "Query failed in the database"
        log.warning("assistant tool %s failed: %s", name, exc.orig)
        return {"error": reason}, True


def _to_text(payload: dict) -> str:
    text = json.dumps(payload, default=str, ensure_ascii=False)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + ' ... [truncated: narrow the question or add filters]"'
    return text


def run(
    question: str,
    history: list[dict],
    user: User,
    conn: sa.Connection,
    session: Session,
    request: Request | None,
    provider: LLMProvider,
) -> AssistantResult:
    settings = get_settings()
    tools = allowed_tools(user)
    definitions = [t.api_definition() for t in tools]
    messages: list = [{"role": h["role"], "content": h["content"]} for h in history]
    messages.append({"role": "user", "content": question})
    result = AssistantResult(status="error", answer="", model=provider.model)
    started = time.perf_counter()

    for iteration in range(1, settings.assistant_max_iterations + 1):
        result.iterations = iteration
        response = provider.create(system=SYSTEM_PROMPT, messages=messages, tools=definitions)
        usage = getattr(response, "usage", None)
        result.input_tokens += getattr(usage, "input_tokens", 0) or 0
        result.output_tokens += getattr(usage, "output_tokens", 0) or 0
        result.model = getattr(response, "model", None) or provider.model
        if any(getattr(b, "type", None) == "fallback" for b in response.content):
            result.served_by_fallback = True

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None)
            result.status = "refused"
            result.answer = (
                "The model declined to answer this request"
                + (f" (category: {category})" if category else "")
                + "."
            )
            break

        # Append the full content (incl. thinking blocks) so the history stays append-only.
        messages.append({"role": "assistant", "content": response.content})
        tool_uses = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
        if response.stop_reason != "tool_use" or not tool_uses:
            text = "\n".join(b.text for b in response.content if getattr(b, "type", None) == "text")
            result.answer = text.strip()
            result.status = "truncated" if response.stop_reason == "max_tokens" else "answered"
            break

        tool_results = []
        for block in tool_uses:
            t0 = time.perf_counter()
            payload, is_error = execute_tool(
                conn, session, request, user, block.name, dict(block.input or {})
            )
            result.tool_calls.append(
                {
                    "name": block.name,
                    "input": block.input,
                    "status": "error" if is_error else "ok",
                    "meta": payload.get("meta"),
                    "error": payload.get("error") if is_error else None,
                    "data": payload.get("data") if not is_error else None,
                    "ms": int((time.perf_counter() - t0) * 1000),
                }
            )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": _to_text(payload),
                    "is_error": is_error,
                }
            )
        # All results of one turn go back in a single user message.
        messages.append({"role": "user", "content": tool_results})
    else:
        result.status = "iteration_limit"
        result.answer = "I could not finish within the tool-call limit. Try a narrower question."

    result.latency_ms = int((time.perf_counter() - started) * 1000)
    return result


def log_result(
    session: Session,
    request: Request | None,
    user: User,
    question: str,
    result: AssistantResult | None,
    error: str | None = None,
) -> None:
    """Persist the audit record. Tool data is not stored (only names, inputs, row counts)."""
    keep = ("name", "input", "status", "error", "ms")
    calls = [
        {k: c[k] for k in keep} | {"rows": (c["meta"] or {}).get("rows")}
        for c in (result.tool_calls if result else [])
    ]
    session.add(
        AssistantLog(
            user_id=user.id,
            question=question,
            status=result.status if result else "error",
            answer=result.answer if result else None,
            model=result.model if result else None,
            tool_calls=calls,
            iterations=result.iterations if result else 0,
            input_tokens=result.input_tokens if result else 0,
            output_tokens=result.output_tokens if result else 0,
            latency_ms=result.latency_ms if result else None,
            request_id=getattr(request.state, "request_id", None) if request else None,
            error=error,
        )
    )
