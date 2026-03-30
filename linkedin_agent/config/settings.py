"""
Loads config.yaml and .env, validates required fields, and exposes a
single Settings object used by all modules.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent.parent
_CONFIG_PATH = Path(__file__).parent / "config.yaml"
_ENV_PATH = _ROOT / ".env"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class UserConfig:
    name: str
    linkedin_url: str
    headline: str
    language: str
    tone: str


@dataclass
class ContentPillar:
    name: str
    weight: int


@dataclass
class ContentFormat:
    name: str
    description: str
    weight: int


@dataclass
class NicheConfig:
    primary_keywords: list[str]
    hashtags: list[str]
    content_pillars: list[ContentPillar]
    content_formats: list[ContentFormat]


@dataclass
class TargetProfiles:
    job_titles: list[str]
    industries: list[str]
    locations: list[str]


@dataclass
class ActivityLimits:
    posts_per_week: int
    comments_per_day: int
    reactions_per_day: int
    connection_requests_per_day: int
    profile_views_per_day: int


@dataclass
class PostingWindow:
    start_hour: int
    end_hour: int


@dataclass
class ActivityConfig:
    daily_limits: ActivityLimits
    posting_window: PostingWindow
    best_days_to_post: list[str]
    timezone: str


@dataclass
class SafetyConfig:
    min_delay_between_actions_seconds: int
    max_delay_between_actions_seconds: int
    session_max_actions: int
    respect_weekends: bool
    headless_browser: bool


@dataclass
class Settings:
    user: UserConfig
    niche: NicheConfig
    target_profiles: TargetProfiles
    influencers_to_monitor: list[str]
    activity: ActivityConfig
    safety: SafetyConfig

    # Secrets (from .env)
    gemini_api_key: str = field(default="", repr=False)
    linkedin_email: str = field(default="", repr=False)
    linkedin_password: str = field(default="", repr=False)
    linkedin_li_at: str = field(default="", repr=False)  # Cookie li_at (bypasses CHALLENGE)

    # Derived paths
    data_dir: Path = field(default_factory=lambda: _ROOT / "linkedin_agent" / "data")


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_settings(config_path: Path = _CONFIG_PATH) -> Settings:
    load_dotenv(_ENV_PATH)

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    u = raw["user"]
    user = UserConfig(
        name=u["name"],
        linkedin_url=u["linkedin_url"],
        headline=u["headline"],
        language=u["language"],
        tone=u["tone"],
    )

    n = raw["niche"]
    niche = NicheConfig(
        primary_keywords=n["primary_keywords"],
        hashtags=n["hashtags"],
        content_pillars=[ContentPillar(**p) for p in n["content_pillars"]],
        content_formats=[ContentFormat(**f) for f in n["content_formats"]],
    )

    tp = raw["target_profiles"]
    target_profiles = TargetProfiles(
        job_titles=tp["job_titles"],
        industries=tp["industries"],
        locations=tp["locations"],
    )

    a = raw["activity"]
    lim = a["daily_limits"]
    activity = ActivityConfig(
        daily_limits=ActivityLimits(
            posts_per_week=lim["posts_per_week"],
            comments_per_day=lim["comments_per_day"],
            reactions_per_day=lim["reactions_per_day"],
            connection_requests_per_day=lim["connection_requests_per_day"],
            profile_views_per_day=lim["profile_views_per_day"],
        ),
        posting_window=PostingWindow(**a["posting_window"]),
        best_days_to_post=a["best_days_to_post"],
        timezone=a["timezone"],
    )

    s = raw["safety"]
    safety = SafetyConfig(
        min_delay_between_actions_seconds=s["min_delay_between_actions_seconds"],
        max_delay_between_actions_seconds=s["max_delay_between_actions_seconds"],
        session_max_actions=s["session_max_actions"],
        respect_weekends=s["respect_weekends"],
        headless_browser=s["headless_browser"],
    )

    settings = Settings(
        user=user,
        niche=niche,
        target_profiles=target_profiles,
        influencers_to_monitor=raw.get("influencers_to_monitor", {}).get("profiles", []),
        activity=activity,
        safety=safety,
    )

    # Load secrets from environment
    settings.gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
    settings.linkedin_email = os.environ.get("LINKEDIN_EMAIL", "")
    settings.linkedin_password = os.environ.get("LINKEDIN_PASSWORD", "")
    settings.linkedin_li_at = os.environ.get("LINKEDIN_LI_AT", "")

    _validate(settings)
    return settings


def _validate(s: Settings) -> None:
    errors: list[str] = []
    if not s.gemini_api_key:
        errors.append("GEMINI_API_KEY not set in .env (get it free at https://aistudio.google.com)")
    if not s.linkedin_email:
        errors.append("LINKEDIN_EMAIL not set in .env")
    if not s.linkedin_password:
        errors.append("LINKEDIN_PASSWORD not set in .env")
    if errors:
        raise EnvironmentError(
            "Missing required environment variables:\n" + "\n".join(f"  - {e}" for e in errors)
        )
