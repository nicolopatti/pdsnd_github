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
from linkedin_agent.modules.context_collector import ContextCollector, ContextSnapshot
from linkedin_agent.modules.content_generator import ContentGenerator
from linkedin_agent.modules.engagement import EngagementModule
from linkedin_agent.modules.knowledge_pipeline import (
    CommentOpportunityRanker,
    ContentBriefBuilder,
    ProfileOpportunityRanker,
    SectorAnalyzer,
    SignalRanker,
)
from linkedin_agent.modules.knowledge_store import SectorKnowledgeStore
from linkedin_agent.modules.knowledge_types import ContentBrief, DailyDelta, RankedPost, RankedProfile
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
    post_slot_available: bool = False
    content_brief: Optional[ContentBrief] = None
    daily_delta: Optional[DailyDelta] = None
    knowledge_overview: dict = field(default_factory=dict)
    comments: list[CommentDraft] = field(default_factory=list)
    reactions: list[ReactionItem] = field(default_factory=list)
    connections: list[ConnectionRequest] = field(default_factory=list)
    context_snapshot: Optional[ContextSnapshot] = None
    is_weekend: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def total_actions(self) -> int:
        return (
            len(self.comments)
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
        context_collector: ContextCollector | None = None,
        knowledge_store: SectorKnowledgeStore | None = None,
    ) -> None:
        self._settings = settings
        self._tracker = tracker
        self._content_gen = content_gen
        self._engagement = engagement
        self._network = network
        self._context_collector = context_collector
        self._knowledge_store = knowledge_store
        self._sector_analyzer = SectorAnalyzer(settings, knowledge_store) if knowledge_store else None
        self._signal_ranker = SignalRanker(settings, knowledge_store) if knowledge_store else None
        self._comment_ranker = CommentOpportunityRanker()
        self._profile_ranker = ProfileOpportunityRanker()
        self._brief_builder = ContentBriefBuilder(settings, knowledge_store) if knowledge_store else None

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

        if not self._context_collector:
            plan.notes.append("Context collector non configurato.")
            return plan
        if not self._knowledge_store or not self._sector_analyzer or not self._signal_ranker or not self._brief_builder:
            plan.notes.append("Knowledge store non configurato.")
            return plan

        snapshot = self._context_collector.collect_daily_context()
        plan.context_snapshot = snapshot
        plan.notes.extend(snapshot.notes)

        if snapshot.status != "sufficient":
            plan.notes.append("Contesto insufficiente: impossibile generare un piano affidabile.")
            return plan

        delta = self._sector_analyzer.ingest_daily_snapshot(snapshot)
        plan.daily_delta = delta
        plan.knowledge_overview = self._knowledge_store.get_overview()
        plan.content_brief = self._brief_builder.build(snapshot)
        if not plan.content_brief:
            plan.notes.append("Brief contenuto non disponibile: la base conoscitiva e' ancora troppo povera.")

        plan.post_slot_available = self.should_post_today()
        if plan.post_slot_available and plan.content_brief:
            plan.notes.append("Contesto pronto: puoi generare il post dallo step dedicato.")
        else:
            if not plan.post_slot_available:
                plan.notes.append("Limite settimanale di post raggiunto — generazione post disabilitata oggi.")

        ranked_posts = self._signal_ranker.rank_posts_for_today(limit=18)
        comment_candidates, comment_report = self._comment_ranker.build(
            ranked_posts,
            limit=self._settings.activity.daily_limits.comments_per_day,
            posts_read=snapshot.niche_posts_count,
        )
        delta.comment_candidates = len(comment_candidates)
        delta.skipped_posts = [
            f"{item.label}: {', '.join(item.reasons)}"
            for item in comment_report.excluded_final[:8]
        ]

        # -- Comments --
        plan.comments = self._build_comment_queue(comment_candidates)
        if not plan.comments:
            reason = (
                f"letti {comment_report.posts_read}, filtrati {comment_report.posts_filtered}, "
                f"rankati {comment_report.posts_ranked}"
            )
            if comment_report.excluded_final:
                top = comment_report.excluded_final[0]
                reason += f" · migliore escluso: {top.label} ({', '.join(top.reasons)})"
            plan.notes.append(f"Nessun post rilevante trovato per commenti oggi: {reason}.")

        # -- Reactions --
        reaction_candidates = [post for post in ranked_posts if post.decision == "react"][: self._settings.activity.daily_limits.reactions_per_day]
        delta.reaction_candidates = len(reaction_candidates)
        plan.reactions = self._build_reaction_queue(reaction_candidates)

        # -- Connections --
        ranked_profiles = self._signal_ranker.rank_profiles_for_today(limit=18)
        connection_candidates, profile_report = self._profile_ranker.build(
            ranked_profiles,
            limit=self._settings.activity.daily_limits.connection_requests_per_day,
            profiles_read=snapshot.niche_profiles_count,
        )
        delta.connection_candidates = len(connection_candidates)
        delta.skipped_profiles = [
            f"{item.label}: {', '.join(item.reasons)}"
            for item in profile_report.excluded_final[:8]
        ]
        plan.connections = self._build_connection_queue(connection_candidates)

        return plan

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def should_post_today(self, weekday_name: str | None = None) -> bool:
        """
        Decide whether today is a posting day based only on the weekly limit.
        Day-of-week scheduling is handled externally (e.g. n8n).
        """
        max_per_week = self._settings.activity.daily_limits.posts_per_week
        posted_this_week = self._tracker.get_weekly_post_count()
        return posted_this_week < max_per_week

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
            post_draft=None,
            post_slot_available=True,
            content_brief=ContentBrief(
                snapshot_id=None,
                angle_label="Brief demo",
                selected_pattern="Checklist pratica",
                target_reader="Grant consultant, responsabili progettazione",
                recommended_cta="Commenta se vuoi la checklist completa.",
                supporting_points=["Errore ricorrente: lettura tardiva dei requisiti."],
                context_sources=["[DRY RUN] Brief simulato."],
                notes=["[DRY RUN] Brief simulato."],
            ),
            comments=[mock_comment],
            reactions=[mock_reaction],
            connections=[mock_connection],
            context_snapshot=ContextSnapshot(
                created_at=datetime.now().isoformat(timespec="seconds"),
                status="sufficient",
                notes=["[DRY RUN] Context snapshot simulato."],
            ),
            notes=["[DRY RUN] Dati di esempio — nessuna chiamata API reale."],
        )

    def _build_comment_queue(self, ranked_posts: list[RankedPost]) -> list[CommentDraft]:
        comments: list[CommentDraft] = []
        from linkedin_agent.core.linkedin_client import FeedPost

        for item in ranked_posts:
            feed_post = FeedPost(
                urn=item.urn,
                author_name=item.author_name,
                author_headline="",
                text=item.text_snippet,
                reaction_count=0,
                comment_count=0,
                url=item.post_url,
            )
            draft = self._engagement.generate_comment(feed_post)
            draft.relevance_score = item.score
            draft.id = self._tracker.log_comment(draft)
            comments.append(draft)
        return comments

    def _build_reaction_queue(self, ranked_posts: list[RankedPost]) -> list[ReactionItem]:
        reactions: list[ReactionItem] = []
        for item in ranked_posts:
            reaction_type = "repost" if item.score >= 0.72 else "like"
            reaction = ReactionItem(
                post_urn=item.urn,
                post_url=item.post_url,
                post_author=item.author_name,
                post_text_snippet=item.text_snippet,
                reaction_type=reaction_type,
                motivation="; ".join(item.reasons),
            )
            reaction.id = self._tracker.log_reaction(reaction)
            reactions.append(reaction)
        return reactions

    def _build_connection_queue(self, ranked_profiles: list[RankedProfile]) -> list[ConnectionRequest]:
        connections: list[ConnectionRequest] = []
        for item in ranked_profiles:
            request = ConnectionRequest(
                profile_urn=item.urn,
                full_name=item.full_name,
                headline=item.headline,
                profile_url=item.profile_url,
                relevance_score=item.score,
                motivation="; ".join(item.reasons),
            )
            request.id = self._tracker.log_connection(request)
            connections.append(request)
        return connections
