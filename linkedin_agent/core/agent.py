"""
Main agent orchestrator.
Provides a single Agent class that wires all components together.
Used by the scripts as a convenient facade.
"""
from __future__ import annotations

from linkedin_agent.config.settings import Settings, load_settings
from linkedin_agent.core.provider_factory import create_llm_provider
from linkedin_agent.core.linkedin_client import LinkedInReader
from linkedin_agent.modules.content_generator import ContentGenerator
from linkedin_agent.modules.engagement import EngagementModule
from linkedin_agent.modules.network import NetworkModule
from linkedin_agent.modules.scheduler import DailyScheduler
from linkedin_agent.modules.strategy_advisor import StrategyAdvisor
from linkedin_agent.modules.tracker import ActivityTracker


class Agent:
    """
    Facade that initializes and wires all agent components from a Settings object.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        db_path = settings.data_dir / "activity_log.db"

        self.tracker = ActivityTracker(db_path)
        self.tracker.init_db()

        self.llm = create_llm_provider(settings)
        self.linkedin = LinkedInReader(settings.linkedin_email, settings.linkedin_password)

        self.content_gen = ContentGenerator(settings, self.llm)
        self.engagement = EngagementModule(settings, self.llm, self.linkedin, self.tracker)
        self.network = NetworkModule(settings, self.llm, self.linkedin, self.tracker)
        self.advisor = StrategyAdvisor(settings, self.llm, self.tracker)
        self.scheduler = DailyScheduler(
            settings=settings,
            tracker=self.tracker,
            content_gen=self.content_gen,
            engagement=self.engagement,
            network=self.network,
        )

    @classmethod
    def from_config(cls) -> "Agent":
        """Create an Agent instance by loading config from the default locations."""
        return cls(load_settings())
