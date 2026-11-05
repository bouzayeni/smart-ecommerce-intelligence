"""LLM provider abstraction. The assistant loop depends only on `LLMProvider`; tests use a
scripted provider, production uses Anthropic's Messages API through the official SDK."""

from typing import Any, Protocol

from app.core.config import get_settings


class LLMProvider(Protocol):
    name: str
    model: str

    def create(self, *, system: str, messages: list, tools: list[dict]) -> Any:
        """Return a message object exposing .content, .stop_reason, .stop_details, .usage."""
        ...


class ProviderUnavailableError(RuntimeError):
    pass


class AnthropicProvider:
    """Claude via the Anthropic SDK.

    - Server-side refusal fallback is enabled (`fallbacks: "default"`, beta
      server-side-fallback-2026-07-01): if a safety classifier declines, the API re-runs the
      request on Anthropic's recommended fallback model inside the same call.
    - Thinking is adaptive (always on for Opus 5.5); effort is set explicitly because Opus 5.5
      defaults to medium.
    - tool_choice stays "auto" (forced tool use is rejected on this model); the system prompt
      tells the model to use tools.
    """

    name = "anthropic"

    def __init__(self, api_key: str, model: str, effort: str, timeout_s: float):
        import anthropic

        self.model = model
        self.effort = effort
        self.client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=2)

    def create(self, *, system: str, messages: list, tools: list[dict]):
        return self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=messages,
            tools=tools,
            output_config={"effort": self.effort},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )


def get_provider() -> LLMProvider:
    s = get_settings()
    if s.llm_provider != "anthropic":
        raise ProviderUnavailableError(f"Unsupported LLM_PROVIDER {s.llm_provider!r}")
    key = s.anthropic_api_key.get_secret_value()
    if not key:
        raise ProviderUnavailableError("ANTHROPIC_API_KEY is not set")
    return AnthropicProvider(key, s.anthropic_model, s.assistant_effort, s.assistant_timeout_s)
