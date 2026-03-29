"""
Thin wrapper around the Anthropic Python SDK.
Provides a single generate() method with retry logic.
"""
from __future__ import annotations

import time
from typing import Optional

import anthropic

MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 1024


class ClaudeClient:
    def __init__(self, api_key: str, model: str = MODEL) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
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
