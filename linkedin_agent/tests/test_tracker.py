"""Tests for ActivityTracker."""
from __future__ import annotations

import tempfile
from pathlib import Path

from linkedin_agent.modules.tracker import (
    ActivityTracker,
    CommentDraft,
    ConnectionRequest,
    PostDraft,
    ReactionItem,
)


def make_tracker() -> ActivityTracker:
    tmp = tempfile.mktemp(suffix=".db")
    tracker = ActivityTracker(Path(tmp))
    tracker.init_db()
    return tracker


def test_post_lifecycle():
    tracker = make_tracker()
    draft = PostDraft(content="Test post", hashtags=["#test"], pillar="Guide", format_type="guida_pratica")
    post_id = tracker.log_post(draft)
    assert post_id is not None

    pending = tracker.get_pending_posts()
    assert any(p.id == post_id for p in pending)

    tracker.update_post_status(post_id, "approved")
    approved = tracker.get_approved_posts()
    assert any(p.id == post_id for p in approved)

    tracker.mark_post_published(post_id, "urn:li:activity:12345")
    published = tracker.get_published_posts()
    assert any(p.id == post_id for p in published)
    assert tracker.get_weekly_post_count() >= 1


def test_comment_lifecycle():
    tracker = make_tracker()
    draft = CommentDraft(
        post_urn="urn:li:activity:999",
        post_url="https://linkedin.com/post/999",
        post_author="Mario",
        post_text_snippet="Test post text",
        comment_text="My comment",
        relevance_score=0.85,
    )
    comment_id = tracker.log_comment(draft)
    assert comment_id is not None

    tracker.update_comment_status(comment_id, "approved")
    tracker.mark_comment_published(comment_id)
    assert tracker.get_daily_comment_count() >= 1


def test_deduplication():
    tracker = make_tracker()
    tracker.mark_post_seen("urn:li:activity:001", 0.9)
    assert tracker.is_post_seen("urn:li:activity:001")
    assert not tracker.is_post_seen("urn:li:activity:002")

    tracker.mark_profile_seen("urn:li:fs_profile:ABC", 0.7)
    assert tracker.is_profile_seen("urn:li:fs_profile:ABC")
    assert not tracker.is_profile_seen("urn:li:fs_profile:XYZ")


def test_progress_report():
    tracker = make_tracker()
    report = tracker.export_progress_report()
    assert "all_time" in report
    assert "today" in report
    assert "this_week" in report


def test_post_generation_run_logging():
    tracker = make_tracker()
    run_id = tracker.log_post_generation_run(
        snapshot_id=12,
        model="gemini-test",
        status="invalid_ai_output",
        error_message="Bad JSON",
        raw_excerpt="{",
        validation_errors=["Missing content"],
    )
    assert run_id is not None

    latest = tracker.get_latest_post_generation_run()
    assert latest is not None
    assert latest["status"] == "invalid_ai_output"
    assert latest["model"] == "gemini-test"
    assert latest["validation_errors"] == ["Missing content"]
