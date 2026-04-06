"""
Common LLM provider interfaces and shared parsing helpers.

The rest of the application should depend on this module instead of binding
directly to a specific SDK client. This keeps provider migration contained to
the factory layer.
"""
from __future__ import annotations

import json
import re
from typing import Any, Protocol


class LLMProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        response_mime_type: str | None = None,
    ) -> str: ...

    def generate_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        max_retries: int = 4,
        response_mime_type: str | None = None,
    ) -> str: ...

    def describe_error(self, error: Exception, model_name: str | None = None) -> str: ...

    @staticmethod
    def extract_json_payload(raw: str | None) -> str: ...

    @classmethod
    def parse_json_response(cls, raw: str) -> dict[str, Any]: ...

    @classmethod
    def parse_json_response_safe(cls, raw: str) -> dict[str, Any]: ...


class LLMJsonMixin:
    @staticmethod
    def extract_json_payload(raw: str | None) -> str:
        if not raw:
            return ""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                text = "\n".join(lines[1:-1]).strip()

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start:end + 1]
        return text

    @classmethod
    def parse_json_response(cls, raw: str) -> dict[str, Any]:
        text = cls.extract_json_payload(raw)
        return json.loads(text)

    @classmethod
    def parse_json_response_safe(cls, raw: str) -> dict[str, Any]:
        """
        Best-effort JSON parser for LLM responses. Handles fenced code blocks and
        trailing prose; returns an empty dict when parsing is impossible.
        """
        try:
            return cls.parse_json_response(raw)
        except Exception:
            text = cls.extract_json_payload(raw)
            match = re.search(r"\{[\s\S]*\}", text)
            if not match:
                return {}
            try:
                return json.loads(match.group(0))
            except Exception:
                return {}
