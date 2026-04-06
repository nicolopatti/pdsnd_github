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
from linkedin_agent.core.claude_client import ClaudeClient
from linkedin_agent.core.provider_factory import create_llm_provider


def _make_settings():
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
        llm_provider="claude",
        anthropic_api_key="test-key",
        anthropic_model="claude-test-model",
        linkedin_email="test@test.com",
        linkedin_password="test",
    )


def test_create_llm_provider_defaults_to_claude():
    provider = create_llm_provider(_make_settings())

    assert isinstance(provider, ClaudeClient)
    assert provider.model_name == "claude-test-model"
