"""
Collects and persists the daily LinkedIn context used by the agent.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

from linkedin_agent.automation.browser_reader import BrowserLinkedInReader, OwnProfileSnapshot
from linkedin_agent.config.settings import Settings
from linkedin_agent.core.linkedin_client import FeedPost, Profile
from linkedin_agent.modules.tracker import ActivityTracker


@dataclass
class ContextPost:
    urn: str
    url: str
    author_name: str
    author_headline: str
    text: str
    reaction_count: int = 0
    comment_count: int = 0
    published_at: str = ""
    source_query: str = ""


@dataclass
class ContextProfile:
    profile_urn: str
    full_name: str
    headline: str
    location: str
    summary: str
    current_company: str
    profile_url: str
    source_query: str = ""


@dataclass
class ContextSnapshot:
    created_at: str
    snapshot_id: int | None = None
    profile_snapshot: OwnProfileSnapshot | None = None
    recent_posts_snapshot: list[ContextPost] = field(default_factory=list)
    niche_posts_snapshot: list[ContextPost] = field(default_factory=list)
    niche_profiles_snapshot: list[ContextProfile] = field(default_factory=list)
    status: str = "insufficient"
    notes: list[str] = field(default_factory=list)

    @property
    def own_posts_count(self) -> int:
        return len(self.recent_posts_snapshot)

    @property
    def niche_posts_count(self) -> int:
        return len(self.niche_posts_snapshot)

    @property
    def niche_profiles_count(self) -> int:
        return len(self.niche_profiles_snapshot)

    @property
    def has_minimum_context(self) -> bool:
        return self.profile_snapshot is not None and (self.own_posts_count > 0 or self.niche_posts_count > 0)

    def to_dict(self) -> dict:
        return {
            "created_at": self.created_at,
            "snapshot_id": self.snapshot_id,
            "profile_snapshot": asdict(self.profile_snapshot) if self.profile_snapshot else None,
            "recent_posts_snapshot": [asdict(post) for post in self.recent_posts_snapshot],
            "niche_posts_snapshot": [asdict(post) for post in self.niche_posts_snapshot],
            "niche_profiles_snapshot": [asdict(profile) for profile in self.niche_profiles_snapshot],
            "status": self.status,
            "notes": self.notes,
            "counts": {
                "own_posts": self.own_posts_count,
                "niche_posts": self.niche_posts_count,
                "niche_profiles": self.niche_profiles_count,
            },
        }


class ContextCollector:
    def __init__(
        self,
        settings: Settings,
        tracker: ActivityTracker,
        reader: BrowserLinkedInReader,
    ) -> None:
        self._settings = settings
        self._tracker = tracker
        self._reader = reader

    def collect_daily_context(self) -> ContextSnapshot:
        created_at = datetime.now().isoformat(timespec="seconds")
        notes: list[str] = []

        profile_snapshot = self._reader.get_own_profile()
        if not profile_snapshot:
            notes.append("Profilo LinkedIn non leggibile dalla sessione browser.")

        recent_posts = [
            self._to_context_post(post, source_query="own_recent_posts")
            for post in self._reader.get_own_recent_posts(limit=5)
        ]
        if not recent_posts:
            notes.append("Nessun post recente del profilo trovato.")

        niche_posts = [
            self._to_context_post(post, source_query=post.published_at or "")
            for post in self._reader.search_sector_posts(self._settings.niche.primary_keywords, limit=10)
        ]
        if not niche_posts:
            notes.append("Nessun post del settore trovato nelle ricerche LinkedIn.")

        niche_profiles = [
            self._to_context_profile(profile)
            for profile in self._reader.search_sector_profiles(
                self._settings.target_profiles.job_titles,
                location=self._settings.target_profiles.locations[0] if self._settings.target_profiles.locations else "",
                limit=10,
            )
        ]
        if not niche_profiles:
            notes.append("Nessun profilo del settore trovato nelle ricerche LinkedIn.")

        snapshot = ContextSnapshot(
            created_at=created_at,
            profile_snapshot=profile_snapshot,
            recent_posts_snapshot=recent_posts,
            niche_posts_snapshot=niche_posts,
            niche_profiles_snapshot=niche_profiles,
            notes=notes,
        )
        snapshot.status = "sufficient" if snapshot.has_minimum_context else "insufficient"

        self._persist_snapshot(snapshot)
        return snapshot

    def _persist_snapshot(self, snapshot: ContextSnapshot) -> None:
        if snapshot.profile_snapshot:
            self._tracker.log_profile_snapshot(snapshot.profile_snapshot)
        for post in snapshot.recent_posts_snapshot:
            self._tracker.log_recent_post_seen(post)
        for post in snapshot.niche_posts_snapshot:
            self._tracker.log_niche_post_seen(post)
        for profile in snapshot.niche_profiles_snapshot:
            self._tracker.mark_profile_seen(
                profile.profile_urn,
                score=0.0,
                full_name=profile.full_name,
                headline=profile.headline,
                profile_url=profile.profile_url,
            )
        snapshot.snapshot_id = self._tracker.log_context_run(snapshot)

    def _to_context_post(self, post: FeedPost, source_query: str = "") -> ContextPost:
        return ContextPost(
            urn=post.urn,
            url=post.url,
            author_name=post.author_name,
            author_headline=post.author_headline,
            text=post.text,
            reaction_count=post.reaction_count,
            comment_count=post.comment_count,
            published_at=post.published_at or "",
            source_query=source_query,
        )

    def _to_context_profile(self, profile: Profile) -> ContextProfile:
        return ContextProfile(
            profile_urn=profile.urn,
            full_name=profile.full_name,
            headline=profile.headline,
            location=profile.location,
            summary=profile.summary,
            current_company=profile.current_company,
            profile_url=profile.profile_url,
        )
