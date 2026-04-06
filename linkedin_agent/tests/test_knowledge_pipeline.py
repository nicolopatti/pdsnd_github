import tempfile
from pathlib import Path

from linkedin_agent.modules.context_collector import ContextPost, ContextProfile, ContextSnapshot
from linkedin_agent.modules.knowledge_pipeline import (
    CommentOpportunityRanker,
    ContentBriefBuilder,
    SectorAnalyzer,
    SignalRanker,
)
from linkedin_agent.modules.knowledge_store import SectorKnowledgeStore


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
            primary_keywords=["fondi europei", "pnrr", "terzo settore"],
            hashtags=["#fondieuropei", "#pnrr", "#terzosettore"],
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
            best_days_to_post=["Monday"],
            timezone="Europe/Rome",
        ),
        safety=SafetyConfig(
            min_delay_between_actions_seconds=1,
            max_delay_between_actions_seconds=2,
            session_max_actions=15,
            respect_weekends=True,
            headless_browser=True,
        ),
        gemini_api_key="test",
        linkedin_email="test@test.com",
        linkedin_password="test",
    )


def _make_store():
    tmp = tempfile.mktemp(suffix=".db")
    store = SectorKnowledgeStore(Path(tmp))
    store.init_db()
    return store


def test_sector_analyzer_persists_posts_profiles_signals():
    store = _make_store()
    analyzer = SectorAnalyzer(_make_settings(), store)
    snapshot = ContextSnapshot(
        created_at="2026-04-01T20:00:00",
        snapshot_id=7,
        status="sufficient",
        niche_posts_snapshot=[
            ContextPost(
                urn="urn:p1",
                url="https://www.linkedin.com/feed/update/urn:p1/",
                author_name="Mario Rossi",
                author_headline="Esperto PNRR",
                text="Molti enti del terzo settore sbagliano i requisiti nei bandi PNRR.",
                reaction_count=12,
                comment_count=4,
                source_query="PNRR",
            )
        ],
        niche_profiles_snapshot=[
            ContextProfile(
                profile_urn="urn:pr1",
                full_name="Laura Bianchi",
                headline="Grant Consultant per il terzo settore",
                location="Italy",
                summary="Supporto bandi europei e PNRR",
                current_company="Studio X",
                profile_url="https://www.linkedin.com/in/laura/",
            )
        ],
    )

    delta = analyzer.ingest_daily_snapshot(snapshot)
    overview = store.get_overview()

    assert delta.new_posts == 1
    assert delta.new_profiles == 1
    assert overview["sector_posts"] == 1
    assert overview["sector_profiles"] == 1
    assert overview["sector_signals"] >= 1


def test_content_brief_builder_uses_knowledge_store():
    store = _make_store()
    settings = _make_settings()
    analyzer = SectorAnalyzer(settings, store)
    snapshot = ContextSnapshot(
        created_at="2026-04-01T20:00:00",
        snapshot_id=9,
        status="sufficient",
        niche_posts_snapshot=[
            ContextPost(
                urn="urn:p2",
                url="https://www.linkedin.com/feed/update/urn:p2/",
                author_name="Anna Verdi",
                author_headline="Project Manager",
                text="Scadenze, requisiti e partner sono i tre punti che bloccano piu' spesso i bandi UE.",
                reaction_count=14,
                comment_count=5,
                source_query="bandi UE",
            )
        ],
    )
    analyzer.ingest_daily_snapshot(snapshot)

    brief = ContentBriefBuilder(settings, store).build(snapshot)

    assert brief is not None
    assert brief.supporting_points
    assert brief.context_sources
    assert brief.angle_label


def test_signal_ranker_produces_comment_candidate():
    store = _make_store()
    settings = _make_settings()
    analyzer = SectorAnalyzer(settings, store)
    snapshot = ContextSnapshot(
        created_at="2026-04-01T20:00:00",
        snapshot_id=10,
        status="sufficient",
        niche_posts_snapshot=[
            ContextPost(
                urn="urn:p3",
                url="https://www.linkedin.com/feed/update/urn:p3/",
                author_name="Paolo Neri",
                author_headline="Esperto fondi europei",
                text="Nei fondi europei molti errori nascono da requisiti letti male e allegati sottovalutati.",
                reaction_count=20,
                comment_count=7,
                source_query="fondi europei",
            )
        ],
    )
    analyzer.ingest_daily_snapshot(snapshot)
    ranked = SignalRanker(settings, store).rank_posts_for_today(limit=5)

    assert ranked
    assert ranked[0].decision in {"comment", "react"}


def test_comment_ranker_returns_structured_report():
    store = _make_store()
    settings = _make_settings()
    analyzer = SectorAnalyzer(settings, store)
    snapshot = ContextSnapshot(
        created_at="2026-04-01T20:00:00",
        snapshot_id=11,
        status="sufficient",
        niche_posts_snapshot=[
            ContextPost(
                urn="urn:p4",
                url="https://www.linkedin.com/feed/update/urn:p4/",
                author_name="Alfa",
                author_headline="Esperto fondi europei",
                text="Nei fondi europei gli errori nascono da requisiti letti male e scadenze sottovalutate.",
                reaction_count=22,
                comment_count=8,
                source_query="fondi europei",
            ),
            ContextPost(
                urn="urn:p5",
                url="https://www.linkedin.com/feed/update/urn:p5/",
                author_name="Beta",
                author_headline="Project Manager",
                text="Post generico sulle competenze trasversali nei team.",
                reaction_count=1,
                comment_count=0,
                source_query="leadership",
            ),
        ],
    )
    analyzer.ingest_daily_snapshot(snapshot)
    ranked = SignalRanker(settings, store).rank_posts_for_today(limit=5)

    selected, report = CommentOpportunityRanker().build(ranked, limit=5, posts_read=snapshot.niche_posts_count)

    assert report.posts_read == 2
    assert report.posts_ranked == len(ranked)
    assert report.posts_filtered >= len(selected)
    assert report.comment_candidates == len(selected)
    assert isinstance(report.to_dict()["excluded_final"], list)
