"""
Read-only dashboard state used by the observability-focused Streamlit UI.

This module deliberately reads persisted state from SQLite instead of relying
on in-memory Streamlit state so the UI reflects jobs orchestrated by n8n.
"""
from __future__ import annotations

from pathlib import Path

from linkedin_agent.modules.knowledge_store import SectorKnowledgeStore
from linkedin_agent.modules.tracker import ActivityTracker


def load_dashboard_state(db_path: Path) -> dict:
    tracker = ActivityTracker(db_path)
    tracker.init_db()
    store = SectorKnowledgeStore(db_path)
    store.init_db()

    return {
        "knowledge_overview": store.get_overview(),
        "latest_context": tracker.get_latest_context_run(),
        "latest_knowledge_run": store.get_latest_knowledge_run(),
        "latest_delta": store.get_latest_delta(),
        "latest_brief": store.get_latest_brief(),
        "latest_post_generation_run": tracker.get_latest_post_generation_run(),
        "pending": {
            "posts": tracker.get_pending_posts(),
            "comments": tracker.get_pending_comments(),
            "reactions": tracker.get_pending_reactions(),
            "connections": tracker.get_pending_connections(),
        },
        "approved": {
            "posts": tracker.get_approved_posts(),
            "comments": tracker.get_approved_comments(),
            "reactions": tracker.get_approved_reactions(),
            "connections": tracker.get_approved_connections(),
        },
        "progress_report": tracker.export_progress_report(),
        "recent_profiles": tracker.get_recent_seen_profiles(limit=15),
        "recent_own_posts": tracker.get_recent_seen_posts("recent_posts_seen", limit=10),
        "recent_niche_posts": tracker.get_recent_seen_posts("niche_posts_seen", limit=10),
    }
