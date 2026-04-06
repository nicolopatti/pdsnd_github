"""
Thin wrapper around the Anthropic Python SDK.
Provides a single generate() method with retry logic.
"""
from __future__ import annotations

import time
from typing import Optional

import anthropic

from linkedin_agent.core.llm_provider import LLMJsonMixin

MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 1024


class ClaudeClient(LLMJsonMixin):
    def __init__(self, api_key: str, model: str = MODEL) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        response_mime_type: str | None = None,
    ) -> str:
        """Single-turn text generation. Returns the assistant's text response."""
        message = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return message.content[0].text

    def generate_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_retries: int = 4,
        response_mime_type: str | None = None,
    ) -> str:
        """Same as generate() but retries on rate-limit errors with exponential backoff."""
        delay = 2
        last_error: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                return self.generate(system_prompt, user_prompt, max_tokens)
            except anthropic.RateLimitError as e:
                last_error = e
                if attempt < max_retries:
                    time.sleep(delay)
                    delay *= 2
            except anthropic.APIStatusError as e:
                # Surface non-rate-limit API errors immediately
                raise
        raise last_error  # type: ignore[misc]

    @staticmethod
    def describe_error(error: Exception, model_name: str | None = None) -> str:
        text = str(error)
        model_hint = f" Modello usato: `{model_name}`." if model_name else ""

        if isinstance(error, anthropic.RateLimitError):
            return (
                "Claude ha rifiutato la richiesta per limiti di quota o rate limit."
                f"{model_hint} Attendi e riprova, oppure verifica billing e limiti dell'account."
            )

        if isinstance(error, anthropic.AuthenticationError):
            return (
                "Claude ha rifiutato la richiesta per credenziali non valide."
                f"{model_hint} Verifica `ANTHROPIC_API_KEY`."
            )

        if isinstance(error, anthropic.NotFoundError):
            return (
                "Il modello Claude configurato non sembra disponibile per questo account."
                f"{model_hint} Verifica `ANTHROPIC_MODEL`."
            )

        if isinstance(error, anthropic.APIStatusError):
            return (
                f"Claude ha restituito un errore API: {text}.{model_hint}"
            )

        return f"Errore Claude non gestito: {text}"
