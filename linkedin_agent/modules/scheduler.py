"""
Builds a structured DailyPlan by orchestrating content generation,
engagement discovery, and network discovery.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from linkedin_agent.config.settings import Settings
from linkedin_agent.modules.content_generator import ContentGenerator
from linkedin_agent.modules.engagement import EngagementModule
from linkedin_agent.modules.network import NetworkModule
from linkedin_agent.modules.tracker import (
    ActivityTracker,
    CommentDraft,
    ConnectionRequest,
    PostDraft,
    ReactionItem,
)


@dataclass
class DailyPlan:
    plan_date: date
    post_draft: Optional[PostDraft]          # None if not a posting day
    comments: list[CommentDraft] = field(default_factory=list)
    reactions: list[ReactionItem] = field(default_factory=list)
    connections: list[ConnectionRequest] = field(default_factory=list)
    is_weekend: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def total_actions(self) -> int:
        return (
            (1 if self.post_draft else 0)
            + len(self.comments)
            + len(self.reactions)
            + len(self.connections)
        )

    @property
    def estimated_duration_minutes(self) -> int:
        # Rough estimate: each action takes ~2 minutes of review + execution
        return self.total_actions * 2


class DailyScheduler:
    def __init__(
        self,
        settings: Settings,
        tracker: ActivityTracker,
        content_gen: ContentGenerator,
        engagement: EngagementModule,
        network: NetworkModule,
    ) -> None:
        self._settings = settings
        self._tracker = tracker
        self._content_gen = content_gen
        self._engagement = engagement
        self._network = network

    # ------------------------------------------------------------------
    # Main builder
    # ------------------------------------------------------------------

    def build_daily_plan(self, dry_run: bool = False) -> DailyPlan:
        """
        Orchestrate all modules to produce today's complete activity plan.
        In dry_run mode, uses mock data (no LinkedIn API calls, no Claude calls).
        """
        tz = ZoneInfo(self._settings.activity.timezone)
        today = datetime.now(tz).date()
        weekday_name = today.strftime("%A")
        is_weekend = weekday_name in ("Saturday", "Sunday")

        plan = DailyPlan(plan_date=today, post_draft=None, is_weekend=is_weekend)

        if is_weekend and self._settings.safety.respect_weekends:
            plan.notes.append("Weekend: nessuna attività automatica pianificata.")
            return plan

        if dry_run:
            return self._build_dry_run_plan(today)

        # -- Post generation --
        if self.should_post_today(weekday_name):
            draft = self._content_gen.generate_post_draft()
            plan.post_draft = draft
            plan.notes.append(f"Post pianificato per oggi ({weekday_name}).")
        else:
            plan.notes.append(f"Oggi ({weekday_name}) non è un giorno di pubblicazione.")

        # -- Comments --
        plan.comments = self._engagement.get_daily_engagement_queue()
        if not plan.comments:
            plan.notes.append("Nessun post rilevante trovato per commenti oggi.")

        # -- Reactions --
        plan.reactions = self._engagement.get_reaction_queue()

        # -- Connections --
        plan.connections = self._network.get_connection_queue()

        return plan

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def should_post_today(self, weekday_name: str | None = None) -> bool:
        """
        Decide whether today is a posting day based on:
        - posts_per_week limit
        - best_days_to_post preference
        - how many posts have already been published this week
        """
        max_per_week = self._settings.activity.daily_limits.posts_per_week
        posted_this_week = self._tracker.get_weekly_post_count()

        if posted_this_week >= max_per_week:
            return False

        preferred_days = self._settings.activity.best_days_to_post
        if weekday_name and preferred_days:
            return weekday_name in preferred_days

        return True  # No preference set, always ok to post

    def get_posting_time(self) -> datetime:
        """Return a randomized posting time within the configured window."""
        tz = ZoneInfo(self._settings.activity.timezone)
        now = datetime.now(tz)
        start = self._settings.activity.posting_window.start_hour
        end = self._settings.activity.posting_window.end_hour
        hour = random.randint(start, end - 1)
        minute = random.randint(0, 59)
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    def _build_dry_run_plan(self, today: date) -> DailyPlan:
        """Returns a plan with mock data for testing without API calls."""
        mock_post = PostDraft(
            content=(
                "3 motivi per cui le PMI italiane lasciano sul tavolo i fondi europei.\n\n"
                "Solo il 12% delle imprese eligible accede ai contributi disponibili.\n"
                "Ecco gli ostacoli più comuni:\n\n"
                "1. Non conoscono i bandi aperti\n"
                "2. Credono di non avere i requisiti\n"
                "3. Ritengono il processo troppo complesso\n\n"
                "La realtà: con il supporto giusto, molte di queste barriere spariscono.\n"
                "Quale ostacolo riconosci nella tua organizzazione?"
            ),
            hashtags=["#fondieuropei", "#PMI", "#PNRR", "#finanzaagevolata", "#bandeuropei"],
            pillar="Dati e tendenze sui finanziamenti europei",
            format_type="dato_sorprendente",
        )
        mock_comment = CommentDraft(
            post_urn="urn:li:activity:0000000000000001",
            post_url="https://www.linkedin.com/feed/update/urn:li:activity:0000000000000001/",
            post_author="Mario Rossi",
            post_text_snippet="Il PNRR ha stanziato 191 miliardi per l'Italia...",
            comment_text=(
                "Dato importante. Vale la pena aggiungere che circa il 40% "
                "di queste risorse passa attraverso bandi regionali, spesso meno noti "
                "ma con meno concorrenza. Stai monitorando anche i canali regionali?"
            ),
            relevance_score=0.87,
        )
        mock_reaction = ReactionItem(
            post_urn="urn:li:activity:0000000000000002",
            post_url="https://www.linkedin.com/feed/update/urn:li:activity:0000000000000002/",
            post_author="Giulia Bianchi",
            post_text_snippet="Horizon Europe: apertura nuova call per il settore salute...",
            reaction_type="like",
            motivation="Post di Giulia Bianchi raggiunge professionisti del tuo niche. Mettere 'consiglia' aumenta la tua visibilità verso i suoi follower.",
        )
        mock_connection = ConnectionRequest(
            profile_urn="urn:li:fs_profile:EXAMPLE001",
            full_name="Laura Verdi",
            headline="Europrogettista | Fondi UE | Terzo Settore",
            profile_url="https://www.linkedin.com/in/laura-verdi/",
            relevance_score=0.91,
            motivation="Europrogettista con 8 anni di esperienza in fondi europei per il terzo settore — perfettamente in target con il tuo niche.",
        )
        return DailyPlan(
            plan_date=today,
            post_draft=mock_post,
            comments=[mock_comment],
            reactions=[mock_reaction],
            connections=[mock_connection],
            notes=["[DRY RUN] Dati di esempio — nessuna chiamata API reale."],
        )
