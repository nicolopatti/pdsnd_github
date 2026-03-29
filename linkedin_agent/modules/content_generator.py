"""
Generates LinkedIn post drafts using Claude.
Uses a value-first content philosophy: every post must give the reader
something actionable, practical, or insightful.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from linkedin_agent.config.settings import Settings
from linkedin_agent.core.claude_client import ClaudeClient
from linkedin_agent.modules.tracker import PostDraft

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


class ContentGenerator:
    def __init__(self, settings: Settings, claude: ClaudeClient) -> None:
        self._settings = settings
        self._claude = claude
        self._system_template = _load_prompt("post_generation.txt")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_post_draft(
        self,
        pillar: str | None = None,
        format_type: str | None = None,
        context: str | None = None,
    ) -> PostDraft:
        """
        Generate a single LinkedIn post draft.

        Args:
            pillar: Content pillar name. If None, picks one by weighted random.
            format_type: Content format name. If None, picks one by weighted random.
            context: Optional current-events context to make the post timely
                     (e.g., "Nuova call Horizon Europe aperta fino al 15 aprile").
        """
        pillar = pillar or self._pick_pillar()
        fmt = self._get_format(format_type) or self._pick_format()

        system_prompt = self._build_system_prompt(pillar, fmt)
        user_prompt = self._build_user_prompt(pillar, fmt, context)

        raw = self._claude.generate_with_retry(system_prompt, user_prompt, max_tokens=800)
        content, hashtags = self._parse_response(raw)

        return PostDraft(
            content=content,
            hashtags=hashtags,
            pillar=pillar,
            format_type=fmt["name"],
        )

    def generate_weekly_calendar(self, count: int | None = None) -> list[PostDraft]:
        """
        Generate multiple post drafts covering different pillars and formats.
        Useful for preparing a full week of content in one session.
        """
        n = count or self._settings.activity.daily_limits.posts_per_week
        pillars = self._settings.niche.content_pillars
        formats = self._settings.niche.content_formats

        # Rotate through pillars to ensure variety
        expanded_pillars = [p.name for p in pillars for _ in range(p.weight)]
        selected_pillars = random.sample(expanded_pillars, min(n, len(expanded_pillars)))

        drafts: list[PostDraft] = []
        for pillar_name in selected_pillars[:n]:
            draft = self.generate_post_draft(pillar=pillar_name)
            drafts.append(draft)
        return drafts

    def improve_draft(self, draft: PostDraft, feedback: str) -> PostDraft:
        """
        Regenerate a draft based on user feedback.
        Returns a new PostDraft with status='pending'.
        """
        fmt = self._get_format(draft.format_type) or self._pick_format()
        system_prompt = self._build_system_prompt(draft.pillar, fmt)
        user_prompt = (
            f"Riscrivi il seguente post LinkedIn incorporando questo feedback: {feedback}\n\n"
            f"POST ORIGINALE:\n{draft.content}\n\n"
            f"HASHTAG ORIGINALI: {', '.join(draft.hashtags)}"
        )
        raw = self._claude.generate_with_retry(system_prompt, user_prompt, max_tokens=800)
        content, hashtags = self._parse_response(raw)
        return PostDraft(
            content=content,
            hashtags=hashtags,
            pillar=draft.pillar,
            format_type=draft.format_type,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _pick_pillar(self) -> str:
        pillars = self._settings.niche.content_pillars
        pool = [p.name for p in pillars for _ in range(p.weight)]
        return random.choice(pool)

    def _pick_format(self) -> dict:
        formats = self._settings.niche.content_formats
        pool = [f for f in formats for _ in range(f.weight)]
        chosen = random.choice(pool)
        return {"name": chosen.name, "description": chosen.description}

    def _get_format(self, name: str | None) -> dict | None:
        if not name:
            return None
        for f in self._settings.niche.content_formats:
            if f.name == name:
                return {"name": f.name, "description": f.description}
        return None

    def _build_system_prompt(self, pillar: str, fmt: dict) -> str:
        s = self._settings
        tone_map = {
            "formal": "formale e preciso",
            "professional_warm": "professionale ma accessibile, come un collega esperto che spiega a un pari",
            "conversational": "colloquiale e diretto",
        }
        return self._system_template.format(
            user_name=s.user.name,
            user_headline=s.user.headline,
            tone=tone_map.get(s.user.tone, s.user.tone),
            pillar=pillar,
            format_type=fmt["name"],
            format_description=fmt["description"],
        )

    def _build_user_prompt(self, pillar: str, fmt: dict, context: str | None) -> str:
        keywords = ", ".join(self._settings.niche.primary_keywords[:6])
        hashtags = ", ".join(self._settings.niche.hashtags[:6])
        prompt = (
            f"Scrivi un post LinkedIn per il pilastro '{pillar}' usando il formato '{fmt['name']}'.\n"
            f"Keyword rilevanti da considerare: {keywords}\n"
            f"Hashtag da usare (scegli i più pertinenti): {hashtags}\n"
        )
        if context:
            prompt += f"\nCONTESTO ATTUALE (usa per rendere il post tempestivo): {context}\n"
        prompt += "\nRispondi SOLO con il JSON richiesto."
        return prompt

    def _parse_response(self, raw: str) -> tuple[str, list[str]]:
        """Parse Claude's JSON response. Falls back gracefully on parse errors."""
        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
        try:
            data = json.loads(text)
            content = data.get("content", "").strip()
            hashtags = data.get("hashtags", [])
            if not isinstance(hashtags, list):
                hashtags = []
            return content, hashtags
        except json.JSONDecodeError:
            # Best-effort: return raw text without hashtags
            return raw.strip(), []
