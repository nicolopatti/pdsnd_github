from linkedin_agent.modules.dashboard_state import load_dashboard_state
from linkedin_agent.modules.knowledge_store import SectorKnowledgeStore
from linkedin_agent.modules.knowledge_types import ContentBrief, DailyDelta
from linkedin_agent.modules.tracker import (
    ActivityTracker,
    CommentDraft,
    ConnectionRequest,
    PostDraft,
    ReactionItem,
)


def test_load_dashboard_state_reads_persisted_review_queues(tmp_path):
    db_path = tmp_path / "activity_log.db"
    tracker = ActivityTracker(db_path)
    tracker.init_db()
    store = SectorKnowledgeStore(db_path)
    store.init_db()

    tracker.log_post(PostDraft(content="Bozza", hashtags=["#uno"], pillar="pillar", format_type="fmt"))
    comment_id = tracker.log_comment(
        CommentDraft(
            post_urn="urn:1",
            post_url="https://linkedin.com/posts/1",
            post_author="Autore",
            post_text_snippet="Snippet",
            comment_text="Commento",
            relevance_score=0.7,
        )
    )
    tracker.update_comment_status(comment_id, "approved")
    tracker.log_reaction(
        ReactionItem(
            post_urn="urn:2",
            post_url="https://linkedin.com/posts/2",
            post_author="Autore 2",
            post_text_snippet="Snippet 2",
            reaction_type="like",
            motivation="Motivo",
        )
    )
    tracker.log_connection(
        ConnectionRequest(
            profile_urn="urn:profile:1",
            full_name="Nome Profilo",
            headline="Headline",
            profile_url="https://linkedin.com/in/test",
            relevance_score=0.8,
            motivation="Match rilevante",
        )
    )

    brief = ContentBrief(
        snapshot_id=10,
        angle_label="Angolo test",
        selected_pattern="Checklist",
        target_reader="Grant consultant",
        recommended_cta="Scrivimi.",
        supporting_points=["Punto 1", "Punto 2"],
        context_sources=["Fonte 1"],
        notes=["Nota"],
    )
    store.save_content_brief(brief)
    store.log_daily_delta(DailyDelta(snapshot_id=10, new_posts=2, new_profiles=1, signals_emerged=1))

    state = load_dashboard_state(db_path)

    assert state["knowledge_overview"]["content_briefs"] == 1
    assert len(state["pending"]["posts"]) == 1
    assert len(state["approved"]["comments"]) == 1
    assert len(state["pending"]["reactions"]) == 1
    assert len(state["pending"]["connections"]) == 1
    assert state["latest_brief"]["angle_label"] == "Angolo test"
    assert state["latest_delta"]["delta"]["new_posts"] == 2
