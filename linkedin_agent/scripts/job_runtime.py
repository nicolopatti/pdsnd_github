"""
Runtime helpers shared by the n8n-friendly CLI jobs.
"""
from __future__ import annotations

import logging
from pathlib import Path

from linkedin_agent.automation.browser import BrowserSession
from linkedin_agent.automation.browser_reader import BrowserLinkedInReader, OwnProfileSnapshot
from linkedin_agent.config.settings import Settings, load_settings
from linkedin_agent.core.provider_factory import create_llm_provider
from linkedin_agent.modules.context_collector import ContextCollector, ContextPost, ContextProfile, ContextSnapshot
from linkedin_agent.modules.knowledge_pipeline import ContentBriefBuilder, SectorAnalyzer
from linkedin_agent.modules.knowledge_store import SectorKnowledgeStore
from linkedin_agent.modules.knowledge_types import ContentBrief
from linkedin_agent.modules.tracker import ActivityTracker
from linkedin_agent.scripts.cli_common import RecoverableCLIError


def load_core_runtime(require_llm: bool = False):
    settings = load_settings(validate_llm=require_llm)
    db_path = settings.data_dir / "activity_log.db"
    tracker = ActivityTracker(db_path)
    tracker.init_db()
    store = SectorKnowledgeStore(db_path)
    store.init_db()
    llm = create_llm_provider(settings) if require_llm else None
    return settings, tracker, store, llm


def ensure_browser_session(settings: Settings) -> str:
    browser_ok, browser_detail = BrowserSession.probe_saved_session(settings)
    if not browser_ok:
        raise RecoverableCLIError(f"Sessione browser non valida: {browser_detail}")
    return browser_detail


def collect_context(settings: Settings, tracker: ActivityTracker, logger: logging.Logger) -> ContextSnapshot:
    logger.info("Avvio raccolta contesto LinkedIn via Playwright")
    collector = ContextCollector(settings, tracker, BrowserLinkedInReader(settings))
    snapshot = collector.collect_daily_context()
    logger.info(
        "Contesto raccolto: profilo=%s tuoi_post=%s post_settore=%s profili_settore=%s",
        bool(snapshot.profile_snapshot),
        snapshot.own_posts_count,
        snapshot.niche_posts_count,
        snapshot.niche_profiles_count,
    )
    return snapshot


def ingest_snapshot(
    settings: Settings,
    store: SectorKnowledgeStore,
    snapshot: ContextSnapshot,
    run_kind: str,
):
    analyzer = SectorAnalyzer(settings, store)
    if run_kind == "bootstrap":
        delta = analyzer.bootstrap_from_snapshot(snapshot, run_kind="bootstrap")
    else:
        delta = analyzer.ingest_daily_snapshot(snapshot)
    overview = store.get_overview()
    return delta, overview


def build_brief_from_snapshot(
    settings: Settings,
    store: SectorKnowledgeStore,
    snapshot: ContextSnapshot,
) -> tuple[ContentBrief, int]:
    builder = ContentBriefBuilder(settings, store)
    brief = builder.build(snapshot)
    if not brief:
        raise RecoverableCLIError("Nessun content brief disponibile per lo snapshot corrente.")
    brief_id = store.save_content_brief(brief)
    return brief, brief_id


def persist_snapshot(tracker: ActivityTracker, snapshot: ContextSnapshot, run_kind: str = "daily_plan") -> int:
    if snapshot.profile_snapshot:
        tracker.log_profile_snapshot(snapshot.profile_snapshot)
    for post in snapshot.recent_posts_snapshot:
        tracker.log_recent_post_seen(post)
    for post in snapshot.niche_posts_snapshot:
        tracker.log_niche_post_seen(post)
    for profile in snapshot.niche_profiles_snapshot:
        tracker.mark_profile_seen(
            profile.profile_urn,
            score=0.0,
            full_name=profile.full_name,
            headline=profile.headline,
            profile_url=profile.profile_url,
        )
    snapshot.snapshot_id = tracker.log_context_run(snapshot, run_kind=run_kind)
    return snapshot.snapshot_id


def load_latest_snapshot(tracker: ActivityTracker) -> ContextSnapshot:
    latest = tracker.get_latest_context_run()
    if not latest:
        raise RecoverableCLIError("Nessuno snapshot di contesto disponibile nel database.")

    summary = latest["summary"]
    profile_data = summary.get("profile_snapshot")
    profile = OwnProfileSnapshot(**profile_data) if profile_data else None
    recent_posts = [ContextPost(**item) for item in summary.get("recent_posts_snapshot", [])]
    niche_posts = [ContextPost(**item) for item in summary.get("niche_posts_snapshot", [])]
    niche_profiles = [ContextProfile(**item) for item in summary.get("niche_profiles_snapshot", [])]

    return ContextSnapshot(
        created_at=summary.get("created_at", latest["created_at"]),
        snapshot_id=summary.get("snapshot_id") or latest["id"],
        profile_snapshot=profile,
        recent_posts_snapshot=recent_posts,
        niche_posts_snapshot=niche_posts,
        niche_profiles_snapshot=niche_profiles,
        status=summary.get("status", latest["status"]),
        notes=summary.get("notes", latest.get("notes", [])),
    )


def snapshot_to_payload(snapshot: ContextSnapshot) -> dict:
    return snapshot.to_dict()


def payload_to_snapshot(payload: dict) -> ContextSnapshot:
    profile_data = payload.get("profile_snapshot")
    profile = OwnProfileSnapshot(**profile_data) if profile_data else None
    recent_posts = [ContextPost(**item) for item in payload.get("recent_posts_snapshot", [])]
    niche_posts = [ContextPost(**item) for item in payload.get("niche_posts_snapshot", [])]
    niche_profiles = [ContextProfile(**item) for item in payload.get("niche_profiles_snapshot", [])]
    return ContextSnapshot(
        created_at=payload.get("created_at", ""),
        snapshot_id=payload.get("snapshot_id"),
        profile_snapshot=profile,
        recent_posts_snapshot=recent_posts,
        niche_posts_snapshot=niche_posts,
        niche_profiles_snapshot=niche_profiles,
        status=payload.get("status", "insufficient"),
        notes=payload.get("notes", []),
    )
