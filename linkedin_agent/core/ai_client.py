"""
AI client using Google Gemini 1.5 Flash (free tier).
Drop-in replacement for the previous Anthropic client.
Get your free API key at https://aistudio.google.com
"""
from __future__ import annotations

import time
from typing import Optional

import google.generativeai as genai

MODEL = "gemini-1.5-flash"
DEFAULT_MAX_TOKENS = 1024


class AIClient:
    def __init__(self, api_key: str, model: str = MODEL) -> None:
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(
            model_name=model,
            generation_config=genai.GenerationConfig(
                max_output_tokens=DEFAULT_MAX_TOKENS,
            ),
        )
        self._model_name = model

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> str:
        """Single-turn text generation. Returns the model's text response."""
        # Gemini free API doesn't support separate system instructions in all versions;
        # we concatenate system + user into a single prompt.
        full_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"
        response = self._model.generate_content(
            full_prompt,
            generation_config=genai.GenerationConfig(max_output_tokens=max_tokens),
        )
        return response.text

    def generate_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_retries: int = 4,
    ) -> str:
        """Same as generate() but retries on quota/rate-limit errors with exponential backoff."""
        import google.api_core.exceptions as gexc

        delay = 2
        last_error: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                return self.generate(system_prompt, user_prompt, max_tokens)
            except (gexc.ResourceExhausted, gexc.ServiceUnavailable) as e:
                last_error = e
                if attempt < max_retries:
                    time.sleep(delay)
                    delay *= 2
            except Exception:
                raise
        raise last_error  # type: ignore[misc]


# Backwards-compatible alias used by existing modules
ClaudeClient = AIClient
