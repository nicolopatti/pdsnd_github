"""
AI client using Google Gemini.
Supports model override via environment/config and exposes friendlier
diagnostics for quota and model-availability failures.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from google import genai
from google.genai import types

from linkedin_agent.core.llm_provider import LLMJsonMixin

MODEL = "gemini-2.0-flash-lite"
DEFAULT_MAX_TOKENS = 1024


class AIClient(LLMJsonMixin):
    def __init__(self, api_key: str, model: str = MODEL) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model_name = model

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        response_mime_type: str | None = None,
    ) -> str:
        """Single-turn text generation. Returns the model's text response."""
        # Concatenate system + user into a single prompt (simpler and works across all tiers)
        full_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"
        config_kwargs: dict[str, Any] = {"max_output_tokens": max_tokens}
        if response_mime_type:
            config_kwargs["response_mime_type"] = response_mime_type
        response = self._client.models.generate_content(
            model=self._model_name,
            contents=full_prompt,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        text = getattr(response, "text", None)
        if text:
            return text

        candidates = getattr(response, "candidates", None) or []
        parts: list[str] = []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            candidate_parts = getattr(content, "parts", None) or []
            for part in candidate_parts:
                part_text = getattr(part, "text", None)
                if part_text:
                    parts.append(part_text)
        return "\n".join(parts)

    @property
    def model_name(self) -> str:
        return self._model_name

    def generate_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_retries: int = 4,
        response_mime_type: str | None = None,
    ) -> str:
        """Same as generate() but retries on quota/rate-limit errors with exponential backoff."""
        try:
            import google.api_core.exceptions as gexc
            _retryable = (gexc.ResourceExhausted, gexc.ServiceUnavailable)
        except ImportError:
            _retryable = ()  # type: ignore[assignment]

        delay = 2
        last_error: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                return self.generate(
                    system_prompt,
                    user_prompt,
                    max_tokens,
                    response_mime_type=response_mime_type,
                )
            except _retryable as e:
                last_error = e
                if attempt < max_retries:
                    time.sleep(delay)
                    delay *= 2
            except Exception:
                raise
        raise last_error  # type: ignore[misc]

    @staticmethod
    def describe_error(error: Exception, model_name: str | None = None) -> str:
        """
        Convert low-level SDK/API exceptions into a user-facing explanation.
        """
        text = str(error)
        model_hint = f" Modello usato: `{model_name}`." if model_name else ""

        if "RESOURCE_EXHAUSTED" in text or "quota" in text.lower() or "429" in text:
            if "limit: 0" in text:
                return (
                    "Gemini ha rifiutato la richiesta perche' la quota disponibile per questo "
                    "progetto/modello risulta pari a 0, quindi anche la prima chiamata fallisce."
                    f"{model_hint} Verifica che la API key punti al progetto corretto, che il "
                    "progetto abbia quota attiva e, se necessario, prova un altro modello tramite "
                    "`GEMINI_MODEL`."
                )
            return (
                "Gemini ha rifiutato la richiesta per limiti di quota o rate limit."
                f"{model_hint} Attendi e riprova, oppure verifica billing e quote del progetto."
            )

        if "404" in text or "not found" in text.lower() or "unsupported" in text.lower():
            return (
                "Il modello Gemini configurato non sembra disponibile per questa API key o per "
                "questo progetto."
                f"{model_hint} Imposta un modello supportato tramite `GEMINI_MODEL`."
            )

        return f"Errore Gemini non gestito: {text}"


# Backwards-compatible alias used by existing modules
ClaudeClient = AIClient
