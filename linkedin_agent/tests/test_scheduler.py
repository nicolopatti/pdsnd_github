"""Tests for DailyScheduler (dry-run mode only, no API calls)."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from linkedin_agent.modules.scheduler import DailyScheduler
from linkedin_agent.modules.tracker import ActivityTracker


def _make_tracker():
    tmp = tempfile.mktemp(suffix=".db")
    tracker = ActivityTracker(Path(tmp))
    tracker.init_db()
    return tracker


def _make_settings():
    from linkedin_agent.config.settings import (
        ActivityConfig,
        ActivityLimits,
        ContentFormat,
        ContentPillar,
        NicheConfig,
        PostingWindow,
        SafetyConfig,
        Settings,
        TargetProfiles,
        UserConfig,
    )
    return Settings(
        user=UserConfig(
            name="Niccolò Patti",
            linkedin_url="https://www.linkedin.com/in/nicol%C3%B2-patti/",
            headline="Consulente Fondi Europei",
            language="it",
            tone="professional_warm",
        ),
        niche=NicheConfig(
            primary_keywords=["fondi europei"],
            hashtags=["#fondieuropei"],
            content_pillars=[ContentPillar(name="Guide pratiche", weight=2)],
            content_formats=[ContentFormat(name="guida_pratica", description="How-to guide", weight=2)],
        ),
        target_profiles=TargetProfiles(job_titles=["Grant Consultant"], industries=[], locations=["Italy"]),
        influencers_to_monitor=[],
        activity=ActivityConfig(
            daily_limits=ActivityLimits(
                posts_per_week=4,
                comments_per_day=5,
                reactions_per_day=10,
                connection_requests_per_day=10,
                profile_views_per_day=20,
            ),
            posting_window=PostingWindow(start_hour=8, end_hour=18),
            best_days_to_post=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            timezone="Europe/Rome",
        ),
        safety=SafetyConfig(
            min_delay_between_actions_seconds=1,
            max_delay_between_actions_seconds=2,
            session_max_actions=15,
            respect_weekends=True,
            headless_browser=True,
        ),
        anthropic_api_key="test",
        linkedin_email="test@test.com",
        linkedin_password="test",
    )


def test_dry_run_plan():
    settings = _make_settings()
    tracker = _make_tracker()
    stub = MagicMock()
    stub.get_daily_engagement_queue.return_value = []
    stub.get_reaction_queue.return_value = []
    stub.get_connection_queue.return_value = []

    scheduler = DailyScheduler(
        settings=settings,
        tracker=tracker,
        content_gen=MagicMock(),
        engagement=stub,
        network=stub,
    )

    plan = scheduler.build_daily_plan(dry_run=True)

    assert plan.post_draft is not None
    assert plan.post_draft.content
    assert len(plan.comments) > 0
    assert len(plan.reactions) > 0
    assert len(plan.connections) > 0
    assert "[DRY RUN]" in plan.notes[0]


def test_should_post_today_limit():
    settings = _make_settings()
    tracker = _make_tracker()
    stub = MagicMock()

    scheduler = DailyScheduler(
        settings=settings, tracker=tracker,
        content_gen=MagicMock(), engagement=stub, network=stub,
    )

    # Simulate 4 posts already published this week
    for _ in range(4):
        from linkedin_agent.modules.tracker import PostDraft
        draft = PostDraft(content="x", hashtags=[], pillar="p", format_type="f")
        pid = tracker.log_post(draft)
        tracker.update_post_status(pid, "approved")

    assert not scheduler.should_post_today("Tuesday")
