"""
Knowledge-first domain types shared across retrieval, ranking and generation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RetrievedPost:
    urn: str
    url: str
    author_name: str
    author_headline: str
    text: str
    reaction_count: int = 0
    comment_count: int = 0
    published_at: str = ""
    source_query: str = ""
    market_scope: str = "italy"
    language: str = "it"


@dataclass
class RetrievedProfile:
    urn: str
    full_name: str
    headline: str
    location: str
    summary: str
    current_company: str
    profile_url: str
    source_query: str = ""
    market_scope: str = "italy"


@dataclass
class NormalizedPost:
    urn: str
    url: str
    author_name: str
    author_headline: str
    text: str
    normalized_text: str
    reaction_count: int
    comment_count: int
    source_query: str
    market_scope: str
    language: str
    importance_score: float = 0.0
    topic_labels: list[str] = field(default_factory=list)


@dataclass
class NormalizedProfile:
    urn: str
    full_name: str
    headline: str
    location: str
    summary: str
    current_company: str
    profile_url: str
    source_query: str
    market_scope: str
    role_labels: list[str] = field(default_factory=list)
    relevance_score: float = 0.0


@dataclass
class SectorSignal:
    signal_type: str
    signal_key: str
    label: str
    evidence: list[str] = field(default_factory=list)
    market_scope: str = "italy"
    strength_score: float = 0.0


@dataclass
class MarketPattern:
    pattern_key: str
    label: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    market_scope: str = "italy"
    score: float = 0.0


@dataclass
class RankedPost:
    urn: str
    author_name: str
    text_snippet: str
    post_url: str
    score: float
    decision: str
    reasons: list[str] = field(default_factory=list)
    source_query: str = ""
    market_scope: str = "italy"
    passed_prefilter: bool = True


@dataclass
class RankedProfile:
    urn: str
    full_name: str
    headline: str
    profile_url: str
    score: float
    decision: str
    reasons: list[str] = field(default_factory=list)
    market_scope: str = "italy"
    passed_prefilter: bool = True


@dataclass
class OpportunityExclusion:
    urn: str
    label: str
    score: float
    decision: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CommentOpportunityReport:
    posts_read: int = 0
    posts_filtered: int = 0
    posts_ranked: int = 0
    comment_candidates: int = 0
    excluded_final: list[OpportunityExclusion] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "posts_read": self.posts_read,
            "posts_filtered": self.posts_filtered,
            "posts_ranked": self.posts_ranked,
            "comment_candidates": self.comment_candidates,
            "excluded_final": [item.to_dict() for item in self.excluded_final],
        }


@dataclass
class ProfileOpportunityReport:
    profiles_read: int = 0
    profiles_filtered: int = 0
    profiles_ranked: int = 0
    connection_candidates: int = 0
    excluded_final: list[OpportunityExclusion] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profiles_read": self.profiles_read,
            "profiles_filtered": self.profiles_filtered,
            "profiles_ranked": self.profiles_ranked,
            "connection_candidates": self.connection_candidates,
            "excluded_final": [item.to_dict() for item in self.excluded_final],
        }


@dataclass
class ContentBrief:
    snapshot_id: int | None
    angle_label: str
    selected_pattern: str
    target_reader: str
    recommended_cta: str
    supporting_points: list[str] = field(default_factory=list)
    context_sources: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DraftVariant:
    angle_label: str
    content: str
    hashtags: list[str]
    rationale: str
    context_sources: list[str] = field(default_factory=list)
    editorial_score: float = 0.0


@dataclass
class DraftSet:
    brief: ContentBrief
    variants: list[DraftVariant] = field(default_factory=list)


@dataclass
class DailyDelta:
    snapshot_id: int | None
    new_posts: int = 0
    new_profiles: int = 0
    signals_emerged: int = 0
    comment_candidates: int = 0
    reaction_candidates: int = 0
    connection_candidates: int = 0
    skipped_posts: list[str] = field(default_factory=list)
    skipped_profiles: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
