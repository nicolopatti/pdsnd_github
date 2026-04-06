import json
from types import SimpleNamespace

from linkedin_agent.modules.context_collector import ContextSnapshot
from linkedin_agent.modules.knowledge_types import ContentBrief
from linkedin_agent.scripts import build_daily_brief, daily_refresh_knowledge, generate_post_variants


class _DummyTracker:
    pass


class _DummyStore:
    pass


class _DummySettings:
    pass


def test_build_daily_brief_outputs_structured_json(monkeypatch, capsys):
    snapshot = ContextSnapshot(created_at="2026-04-01T10:00:00", snapshot_id=12, status="sufficient")
    brief = ContentBrief(
        snapshot_id=12,
        angle_label="Angolo su scadenze",
        selected_pattern="Checklist pratica",
        target_reader="Grant consultant",
        recommended_cta="Scrivimi per la checklist.",
        supporting_points=["Punto 1", "Punto 2"],
        context_sources=["Fonte 1", "Fonte 2"],
        notes=["Brief test"],
    )

    monkeypatch.setattr(
        build_daily_brief,
        "load_core_runtime",
        lambda require_llm=False: (_DummySettings(), _DummyTracker(), _DummyStore(), None),
    )
    monkeypatch.setattr(build_daily_brief, "load_latest_snapshot", lambda tracker: snapshot)
    monkeypatch.setattr(build_daily_brief, "build_brief_from_snapshot", lambda settings, store, snap: (brief, 99))

    exit_code = build_daily_brief.main([])

    assert exit_code == 0
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["status"] == "ok"
    assert payload["command"] == "build_daily_brief"
    assert payload["summary"]["brief_id"] == 99
    assert payload["summary"]["snapshot_id"] == 12


def test_build_daily_brief_returns_recoverable_error(monkeypatch, capsys):
    monkeypatch.setattr(
        build_daily_brief,
        "load_core_runtime",
        lambda require_llm=False: (_DummySettings(), _DummyTracker(), _DummyStore(), None),
    )
    monkeypatch.setattr(build_daily_brief, "load_latest_snapshot", lambda tracker: ContextSnapshot(created_at="x", snapshot_id=1, status="insufficient"))

    exit_code = build_daily_brief.main([])

    assert exit_code == 1
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["status"] == "recoverable_error"
    assert payload["command"] == "build_daily_brief"


def test_daily_refresh_outputs_comment_report(monkeypatch, capsys):
    class _DummySignalRanker:
        def __init__(self, settings, store):
            pass

        def rank_posts_for_today(self, limit=20):
            return []

        def rank_profiles_for_today(self, limit=20):
            return []

    class _DummyCommentRanker:
        def build(self, ranked_posts, limit=5, posts_read=None):
            from linkedin_agent.modules.knowledge_types import CommentOpportunityReport
            return [], CommentOpportunityReport(
                posts_read=4,
                posts_filtered=2,
                posts_ranked=2,
                comment_candidates=0,
            )

    class _DummyProfileRanker:
        def build(self, ranked_profiles, limit=5, profiles_read=None):
            from linkedin_agent.modules.knowledge_types import ProfileOpportunityReport
            return [], ProfileOpportunityReport(
                profiles_read=3,
                profiles_filtered=1,
                profiles_ranked=1,
                connection_candidates=0,
            )

    snapshot = ContextSnapshot(created_at="2026-04-01T10:00:00", snapshot_id=22, status="sufficient")
    snapshot.niche_posts_snapshot = [object(), object(), object(), object()]
    snapshot.niche_profiles_snapshot = [object(), object(), object()]

    class _Delta:
        comment_candidates = 0
        connection_candidates = 0
        skipped_posts = []
        skipped_profiles = []

        def to_dict(self):
            return {
                "comment_candidates": self.comment_candidates,
                "connection_candidates": self.connection_candidates,
                "skipped_posts": self.skipped_posts,
                "skipped_profiles": self.skipped_profiles,
            }

    monkeypatch.setattr(
        daily_refresh_knowledge,
        "load_core_runtime",
        lambda require_llm=False: (_DummySettings(), _DummyTracker(), _DummyStore(), None),
    )
    monkeypatch.setattr(daily_refresh_knowledge, "ensure_browser_session", lambda settings: "ok")
    monkeypatch.setattr(daily_refresh_knowledge, "collect_context", lambda settings, tracker, logger: snapshot)
    monkeypatch.setattr(daily_refresh_knowledge, "ingest_snapshot", lambda settings, store, snapshot, run_kind: (_Delta(), {"sector_posts": 3}))
    monkeypatch.setattr(daily_refresh_knowledge, "SignalRanker", _DummySignalRanker)
    monkeypatch.setattr(daily_refresh_knowledge, "CommentOpportunityRanker", _DummyCommentRanker)
    monkeypatch.setattr(daily_refresh_knowledge, "ProfileOpportunityRanker", _DummyProfileRanker)

    exit_code = daily_refresh_knowledge.main([])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["summary"]["ranking"]["comment_report"]["posts_read"] == 4
    assert payload["summary"]["ranking"]["comment_report"]["comment_candidates"] == 0


def test_generate_post_variants_outputs_structured_json_and_uses_explicit_brief(monkeypatch, capsys):
    brief = ContentBrief(
        snapshot_id=31,
        angle_label="Angolo operativo",
        selected_pattern="Checklist",
        target_reader="Grant consultant",
        recommended_cta="Scrivimi per la checklist.",
        supporting_points=["Punto 1", "Punto 2"],
        context_sources=["Fonte 1", "Fonte 2"],
        notes=["Brief test"],
    )

    class _Store:
        def get_brief(self, brief_id):
            assert brief_id == 77
            return {"id": 77, "brief": brief.to_dict()}

        def get_latest_brief(self):
            raise AssertionError("Non dovrebbe usare l'ultimo brief quando brief_id e esplicito.")

    class _Tracker:
        def __init__(self):
            self.saved = []

        def log_post(self, draft):
            self.saved.append(draft)
            return len(self.saved)

    class _Generator:
        def __init__(self, settings, llm, tracker):
            pass

        def generate_post_variants(self, brief, count):
            assert brief.snapshot_id == 31
            assert count == 3
            return SimpleNamespace(
                variants=[
                    SimpleNamespace(
                        angle_label="Variante 1",
                        content="Testo variante 1",
                        hashtags=["#uno"],
                        rationale="Razionale 1",
                        context_sources=["Fonte 1"],
                        editorial_score=0.8,
                    ),
                    SimpleNamespace(
                        angle_label="Variante 2",
                        content="Testo variante 2",
                        hashtags=["#due"],
                        rationale="Razionale 2",
                        context_sources=["Fonte 2"],
                        editorial_score=0.7,
                    ),
                ],
                brief=brief,
            )

    tracker = _Tracker()
    monkeypatch.setattr(
        generate_post_variants,
        "load_core_runtime",
        lambda require_llm=True: (_DummySettings(), tracker, _Store(), object()),
    )
    monkeypatch.setattr(generate_post_variants, "ContentGenerator", _Generator)

    exit_code = generate_post_variants.main(["--brief-id", "77", "--variants", "3"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["command"] == "generate_post_variants"
    assert payload["summary"]["brief_id"] == 77
    assert payload["summary"]["generated_variants"] == 2
    assert payload["summary"]["saved_post_ids"] == [1, 2]


def test_generate_post_variants_returns_recoverable_error_when_too_few_variants(monkeypatch, capsys):
    brief = ContentBrief(
        snapshot_id=31,
        angle_label="Angolo operativo",
        selected_pattern="Checklist",
        target_reader="Grant consultant",
        recommended_cta="Scrivimi per la checklist.",
        supporting_points=["Punto 1"],
        context_sources=["Fonte 1"],
        notes=["Brief test"],
    )

    class _Store:
        def get_brief(self, brief_id):
            return {"id": brief_id, "brief": brief.to_dict()}

    class _Generator:
        def __init__(self, settings, llm, tracker):
            pass

        def generate_post_variants(self, brief, count):
            return SimpleNamespace(
                variants=[
                    SimpleNamespace(
                        angle_label="Variante 1",
                        content="Solo una variante",
                        hashtags=["#uno"],
                        rationale="Razionale",
                        context_sources=["Fonte 1"],
                        editorial_score=0.6,
                    )
                ],
                brief=brief,
            )

    monkeypatch.setattr(
        generate_post_variants,
        "load_core_runtime",
        lambda require_llm=True: (_DummySettings(), _DummyTracker(), _Store(), object()),
    )
    monkeypatch.setattr(generate_post_variants, "ContentGenerator", _Generator)

    exit_code = generate_post_variants.main(["--brief-id", "12", "--variants", "3"])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["status"] == "recoverable_error"
    assert payload["command"] == "generate_post_variants"
