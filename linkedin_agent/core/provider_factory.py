"""
Factory helpers for selecting the active LLM provider.

The main pipeline intentionally defaults to Claude. Gemini remains available
only as a legacy fallback for deprecated scripts or manual migration work.
"""
from __future__ import annotations

from linkedin_agent.config.settings import Settings
from linkedin_agent.core.ai_client import AIClient, MODEL as DEFAULT_GEMINI_MODEL
from linkedin_agent.core.claude_client import ClaudeClient, MODEL as DEFAULT_CLAUDE_MODEL
from linkedin_agent.core.llm_provider import LLMProvider


def create_llm_provider(settings: Settings, provider_name: str | None = None) -> LLMProvider:
    provider = (provider_name or settings.llm_provider or "claude").lower().strip()

    if provider == "claude":
        if not settings.anthropic_api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY non impostata: la pipeline principale richiede Claude."
            )
        return ClaudeClient(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model or DEFAULT_CLAUDE_MODEL,
        )

    if provider == "gemini":
        if not settings.gemini_api_key:
            raise EnvironmentError(
                "GEMINI_API_KEY non impostata: il provider Gemini legacy non e' disponibile."
            )
        return AIClient(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model or DEFAULT_GEMINI_MODEL,
        )

    raise ValueError(f"Provider LLM non supportato: {provider}")
