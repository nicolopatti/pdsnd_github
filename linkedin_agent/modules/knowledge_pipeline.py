"""
Knowledge-first pipeline: normalize raw LinkedIn context, update the sector
knowledge base, rank opportunities, and build structured content briefs.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass

from linkedin_agent.config.settings import Settings
from linkedin_agent.modules.context_collector import ContextPost, ContextProfile, ContextSnapshot
from linkedin_agent.modules.knowledge_store import SectorKnowledgeStore
from linkedin_agent.modules.knowledge_types import (
    CommentOpportunityReport,
    ContentBrief,
    DailyDelta,
    MarketPattern,
    NormalizedPost,
    NormalizedProfile,
    OpportunityExclusion,
    ProfileOpportunityReport,
    RankedPost,
    RankedProfile,
    RetrievedPost,
    RetrievedProfile,
    SectorSignal,
)

_STOPWORDS = {
    "il", "lo", "la", "i", "gli", "le", "un", "una", "per", "con", "che",
    "del", "dei", "delle", "della", "dello", "nel", "nella", "nelle", "su",
    "da", "di", "in", "e", "o", "a", "al", "ai", "agli", "alle", "gli", "si",
    "ma", "non", "piu", "più", "come", "sono", "una", "uno", "dei", "the",
}


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _market_scope_from_text(text: str, fallback: str = "italy") -> str:
    lowered = (text or "").lower()
    if any(token in lowered for token in ["pnrr", "italia", "italian", "regione", "terzo settore"]):
        return "italy"
    if any(token in lowered for token in ["european", "europe", "horizon europe", "grant agreement", "eu funding"]):
        return "international"
    return fallback


def _extract_topic_labels(text: str) -> list[str]:
    lowered = (text or "").lower()
    labels: list[str] = []
    mapping = {
        "pnrr": ["pnrr", "missione", "m1", "m2", "m5"],
        "bandi": ["bando", "call", "application", "avviso"],
        "requisiti": ["requisiti", "eligibility", "ammissibil", "criteri"],
        "scadenze": ["scadenza", "deadline", "termine"],
        "partnership": ["partner", "partnership", "consorzio"],
        "rendicontazione": ["rendicontazione", "reporting", "audit"],
        "digitalizzazione": ["digit", "digital", "innovazione"],
        "terzo_settore": ["terzo settore", "non profit", "ets", "sociale"],
    }
    for label, tokens in mapping.items():
        if any(token in lowered for token in tokens):
            labels.append(label)
    return labels or ["fondi_europei"]


def _extract_role_labels(headline: str, summary: str) -> list[str]:
    lowered = f"{headline} {summary}".lower()
    labels: list[str] = []
    mapping = {
        "consultant": ["consul", "advisor", "consultant"],
        "grant_writer": ["grant", "europrogett", "proposal"],
        "nonprofit": ["terzo settore", "non profit", "ets", "ngo"],
        "innovation": ["innovation", "innovazione", "digital"],
        "public_sector": ["public", "ente", "municip", "comune", "regione"],
    }
    for label, tokens in mapping.items():
        if any(token in lowered for token in tokens):
            labels.append(label)
    return labels or ["sector_profile"]


class SectorAnalyzer:
    def __init__(self, settings: Settings, store: SectorKnowledgeStore) -> None:
        self._settings = settings
        self._store = store

    def bootstrap_from_snapshot(self, snapshot: ContextSnapshot, run_kind: str = "bootstrap") -> DailyDelta:
        return self._ingest_snapshot(snapshot, run_kind=run_kind)

    def ingest_daily_snapshot(self, snapshot: ContextSnapshot) -> DailyDelta:
        return self._ingest_snapshot(snapshot, run_kind="daily_incremental")

    def _ingest_snapshot(self, snapshot: ContextSnapshot, run_kind: str) -> DailyDelta:
        delta = DailyDelta(snapshot_id=snapshot.snapshot_id)
        normalized_posts = [self._normalize_post(item) for item in snapshot.niche_posts_snapshot]
        normalized_profiles = [self._normalize_profile(item) for item in snapshot.niche_profiles_snapshot]

        for post in normalized_posts:
            self._store.upsert_sector_post(post)
        for profile in normalized_profiles:
            self._store.upsert_sector_profile(profile)

        signals = self._derive_signals(normalized_posts)
        patterns = self._derive_patterns(normalized_posts)
        for signal in signals:
            self._store.upsert_signal(signal)
        for pattern in patterns:
            self._store.upsert_pattern(pattern)

        delta.new_posts = len(normalized_posts)
        delta.new_profiles = len(normalized_profiles)
        delta.signals_emerged = len(signals)
        delta.notes.append(f"Knowledge update `{run_kind}` completato.")

        summary = {
            "snapshot_id": snapshot.snapshot_id,
            "posts_ingested": len(normalized_posts),
            "profiles_ingested": len(normalized_profiles),
            "signals_emerged": len(signals),
            "patterns_updated": len(patterns),
        }
        self._store.log_knowledge_run(run_kind, "italy", "ok", summary)
        self._store.log_daily_delta(delta)
        return delta

    def _normalize_post(self, item: ContextPost) -> NormalizedPost:
        cleaned = _clean_text(item.text)
        labels = _extract_topic_labels(cleaned)
        engagement = item.reaction_count + item.comment_count * 2
        importance = min(1.0, engagement / 40) + min(len(labels) * 0.08, 0.24)
        return NormalizedPost(
            urn=item.urn,
            url=item.url,
            author_name=item.author_name,
            author_headline=item.author_headline,
            text=cleaned,
            normalized_text=cleaned.lower(),
            reaction_count=item.reaction_count,
            comment_count=item.comment_count,
            source_query=item.source_query,
            market_scope=_market_scope_from_text(f"{cleaned} {item.source_query}"),
            language="it" if any(tok in cleaned.lower() for tok in [" il ", " la ", " per ", " con "]) else "en",
            importance_score=round(importance, 3),
            topic_labels=labels,
        )

    def _normalize_profile(self, item: ContextProfile) -> NormalizedProfile:
        summary = _clean_text(item.summary)
        headline = _clean_text(item.headline)
        role_labels = _extract_role_labels(headline, summary)
        relevance = min(1.0, 0.35 + len(role_labels) * 0.08 + (0.1 if item.location else 0))
        return NormalizedProfile(
            urn=item.profile_urn,
            full_name=item.full_name,
            headline=headline,
            location=item.location,
            summary=summary,
            current_company=item.current_company,
            profile_url=item.profile_url,
            source_query=item.source_query,
            market_scope=_market_scope_from_text(f"{headline} {summary}", fallback="italy"),
            role_labels=role_labels,
            relevance_score=round(relevance, 3),
        )

    def _derive_signals(self, posts: list[NormalizedPost]) -> list[SectorSignal]:
        counter: Counter[str] = Counter()
        evidence: dict[str, list[str]] = {}
        for post in posts:
            for label in post.topic_labels:
                counter[label] += 1
                evidence.setdefault(label, []).append(f"{post.author_name}: {post.text[:120]}...")

        signals: list[SectorSignal] = []
        for label, count in counter.most_common(8):
            signals.append(
                SectorSignal(
                    signal_type="topic",
                    signal_key=f"topic_{label}",
                    label=label.replace("_", " "),
                    evidence=evidence.get(label, [])[:3],
                    strength_score=round(min(1.0, count / 4), 3),
                )
            )
        return signals

    def _derive_patterns(self, posts: list[NormalizedPost]) -> list[MarketPattern]:
        patterns: list[MarketPattern] = []
        if not posts:
            return patterns

        frequent_topics = Counter(topic for post in posts for topic in post.topic_labels)
        for topic, count in frequent_topics.most_common(4):
            matching = [post for post in posts if topic in post.topic_labels][:3]
            patterns.append(
                MarketPattern(
                    pattern_key=f"pattern_{topic}",
                    label=f"Pattern su {topic.replace('_', ' ')}",
                    summary=f"Nel settore ricorre spesso il tema {topic.replace('_', ' ')} con focus operativo.",
                    evidence=[f"{post.author_name}: {post.text[:100]}..." for post in matching],
                    score=round(min(1.0, count / 4), 3),
                )
            )
        return patterns


class SignalRanker:
    def __init__(self, settings: Settings, store: SectorKnowledgeStore) -> None:
        self._settings = settings
        self._store = store

    def rank_posts_for_today(self, limit: int = 20) -> list[RankedPost]:
        ranked: list[RankedPost] = []
        for row in self._store.get_top_sector_posts(limit=limit):
            text = row["normalized_text"] or ""
            reasons: list[str] = []
            keyword_hits = sum(1 for kw in self._settings.niche.primary_keywords if kw.lower() in text)
            if keyword_hits:
                reasons.append(f"match keyword {keyword_hits}")
            if row["reaction_count"] >= 8:
                reasons.append("engagement sopra soglia")
            if row["comment_count"] >= 2:
                reasons.append("discussione gia' attiva")
            passed_prefilter = bool(reasons)
            if not passed_prefilter:
                reasons.append("nessun segnale minimo rilevato")
            base_score = row.get("ranking_score", row["importance_score"])
            score = min(1.0, base_score + keyword_hits * 0.08)
            decision = "comment" if score >= 0.58 else "react" if score >= 0.42 else "ignore"
            if decision == "ignore":
                reasons.append("troppo debole per una conversazione utile")
            ranked.append(
                RankedPost(
                    urn=row["post_urn"],
                    author_name=row["author_name"] or "Autore LinkedIn",
                    text_snippet=(row["text_raw"] or "")[:180],
                    post_url=row["post_url"] or "",
                    score=round(score, 3),
                    decision=decision,
                    reasons=reasons or ["segnale presente ma debole"],
                    source_query=row["source_query"] or "",
                    market_scope=row["market_scope"] or "italy",
                    passed_prefilter=passed_prefilter,
                )
            )
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked

    def rank_profiles_for_today(self, limit: int = 20) -> list[RankedProfile]:
        ranked: list[RankedProfile] = []
        target_titles = " ".join(self._settings.target_profiles.job_titles).lower()
        for row in self._store.get_top_sector_profiles(limit=limit):
            headline = (row["headline"] or "").lower()
            reasons: list[str] = []
            title_overlap = 1 if any(tok in headline for tok in target_titles.split()) else 0
            if title_overlap:
                reasons.append("headline allineata al target")
            if row["market_scope"] == "italy":
                reasons.append("mercato principale")
            if row["location"]:
                reasons.append("location leggibile")
            passed_prefilter = bool(reasons)
            if not passed_prefilter:
                reasons.append("nessun segnale minimo rilevato")
            base_score = row.get("ranking_score", row["relevance_score"] or 0.0)
            score = min(1.0, base_score + title_overlap * 0.15)
            decision = "connect" if score >= 0.55 else "ignore"
            if decision == "ignore":
                reasons.append("profilo poco differenziante")
            ranked.append(
                RankedProfile(
                    urn=row["profile_urn"],
                    full_name=row["full_name"] or row["profile_urn"],
                    headline=row["headline"] or "",
                    profile_url=row["profile_url"] or "",
                    score=round(score, 3),
                    decision=decision,
                    reasons=reasons or ["profilo letto ma non prioritario"],
                    market_scope=row["market_scope"] or "italy",
                    passed_prefilter=passed_prefilter,
                )
            )
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked


class CommentOpportunityRanker:
    def build(self, ranked_posts: list[RankedPost], limit: int = 5, posts_read: int | None = None) -> tuple[list[RankedPost], CommentOpportunityReport]:
        selected = [post for post in ranked_posts if post.passed_prefilter and post.decision == "comment"][:limit]
        excluded = [
            OpportunityExclusion(
                urn=post.urn,
                label=post.author_name,
                score=post.score,
                decision=post.decision,
                reasons=post.reasons,
            )
            for post in ranked_posts
            if post.passed_prefilter and post.decision != "comment"
        ]
        report = CommentOpportunityReport(
            posts_read=posts_read if posts_read is not None else len(ranked_posts),
            posts_filtered=sum(1 for post in ranked_posts if post.passed_prefilter),
            posts_ranked=len(ranked_posts),
            comment_candidates=len(selected),
            excluded_final=excluded[:12],
        )
        return selected, report


class ProfileOpportunityRanker:
    def build(self, ranked_profiles: list[RankedProfile], limit: int = 5, profiles_read: int | None = None) -> tuple[list[RankedProfile], ProfileOpportunityReport]:
        selected = [profile for profile in ranked_profiles if profile.passed_prefilter and profile.decision == "connect"][:limit]
        excluded = [
            OpportunityExclusion(
                urn=profile.urn,
                label=profile.full_name,
                score=profile.score,
                decision=profile.decision,
                reasons=profile.reasons,
            )
            for profile in ranked_profiles
            if profile.passed_prefilter and profile.decision != "connect"
        ]
        report = ProfileOpportunityReport(
            profiles_read=profiles_read if profiles_read is not None else len(ranked_profiles),
            profiles_filtered=sum(1 for profile in ranked_profiles if profile.passed_prefilter),
            profiles_ranked=len(ranked_profiles),
            connection_candidates=len(selected),
            excluded_final=excluded[:12],
        )
        return selected, report


class ContentBriefBuilder:
    def __init__(self, settings: Settings, store: SectorKnowledgeStore) -> None:
        self._settings = settings
        self._store = store

    def build(self, snapshot: ContextSnapshot | None) -> ContentBrief | None:
        if not snapshot or snapshot.status != "sufficient":
            return None

        top_signals = self._store.get_top_signals(limit=4)
        top_patterns = self._store.get_top_patterns(limit=2)
        top_posts = self._store.get_top_sector_posts(limit=3)
        if not top_signals and not top_posts:
            return None

        signal_label = top_signals[0]["label"] if top_signals else "problemi ricorrenti nei bandi"
        pattern_summary = top_patterns[0]["summary"] if top_patterns else "Checklist pratica da contesto reale"
        points: list[str] = []
        sources: list[str] = []

        for row in top_posts[:3]:
            points.append(f"Osservazione: {row['author_name']} insiste su {(row['source_query'] or row['market_scope'])}.")
            sources.append(f"Post settore: {row['author_name']} · {(row['text_raw'] or '')[:110]}...")
        for signal in top_signals[:3]:
            points.append(f"Segnale settore: {signal['label']} con forza {signal['strength_score']}.")
            evidence = json_loads(signal["evidence_json"])
            sources.extend(evidence[:1])

        target_reader = ", ".join(self._settings.target_profiles.job_titles[:2]) or "professionisti dei fondi europei"
        recommended_cta = "Commenta se vuoi una checklist pratica applicabile ai tuoi bandi."
        return ContentBrief(
            snapshot_id=snapshot.snapshot_id,
            angle_label=f"Angolo su {signal_label}",
            selected_pattern=pattern_summary,
            target_reader=target_reader,
            recommended_cta=recommended_cta,
            supporting_points=points[:5],
            context_sources=sources[:5],
            notes=["Brief costruito dalla knowledge base e dal delta giornaliero."],
        )


def json_loads(text: str) -> list[str]:
    try:
        data = json.loads(text)  # type: ignore[name-defined]
    except Exception:
        return []
    return data if isinstance(data, list) else []
