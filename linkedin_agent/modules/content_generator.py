"""
Generates LinkedIn post drafts using the configured LLM provider.
Uses a value-first content philosophy: every post must give the reader
something actionable, practical, or insightful.
"""
from __future__ import annotations

import random
import re
from pathlib import Path

from linkedin_agent.config.settings import Settings
from linkedin_agent.modules.context_collector import ContextSnapshot
from linkedin_agent.core.llm_provider import LLMProvider
from linkedin_agent.modules.knowledge_types import ContentBrief, DraftSet, DraftVariant
from linkedin_agent.modules.tracker import ActivityTracker, PostDraft, PostGenerationResult

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


class ContentGenerator:
    def __init__(
        self,
        settings: Settings,
        llm: LLMProvider,
        tracker: ActivityTracker | None = None,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._tracker = tracker
        self._system_template = _load_prompt("post_generation.txt")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_post_draft(
        self,
        snapshot: ContextSnapshot | None = None,
        brief: ContentBrief | None = None,
        pillar: str | None = None,
        format_type: str | None = None,
        context: str | None = None,
    ) -> PostGenerationResult:
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
        snapshot_id = brief.snapshot_id if brief else (snapshot.snapshot_id if snapshot else None)

        if not brief and (not snapshot or snapshot.status != "sufficient"):
            result = PostGenerationResult(
                status="insufficient_context",
                error_message="Contesto insufficiente: serve uno snapshot valido o un content brief.",
                snapshot_id=snapshot_id,
            )
            self._log_generation_result(result)
            return result

        system_prompt = self._build_system_prompt(pillar, fmt)
        user_prompt = self._build_user_prompt(snapshot, pillar, fmt, context, brief=brief)

        try:
            raw = self.generate_raw_post_response(system_prompt, user_prompt)
            parsed = self._enrich_partial_response(self.parse_post_response(raw), snapshot, brief=brief)
            validation_errors = self.validate_post_draft(parsed, snapshot, brief=brief)
            if validation_errors:
                repaired_raw = self._repair_or_regenerate_response(system_prompt, user_prompt, raw)
                parsed = self._enrich_partial_response(self.parse_post_response(repaired_raw), snapshot, brief=brief)
                validation_errors = self.validate_post_draft(parsed, snapshot, brief=brief)
                raw = repaired_raw

            if validation_errors:
                result = PostGenerationResult(
                    status="invalid_ai_output",
                    error_message="Il provider LLM ha restituito un output non valido per il post.",
                    raw_response_excerpt=self._excerpt(raw),
                    validation_errors=self._classify_raw_failure(raw, fallback_errors=validation_errors),
                    snapshot_id=snapshot_id,
                )
                self._log_generation_result(result)
                return result

            draft = self._to_post_draft(parsed, pillar=pillar, format_type=fmt["name"])
            result = PostGenerationResult(
                status="ok",
                draft=draft,
                snapshot_id=snapshot_id,
            )
            self._log_generation_result(result)
            return result
        except Exception as exc:
            result = PostGenerationResult(
                status="provider_error",
                error_message=self._llm.describe_error(exc, self._llm.model_name),
                snapshot_id=snapshot_id,
            )
            self._log_generation_result(result)
            return result

    def generate_post_variants(
        self,
        brief: ContentBrief,
        count: int = 3,
        snapshot: ContextSnapshot | None = None,
    ) -> DraftSet:
        """
        Preferred knowledge-first API.

        The brief is mandatory so variants can be retried without rebuilding the
        full context. Snapshot remains optional during migration.
        """
        if not brief:
            raise ValueError("ContentBrief richiesto per generare varianti.")

        instructions = [
            "Variante 1: tono consulenziale diretto, molto operativo.",
            "Variante 2: struttura checklist o sequenza pratica, senza perdere autorevolezza.",
            "Variante 3: taglio piu' netto e differenziante, con hook meno ovvio.",
            "Variante 4: apri da un errore comune che osservi nel settore e poi proponi una correzione pratica.",
            "Variante 5: usa un taglio comparativo tra chi intercetta i bandi e chi li perde per impostazione errata.",
        ]
        target_count = max(1, min(count, 3))
        variants: list[DraftVariant] = []
        seen_contents: set[str] = set()
        for idx, instruction in enumerate(instructions):
            if len(variants) >= target_count:
                break
            result = self.generate_post_draft(
                snapshot=snapshot,
                brief=brief,
                pillar="knowledge_first",
                format_type="brief_variant",
                context=instruction,
            )
            if not result.is_ok or not result.draft:
                continue
            normalized = result.draft.content.strip().lower()
            if normalized in seen_contents:
                continue
            seen_contents.add(normalized)
            variants.append(
                DraftVariant(
                    angle_label=f"{brief.angle_label} · variante {idx + 1}",
                    content=result.draft.content,
                    hashtags=result.draft.hashtags,
                    rationale=result.draft.rationale,
                    context_sources=result.draft.context_sources,
                    editorial_score=self._estimate_editorial_score(result.draft, brief),
                )
            )

        return DraftSet(brief=brief, variants=variants)

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
            result = self.generate_post_draft(snapshot=None, pillar=pillar_name)
            if result.draft:
                drafts.append(result.draft)
        return drafts

    def improve_draft(self, draft: PostDraft, feedback: str, snapshot: ContextSnapshot | None = None) -> PostDraft:
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
        raw = self._llm.generate_with_retry(system_prompt, user_prompt, max_tokens=800)
        parsed = self.parse_post_response(raw)
        validation_errors = self.validate_post_draft(parsed, snapshot)
        if validation_errors:
            return draft
        content, hashtags, _, _, _ = self._normalize_parsed_response(parsed)
        return PostDraft(
            content=content,
            hashtags=hashtags,
            pillar=draft.pillar,
            format_type=draft.format_type,
            rationale=draft.rationale,
            chosen_pattern=draft.chosen_pattern,
            context_sources=draft.context_sources,
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

    def _build_user_prompt(
        self,
        snapshot: ContextSnapshot | None,
        pillar: str,
        fmt: dict,
        context: str | None,
        brief: ContentBrief | None = None,
    ) -> str:
        keywords = ", ".join(self._settings.niche.primary_keywords[:6])
        hashtags = ", ".join(self._settings.niche.hashtags[:6])
        prompt = (
            f"Scrivi un post LinkedIn per il pilastro '{pillar}' usando il formato '{fmt['name']}'.\n"
            "Mantieni il post tra 1500 e 2200 caratteri circa, senza superare 3000 caratteri.\n"
            f"Keyword rilevanti da considerare: {keywords}\n"
            f"Hashtag da usare (scegli i più pertinenti): {hashtags}\n"
        )
        if snapshot:
            prompt += "\nCONTESTO REALE DA USARE OBBLIGATORIAMENTE:\n"
            if snapshot.profile_snapshot:
                prompt += (
                    f"- Profilo reale: {snapshot.profile_snapshot.full_name} | {snapshot.profile_snapshot.headline}\n"
                    f"- About: {snapshot.profile_snapshot.about[:350]}\n"
                )
            if snapshot.recent_posts_snapshot:
                prompt += "- Tuoi post recenti:\n"
                for post in snapshot.recent_posts_snapshot[:3]:
                    prompt += f"  * {post.text[:160]}\n"
            if snapshot.niche_posts_snapshot:
                prompt += "- Post del settore analizzati:\n"
                for post in snapshot.niche_posts_snapshot[:4]:
                    prompt += (
                        f"  * {post.author_name}: {post.text[:160]} "
                        f"(reazioni {post.reaction_count}, query {post.source_query})\n"
                    )
            if snapshot.niche_profiles_snapshot:
                prompt += "- Profili del settore analizzati:\n"
                for profile in snapshot.niche_profiles_snapshot[:4]:
                    prompt += f"  * {profile.full_name} | {profile.headline}\n"
        if context:
            prompt += f"\nISTRUZIONE AGGIUNTIVA PER QUESTA VARIANTE: {context}\n"
        if brief:
            prompt += "\nCONTENT BRIEF STRUTTURATO DA USARE COME FONTE PRINCIPALE:\n"
            prompt += f"- Angolo scelto: {brief.angle_label}\n"
            prompt += f"- Pattern scelto: {brief.selected_pattern}\n"
            prompt += f"- Target reader: {brief.target_reader}\n"
            prompt += f"- CTA consigliata: {brief.recommended_cta}\n"
            if brief.supporting_points:
                prompt += "- Punti da sviluppare:\n"
                for point in brief.supporting_points[:5]:
                    prompt += f"  * {point}\n"
            if brief.context_sources:
                prompt += "- Evidenze/fonte da incorporare:\n"
                for source in brief.context_sources[:5]:
                    prompt += f"  * {source}\n"
        prompt += (
            "\nScegli un pattern osservato nel contesto reale e spiegalo. "
            "Il post deve sembrare scritto da un consulente senior che sa dove si inceppano davvero bandi, candidature, requisiti, allegati e tempistiche. "
            "Evita formule scolastiche o troppo generiche. "
            "Rispondi SOLO con le sezioni CONTENT, HASHTAGS, RATIONALE, PATTERN e SOURCES."
        )
        return prompt

    def generate_raw_post_response(self, system_prompt: str, user_prompt: str) -> str:
        return self._llm.generate_with_retry(
            system_prompt,
            user_prompt,
            max_tokens=1400,
        )

    def parse_post_response(self, raw: str) -> dict:
        tagged = self._parse_tagged_response(raw)
        if tagged:
            return tagged
        return self._llm.parse_json_response_safe(raw)

    def validate_post_draft(
        self,
        data: dict,
        snapshot: ContextSnapshot | None,
        brief: ContentBrief | None = None,
    ) -> list[str]:
        errors: list[str] = []
        if not data:
            return ["Nessun JSON valido trovato nella risposta AI."]

        content, hashtags, rationale, chosen_pattern, context_sources = self._normalize_parsed_response(data)
        if not self._is_valid_post_content(content):
            errors.append("Il contenuto del post e' vuoto, troppo corto o sembra JSON grezzo.")
        if any(tag.startswith("{") or tag.startswith("[") for tag in hashtags):
            errors.append("Gli hashtag non sono normalizzati.")
        if (snapshot and snapshot.status == "sufficient") or brief:
            if not rationale:
                errors.append("Manca la rationale del post.")
            if not chosen_pattern:
                errors.append("Manca il pattern scelto.")
            if not context_sources:
                errors.append("Mancano le fonti di contesto usate.")
        return errors

    def _enrich_partial_response(
        self,
        data: dict,
        snapshot: ContextSnapshot | None,
        brief: ContentBrief | None = None,
    ) -> dict:
        if not data:
            return {}
        enriched = dict(data)
        content = enriched.get("content", "")
        if not isinstance(content, str) or not content.strip():
            return data

        hashtags = enriched.get("hashtags")
        if not isinstance(hashtags, list) or not hashtags:
            enriched["hashtags"] = self._default_hashtags()

        if not enriched.get("rationale"):
            enriched["rationale"] = (
                f"Post costruito a partire dal brief '{brief.angle_label}'."
                if brief else
                "Post generato a partire dal contesto LinkedIn raccolto oggi."
            )

        if not enriched.get("chosen_pattern"):
            enriched["chosen_pattern"] = brief.selected_pattern if brief else self._infer_pattern_from_snapshot(snapshot)

        sources = enriched.get("context_sources")
        if not isinstance(sources, list) or not sources:
            enriched["context_sources"] = brief.context_sources if brief and brief.context_sources else self._default_sources(snapshot)
        return enriched

    def _normalize_parsed_response(self, data: dict) -> tuple[str, list[str], str, str, list[str]]:
        content = data.get("content", "")
        hashtags = data.get("hashtags", [])
        rationale = data.get("rationale", "")
        chosen_pattern = data.get("chosen_pattern", "")
        context_sources = data.get("context_sources", [])

        if isinstance(content, list):
            content = "\n".join(str(item) for item in content)
        if not isinstance(content, str):
            content = str(content)

        if not isinstance(hashtags, list):
            hashtags = []
        if not isinstance(context_sources, list):
            context_sources = []

        normalized_hashtags = [str(tag).strip() for tag in hashtags if str(tag).strip()]
        normalized_sources = [str(item).strip() for item in context_sources if str(item).strip()]
        return content.strip(), normalized_hashtags, str(rationale).strip(), str(chosen_pattern).strip(), normalized_sources

    def _repair_or_regenerate_response(self, system_prompt: str, user_prompt: str, broken_raw: str) -> str:
        repair_user_prompt = (
            "La tua risposta precedente non era nel formato richiesto o era incompleta.\n"
            "Rigenera da zero il post rispettando esattamente le sezioni richieste.\n\n"
            f"RISPOSTA NON VALIDA PRECEDENTE:\n{broken_raw}\n\n"
            f"ISTRUZIONE ORIGINALE:\n{user_prompt}\n\n"
            "Rispondi SOLO con CONTENT, HASHTAGS, RATIONALE, PATTERN e SOURCES, senza markdown e senza testo extra."
        )
        return self._llm.generate_with_retry(
            system_prompt,
            repair_user_prompt,
            max_tokens=1400,
        )

    def _looks_like_broken_json(self, text: str) -> bool:
        stripped = (text or "").strip()
        return stripped.startswith("{") or stripped.startswith("[") or stripped.startswith("```")

    def _is_valid_post_content(self, content: str) -> bool:
        text = (content or "").strip()
        if len(text) < 40:
            return False
        invalid_starts = ("{", "[", '"content"', "```json", "```")
        return not any(text.startswith(prefix) for prefix in invalid_starts) and "{" not in text[:10]

    def _to_post_draft(self, data: dict, pillar: str, format_type: str) -> PostDraft:
        content, hashtags, rationale, chosen_pattern, context_sources = self._normalize_parsed_response(data)
        return PostDraft(
            content=content,
            hashtags=hashtags,
            pillar=pillar,
            format_type=format_type,
            rationale=rationale,
            chosen_pattern=chosen_pattern,
            context_sources=context_sources,
        )

    def _excerpt(self, raw: str | None) -> str:
        return (raw or "").strip().replace("\n", " ")[:300]

    def _classify_raw_failure(self, raw: str | None, fallback_errors: list[str]) -> list[str]:
        text = (raw or "").strip()
        if not text:
            return ["Il provider LLM non ha restituito alcun contenuto."]
        if ("```json" in text or text.startswith("{")) and "}" not in text:
            return ["La risposta JSON del provider LLM sembra troncata prima della chiusura."]
        if "CONTENT:" in text and "HASHTAGS:" not in text:
            return ["La risposta del post sembra troncata prima delle sezioni finali."]
        return fallback_errors

    def _parse_tagged_response(self, raw: str | None) -> dict:
        text = (raw or "").strip()
        if not text:
            return {}
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                text = "\n".join(lines[1:-1]).strip()

        if "CONTENT:" not in text:
            return {}

        def section(start: str, end_markers: list[str]) -> str:
            start_idx = text.find(start)
            if start_idx == -1:
                return ""
            start_idx += len(start)
            end_idx = len(text)
            for marker in end_markers:
                marker_idx = text.find(marker, start_idx)
                if marker_idx != -1:
                    end_idx = min(end_idx, marker_idx)
            return text[start_idx:end_idx].strip()

        content = section("CONTENT:", ["HASHTAGS:", "RATIONALE:", "PATTERN:", "SOURCES:"])
        hashtags_block = section("HASHTAGS:", ["RATIONALE:", "PATTERN:", "SOURCES:"])
        rationale = section("RATIONALE:", ["PATTERN:", "SOURCES:"])
        pattern_text = section("PATTERN:", ["SOURCES:"])
        sources_block = section("SOURCES:", [])

        hashtags = [
            line.strip().rstrip(",")
            for line in hashtags_block.splitlines()
            if line.strip()
        ]
        sources = [
            line.strip().lstrip("-").strip()
            for line in sources_block.splitlines()
            if line.strip()
        ]
        return {
            "content": content,
            "hashtags": hashtags,
            "rationale": rationale,
            "chosen_pattern": pattern_text,
            "context_sources": sources,
        }

    def _default_hashtags(self) -> list[str]:
        return self._settings.niche.hashtags[:5]

    def _infer_pattern_from_snapshot(self, snapshot: ContextSnapshot | None) -> str:
        if snapshot and snapshot.niche_posts_snapshot:
            return "Pattern osservato nei post del settore raccolti oggi"
        if snapshot and snapshot.recent_posts_snapshot:
            return "Pattern derivato dai tuoi post recenti"
        return "Pattern generato dal contesto disponibile"

    def _default_sources(self, snapshot: ContextSnapshot | None) -> list[str]:
        sources: list[str] = []
        if snapshot and snapshot.profile_snapshot:
            sources.append(f"Profilo reale: {snapshot.profile_snapshot.full_name}")
        for post in (snapshot.niche_posts_snapshot[:2] if snapshot else []):
            sources.append(f"Post settore: {post.author_name} · {post.text[:90]}...")
        for post in (snapshot.recent_posts_snapshot[:1] if snapshot else []):
            sources.append(f"Tuo post recente: {post.text[:90]}...")
        return sources or ["Contesto LinkedIn raccolto oggi"]

    def _estimate_editorial_score(self, draft: PostDraft, brief: ContentBrief) -> float:
        score = 0.45
        content = draft.content.lower()
        if len(draft.content) >= 600:
            score += 0.15
        if len(draft.content) >= 1200:
            score += 0.1
        if any(point.lower()[:20] in content for point in brief.supporting_points[:3]):
            score += 0.1
        if draft.context_sources:
            score += 0.1
        if draft.hashtags:
            score += 0.05
        return round(min(1.0, score), 3)

    def _log_generation_result(self, result: PostGenerationResult) -> None:
        if not self._tracker:
            return
        result.run_id = self._tracker.log_post_generation_run(
            snapshot_id=result.snapshot_id,
            model=self._llm.model_name,
            status=result.status,
            error_message=result.error_message,
            raw_excerpt=result.raw_response_excerpt,
            validation_errors=result.validation_errors,
            draft_post_id=result.draft.id if result.draft else None,
        )
