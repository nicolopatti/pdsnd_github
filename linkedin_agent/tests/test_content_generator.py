from unittest.mock import MagicMock

from linkedin_agent.modules.context_collector import ContextPost, ContextSnapshot
from linkedin_agent.modules.content_generator import ContentGenerator


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


def test_validate_post_draft_rejects_broken_json_fragment():
    ai = MagicMock()
    ai.parse_json_response_safe.return_value = {}
    generator = ContentGenerator(_make_settings(), ai)

    data = generator.parse_post_response("{")
    errors = generator.validate_post_draft(data, ContextSnapshot(created_at="2026-03-31T23:00:00", status="sufficient"))

    assert data == {}
    assert errors == ["Nessun JSON valido trovato nella risposta AI."]


def test_generate_post_draft_returns_error_when_ai_output_is_invalid():
    ai = MagicMock()
    ai.generate_with_retry.side_effect = ["{", "{"]
    ai.parse_json_response_safe.return_value = {}
    ai.model_name = "gemini-test"
    ai.describe_error.return_value = "boom"
    generator = ContentGenerator(_make_settings(), ai)

    snapshot = ContextSnapshot(
        created_at="2026-03-31T23:00:00",
        status="sufficient",
        niche_posts_snapshot=[
            ContextPost(
                urn="urn:test",
                url="https://www.linkedin.com/feed/update/urn:test/",
                author_name="Mario Rossi",
                author_headline="Esperto PNRR",
                text="Molti enti sbagliano la lettura dei requisiti nei bandi PNRR e arrivano tardi alla candidatura.",
                reaction_count=12,
                comment_count=3,
                source_query="PNRR",
            )
        ],
    )

    result = generator.generate_post_draft(snapshot=snapshot)

    assert result.status == "invalid_ai_output"
    assert result.draft is None
    assert result.validation_errors == ["La risposta JSON del provider LLM sembra troncata prima della chiusura."]
    assert result.raw_response_excerpt == "{"


def test_generate_post_draft_returns_ok_when_ai_output_is_valid():
    ai = MagicMock()
    ai.generate_with_retry.return_value = """CONTENT:
Questo post spiega come leggere meglio un bando europeo senza partire tardi sulla candidatura.

HASHTAGS:
#fondieuropei

RATIONALE:
Basato sul contesto reale.

PATTERN:
Checklist pratica

SOURCES:
- Post settore: esempio
"""
    ai.parse_json_response_safe.return_value = {}
    ai.model_name = "gemini-test"
    generator = ContentGenerator(_make_settings(), ai)

    snapshot = ContextSnapshot(created_at="2026-03-31T23:00:00", status="sufficient")
    result = generator.generate_post_draft(snapshot=snapshot)

    assert result.is_ok
    assert result.draft is not None
    assert result.draft.content.startswith("Questo post")


def test_parse_tagged_response_handles_section_format():
    ai = MagicMock()
    ai.parse_json_response_safe.return_value = {}
    generator = ContentGenerator(_make_settings(), ai)

    parsed = generator.parse_post_response("""CONTENT:
Post di esempio.

HASHTAGS:
#uno
#due

RATIONALE:
Perche' nasce dal contesto.

PATTERN:
Checklist pratica

SOURCES:
- Fonte uno
- Fonte due
""")

    assert parsed["content"] == "Post di esempio."
    assert parsed["hashtags"] == ["#uno", "#due"]
    assert parsed["chosen_pattern"] == "Checklist pratica"


def test_generate_post_draft_requires_sufficient_context():
    ai = MagicMock()
    ai.model_name = "gemini-test"
    generator = ContentGenerator(_make_settings(), ai)

    result = generator.generate_post_draft(snapshot=ContextSnapshot(created_at="2026-03-31T23:00:00", status="insufficient"))

    assert result.status == "insufficient_context"
    assert result.draft is None


def test_generate_post_draft_salvages_partial_tagged_response():
    ai = MagicMock()
    ai.generate_with_retry.return_value = """CONTENT:
3 errori nei bandi PNRR che puoi evitare oggi.

Molte candidature saltano non per mancanza di idee, ma per errori di lettura dei requisiti, allegati incompleti e tempi sottovalutati.

Se lavori su fondi europei, una checklist iniziale vale più di una corsa finale.
"""
    ai.parse_json_response_safe.return_value = {}
    ai.model_name = "gemini-test"
    generator = ContentGenerator(_make_settings(), ai)

    snapshot = ContextSnapshot(
        created_at="2026-03-31T23:00:00",
        status="sufficient",
        recent_posts_snapshot=[
            ContextPost(
                urn="urn:own",
                url="https://www.linkedin.com/feed/update/urn:own/",
                author_name="Niccolo",
                author_headline="Consulente",
                text="Post recente su bandi e checklist operative.",
            )
        ],
        niche_posts_snapshot=[
            ContextPost(
                urn="urn:test",
                url="https://www.linkedin.com/feed/update/urn:test/",
                author_name="Mario Rossi",
                author_headline="Esperto PNRR",
                text="Molti enti sbagliano la lettura dei requisiti nei bandi PNRR e arrivano tardi alla candidatura.",
                reaction_count=12,
                comment_count=3,
                source_query="PNRR",
            )
        ],
    )

    result = generator.generate_post_draft(snapshot=snapshot)

    assert result.is_ok
    assert result.draft is not None
    assert result.draft.content.startswith("3 errori")
    assert result.draft.hashtags
    assert result.draft.context_sources


def test_generate_post_variants_uses_brief_and_returns_multiple_variants():
    ai = MagicMock()
    ai.generate_with_retry.side_effect = [
        """CONTENT:
Variante uno con taglio operativo sui requisiti.

HASHTAGS:
#fondieuropei

RATIONALE:
Prima variante.

PATTERN:
Checklist pratica

SOURCES:
- Fonte uno
""",
        """CONTENT:
Variante due con taglio piu differenziante sulle scadenze.

HASHTAGS:
#fondieuropei

RATIONALE:
Seconda variante.

PATTERN:
Contrarian insight

SOURCES:
- Fonte due
""",
    ]
    ai.parse_json_response_safe.return_value = {}
    ai.model_name = "claude-test"
    generator = ContentGenerator(_make_settings(), ai)

    from linkedin_agent.modules.knowledge_types import ContentBrief

    draft_set = generator.generate_post_variants(
        brief=ContentBrief(
            snapshot_id=12,
            angle_label="Angolo su scadenze",
            selected_pattern="Checklist pratica",
            target_reader="Grant consultant",
            recommended_cta="Commenta per la checklist.",
            supporting_points=["Errore: requisiti letti tardi"],
            context_sources=["Post settore: esempio"],
        ),
        count=2,
    )

    assert len(draft_set.variants) == 2
    assert draft_set.variants[0].content.startswith("Variante uno")
    assert draft_set.variants[1].content.startswith("Variante due")
