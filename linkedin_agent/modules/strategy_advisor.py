"""
Strategic advisor module.
Analyzes post performance, audits content style, benchmarks the niche,
and generates evidence-based weekly recommendations.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from linkedin_agent.config.settings import Settings
from linkedin_agent.core.llm_provider import LLMProvider
from linkedin_agent.modules.context_collector import ContextSnapshot
from linkedin_agent.modules.tracker import ActivityTracker, PostDraft

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


@dataclass
class StyleFeedback:
    value_score: float          # 0-10: how useful/actionable is this for the reader
    authority_score: float      # 0-10: how much does it position Niccolò as an expert
    suggestions: list[str]      # Concrete improvement suggestions
    evidence: list[str]         # Evidence/sources supporting suggestions
    approved: bool = False      # Set to True if user accepts the draft as-is


@dataclass
class PerformanceInsight:
    pattern: str                # What pattern was observed
    evidence: str               # Data point supporting it
    recommendation: str         # Actionable recommendation


@dataclass
class WeeklyStrategyBrief:
    week_summary: str
    what_worked: list[PerformanceInsight]
    what_to_improve: list[PerformanceInsight]
    top_3_recommendations: list[str]
    content_mix_feedback: str
    next_week_focus: str


class StrategyAdvisor:
    def __init__(
        self,
        settings: Settings,
        llm: LLMProvider,
        tracker: ActivityTracker,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._tracker = tracker
        self._prompt_template = (_PROMPTS_DIR / "strategy_advisor.txt").read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Content style audit
    # ------------------------------------------------------------------

    def audit_content_style(self, draft: PostDraft) -> StyleFeedback:
        """
        Analyze a post draft and return style feedback with scores and evidence-based suggestions.
        This is shown inline during the approval CLI review.
        """
        context = (
            f"Pilastro: {draft.pillar}\n"
            f"Formato: {draft.format_type}\n"
            f"Testo del post:\n{draft.content}\n"
            f"Hashtag: {', '.join(draft.hashtags)}"
        )
        output_format = (
            "JSON con questa struttura:\n"
            "{\n"
            '  "value_score": 0-10,\n'
            '  "authority_score": 0-10,\n'
            '  "suggestions": ["suggerimento 1", ...],\n'
            '  "evidence": ["fonte/dato a supporto 1", ...]\n'
            "}\n"
            "Fornisci 1-3 suggerimenti concreti e 1-2 evidenze che li supportano. "
            "Se il post è già buono (value >= 7 e authority >= 7), lo indichi esplicitamente "
            "e dai solo suggerimenti minori."
        )
        system_prompt = self._prompt_template.format(
            user_name=self._settings.user.name,
            user_headline=self._settings.user.headline,
            context=context,
            task="Valuta questo draft di post LinkedIn e fornisci feedback sul suo stile e valore per il lettore.",
            output_format=output_format,
        )
        user_prompt = "Analizza il post e fornisci il feedback in JSON."

        try:
            raw = self._llm.generate(system_prompt, user_prompt, max_tokens=600)
            data = self._llm.parse_json_response_safe(raw)
            return StyleFeedback(
                value_score=float(data.get("value_score", 5.0)),
                authority_score=float(data.get("authority_score", 5.0)),
                suggestions=data.get("suggestions", []),
                evidence=data.get("evidence", []),
            )
        except Exception:
            return StyleFeedback(
                value_score=5.0,
                authority_score=5.0,
                suggestions=["Impossibile analizzare il post in questo momento."],
                evidence=[],
            )

    # ------------------------------------------------------------------
    # Weekly strategy brief
    # ------------------------------------------------------------------

    def generate_weekly_strategy_brief(self) -> WeeklyStrategyBrief:
        """
        Generate a weekly strategic brief based on published posts and activity stats.
        Called automatically on Fridays from run_daily.py.
        """
        report = self._tracker.export_progress_report()
        recent_posts = self._tracker.get_published_posts(since_days=7)

        posts_summary = "\n".join(
            f"- [{p.format_type}] {p.pillar}: {p.content[:100]}..."
            for p in recent_posts
        ) or "Nessun post pubblicato questa settimana."

        context = (
            f"Statistiche settimanali:\n"
            f"- Post pubblicati: {report['this_week']['posts']}\n"
            f"- Commenti postati (oggi): {report['today']['comments']}\n"
            f"- Reazioni fatte (oggi): {report['today']['reactions']}\n"
            f"- Connessioni inviate (oggi): {report['today']['connections']}\n\n"
            f"Post della settimana:\n{posts_summary}\n\n"
            f"Totali all-time:\n"
            f"- Post pubblicati: {report['all_time']['posts_published']}\n"
            f"- Commenti postati: {report['all_time']['comments_posted']}\n"
            f"- Connessioni inviate: {report['all_time']['connections_sent']}"
        )
        output_format = (
            "JSON con questa struttura:\n"
            "{\n"
            '  "week_summary": "Sommario in 2 frasi",\n'
            '  "what_worked": [{"pattern": "...", "evidence": "...", "recommendation": "..."}, ...],\n'
            '  "what_to_improve": [{"pattern": "...", "evidence": "...", "recommendation": "..."}, ...],\n'
            '  "top_3_recommendations": ["raccomandazione 1", "2", "3"],\n'
            '  "content_mix_feedback": "Feedback sul mix di contenuti in 2-3 frasi",\n'
            '  "next_week_focus": "Un\'azione prioritaria per la prossima settimana"\n'
            "}\n"
            "Ogni insight deve citare una fonte o un dato a supporto (es. best practice LinkedIn, "
            "studi sull'algoritmo, analisi del niche). Sii diretto e pragmatico."
        )
        system_prompt = self._prompt_template.format(
            user_name=self._settings.user.name,
            user_headline=self._settings.user.headline,
            context=context,
            task=(
                "Genera un briefing strategico settimanale per migliorare la presenza LinkedIn "
                "di Niccolò nel niche fondi europei. "
                "Sfida le sue assunzioni se i dati lo suggeriscono."
            ),
            output_format=output_format,
        )
        user_prompt = "Genera il briefing strategico in JSON."

        try:
            raw = self._llm.generate_with_retry(system_prompt, user_prompt, max_tokens=1200)
            data = self._llm.parse_json_response_safe(raw)
            return WeeklyStrategyBrief(
                week_summary=data.get("week_summary", ""),
                what_worked=[PerformanceInsight(**i) for i in data.get("what_worked", [])],
                what_to_improve=[PerformanceInsight(**i) for i in data.get("what_to_improve", [])],
                top_3_recommendations=data.get("top_3_recommendations", []),
                content_mix_feedback=data.get("content_mix_feedback", ""),
                next_week_focus=data.get("next_week_focus", ""),
            )
        except Exception as e:
            return WeeklyStrategyBrief(
                week_summary="Errore nella generazione del briefing strategico.",
                what_worked=[],
                what_to_improve=[],
                top_3_recommendations=[],
                content_mix_feedback="",
                next_week_focus="",
            )

    # ------------------------------------------------------------------
    # Profile positioning analysis
    # ------------------------------------------------------------------

    def analyze_profile_positioning(self, snapshot: ContextSnapshot | None = None) -> dict:
        """
        Analyze the user's LinkedIn profile configuration and niche positioning.
        Returns a dict with scores, strengths, gaps, and concrete recommendations.
        """
        s = self._settings
        niche_keywords = ", ".join(s.niche.primary_keywords[:8])
        target_titles = ", ".join(s.target_profiles.job_titles[:5])
        pillars = ", ".join(p.name for p in s.niche.content_pillars)
        formats = ", ".join(f.name for f in s.niche.content_formats)

        profile_lines = [
            f"Profilo configurato: {s.user.name}",
            f"Headline configurata: {s.user.headline}",
            f"Niche: fondi europei, PNRR, bandi pubblici, terzo settore",
            f"Keyword principali: {niche_keywords}",
            f"Target audience: {target_titles}",
            f"Pilastri di contenuto: {pillars}",
            f"Formati usati: {formats}",
            f"Tono: {s.user.tone}",
        ]
        if snapshot and snapshot.profile_snapshot:
            profile_lines.extend(
                [
                    f"Profilo reale letto da LinkedIn: {snapshot.profile_snapshot.full_name}",
                    f"Headline reale: {snapshot.profile_snapshot.headline}",
                    f"About reale: {snapshot.profile_snapshot.about[:500]}",
                    f"Featured: {' | '.join(snapshot.profile_snapshot.featured_items[:3])}",
                    f"Experience: {' | '.join(snapshot.profile_snapshot.experience_items[:3])}",
                ]
            )
        if snapshot and snapshot.recent_posts_snapshot:
            profile_lines.append("Post recenti del profilo:")
            for post in snapshot.recent_posts_snapshot[:4]:
                profile_lines.append(f"- {post.text[:250]}")
        if snapshot and snapshot.niche_posts_snapshot:
            profile_lines.append("Benchmark post del settore:")
            for post in snapshot.niche_posts_snapshot[:4]:
                profile_lines.append(
                    f"- {post.author_name}: {post.text[:220]} (reazioni {post.reaction_count}, commenti {post.comment_count})"
                )
        if snapshot and snapshot.niche_profiles_snapshot:
            profile_lines.append("Profili settore osservati:")
            for profile in snapshot.niche_profiles_snapshot[:4]:
                profile_lines.append(f"- {profile.full_name}: {profile.headline}")
        context = "\n".join(profile_lines)
        output_format = (
            "JSON con questa struttura:\n"
            "{{\n"
            '  "positioning_score": 7.5,\n'
            '  "score_rationale": "Spiegazione del punteggio in 2 frasi",\n'
            '  "strengths": ["punto di forza 1", "punto di forza 2"],\n'
            '  "gaps": ["lacuna strategica 1", "lacuna strategica 2"],\n'
            '  "opportunities": ["opportunità di crescita 1", "opportunità 2"],\n'
            '  "profile_recommendations": [\n'
            '    {{"area": "Headline", "issue": "problema attuale", "suggestion": "proposta concreta"}},\n'
            '    {{"area": "About", "issue": "...", "suggestion": "..."}},\n'
            '    {{"area": "Featured", "issue": "...", "suggestion": "..."}}\n'
            '  ],\n'
            '  "content_recommendations": [\n'
            '    {{"priority": 1, "action": "azione concreta", "rationale": "perché funziona con evidenza"}},\n'
            '    {{"priority": 2, "action": "...", "rationale": "..."}},\n'
            '    {{"priority": 3, "action": "...", "rationale": "..."}}\n'
            '  ],\n'
            '  "quick_wins": ["azione rapida da fare oggi 1", "azione rapida 2"]\n'
            "}}\n"
            "Basa le raccomandazioni su best practice reali LinkedIn B2B 2024-2025 e specifiche del niche EU funding."
        )
        system_prompt = self._prompt_template.format(
            user_name=s.user.name,
            user_headline=s.user.headline,
            context=context,
            task=(
                "Analizza il posizionamento LinkedIn di questo professionista nel niche fondi europei/PNRR "
                "e fornisci raccomandazioni concrete e actionable per migliorare la sua presenza e autorevolezza."
            ),
            output_format=output_format,
        )
        try:
            raw = self._llm.generate_with_retry(system_prompt, "Esegui l'analisi del profilo.", max_tokens=1500)
            data = self._llm.parse_json_response_safe(raw)
            if not data:
                raise RuntimeError("Il provider LLM non ha restituito un JSON valido per l'analisi profilo.")
            if snapshot:
                data["analysis_scope"] = {
                    "own_posts_count": snapshot.own_posts_count,
                    "niche_posts_count": snapshot.niche_posts_count,
                    "niche_profiles_count": snapshot.niche_profiles_count,
                    "status": snapshot.status,
                }
                data["context_evidence"] = [
                    f"Profilo reale letto: {bool(snapshot.profile_snapshot)}",
                    f"Post recenti letti: {snapshot.own_posts_count}",
                    f"Post settore letti: {snapshot.niche_posts_count}",
                    f"Profili settore letti: {snapshot.niche_profiles_count}",
                ]
            return data
        except Exception:
            return {
                "positioning_score": 0,
                "score_rationale": "Analisi non disponibile o risposta AI non valida.",
                "strengths": [],
                "gaps": [],
                "opportunities": [],
                "profile_recommendations": [],
                "content_recommendations": [],
                "quick_wins": [],
                "context_evidence": [
                    f"Profilo reale letto: {bool(snapshot.profile_snapshot) if snapshot else False}",
                    f"Post recenti letti: {snapshot.own_posts_count if snapshot else 0}",
                    f"Post settore letti: {snapshot.niche_posts_count if snapshot else 0}",
                    f"Profili settore letti: {snapshot.niche_profiles_count if snapshot else 0}",
                ] if snapshot else [],
            }

    # ------------------------------------------------------------------
    # Niche benchmarking
    # ------------------------------------------------------------------

    def benchmark_niche(self, posts_sample: list) -> str:
        """
        Analyze a sample of top posts in the EU funding niche and extract patterns.
        Returns a formatted string summary for display.
        """
        if not posts_sample:
            return "Nessun dato disponibile per il benchmark del niche."

        sample_text = "\n\n".join(
            f"Post #{i+1} (autore: {p.author_name}, reazioni: {p.reaction_count}):\n{p.text[:300]}"
            for i, p in enumerate(posts_sample[:10])
        )
        context = f"Campione di post ad alto engagement nel niche fondi europei:\n\n{sample_text}"
        output_format = (
            "Testo formattato (no JSON) con sezioni:\n"
            "- FORMATI PIÙ EFFICACI\n"
            "- TEMI CHE GENERANO PIÙ ENGAGEMENT\n"
            "- PATTERN DI HOOK CHE FUNZIONANO\n"
            "- ORARI E GIORNI MIGLIORI (se deducibile)\n"
            "- RACCOMANDAZIONI PER NICCOLÒ\n"
            "Sii sintetico: max 300 parole totali."
        )
        system_prompt = self._prompt_template.format(
            user_name=self._settings.user.name,
            user_headline=self._settings.user.headline,
            context=context,
            task="Analizza questo campione di post ad alto engagement nel niche fondi europei e identifica i pattern di successo.",
            output_format=output_format,
        )
        user_prompt = "Esegui l'analisi del benchmark."

        try:
            return self._claude.generate(system_prompt, user_prompt, max_tokens=600)
        except Exception:
            return "Errore nell'analisi del benchmark."
