"""
Discovers relevant LinkedIn profiles and builds connection request queues.
"""
from __future__ import annotations

import json
from pathlib import Path

from linkedin_agent.config.settings import Settings
from linkedin_agent.core.claude_client import ClaudeClient
from linkedin_agent.core.linkedin_client import LinkedInReader, Profile
from linkedin_agent.modules.tracker import ActivityTracker, ConnectionRequest

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


class NetworkModule:
    def __init__(
        self,
        settings: Settings,
        claude: ClaudeClient,
        linkedin: LinkedInReader,
        tracker: ActivityTracker,
    ) -> None:
        self._settings = settings
        self._claude = claude
        self._linkedin = linkedin
        self._tracker = tracker
        self._scoring_template = (_PROMPTS_DIR / "profile_scoring.txt").read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover_profiles(self, limit: int = 30) -> list[Profile]:
        """Search for relevant profiles based on configured job titles and locations."""
        job_titles = self._settings.target_profiles.job_titles
        locations = self._settings.target_profiles.locations

        profiles: list[Profile] = []
        for title in job_titles[:3]:  # Limit API calls
            location = locations[0] if locations else "Italy"
            found = self._linkedin.search_people(
                keywords=[title],
                location=location,
                limit=limit // 3 + 1,
            )
            for p in found:
                if not self._tracker.is_profile_seen(p.urn):
                    profiles.append(p)
            if len(profiles) >= limit:
                break

        return profiles[:limit]

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score_profile(self, profile: Profile) -> tuple[float, str]:
        """
        Use Claude to score profile relevance (0.0-1.0).
        Returns (score, motivation) where motivation is shown to the user.
        """
        system_prompt = self._scoring_template.format(
            user_name=self._settings.user.name,
            profile_name=profile.full_name,
            profile_headline=profile.headline,
            current_company=profile.current_company,
            profile_summary=profile.summary[:300] if profile.summary else "N/A",
        )
        user_prompt = "Valuta il profilo e rispondi con il JSON richiesto."

        try:
            raw = self._claude.generate(system_prompt, user_prompt, max_tokens=200)
            text = raw.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1])
            data = json.loads(text)
            score = float(data.get("score", 0.0))
            motivation = data.get("motivation", "Profilo potenzialmente rilevante per il tuo niche.")
            return max(0.0, min(1.0, score)), motivation
        except Exception:
            return 0.0, "Errore nella valutazione del profilo."

    # ------------------------------------------------------------------
    # Connection queue
    # ------------------------------------------------------------------

    def get_connection_queue(self, limit: int | None = None) -> list[ConnectionRequest]:
        """
        Build today's connection request queue.
        Respects the daily_limits.connection_requests_per_day config.
        Excludes already-seen profiles.
        """
        max_connections = limit or self._settings.activity.daily_limits.connection_requests_per_day
        already_done = self._tracker.get_daily_connection_count()
        remaining = max_connections - already_done
        if remaining <= 0:
            return []

        profiles = self.discover_profiles(limit=remaining * 3)
        requests: list[ConnectionRequest] = []

        for profile in profiles:
            score, motivation = self.score_profile(profile)
            self._tracker.mark_profile_seen(profile.urn, score)

            if score < 0.5:
                continue

            requests.append(
                ConnectionRequest(
                    profile_urn=profile.urn,
                    full_name=profile.full_name,
                    headline=profile.headline,
                    profile_url=profile.profile_url,
                    relevance_score=score,
                    motivation=motivation,
                )
            )
            if len(requests) >= remaining:
                break

        requests.sort(key=lambda r: r.relevance_score, reverse=True)
        return requests
