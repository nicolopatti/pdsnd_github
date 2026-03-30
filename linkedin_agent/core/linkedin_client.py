"""
READ-ONLY wrapper around the unofficial linkedin-api library.
All write operations (posting, commenting, reacting) go through Playwright (automation/).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from linkedin_api import Linkedin


@dataclass
class FeedPost:
    urn: str
    author_name: str
    author_headline: str
    text: str
    reaction_count: int
    comment_count: int
    url: str
    published_at: Optional[str] = None


@dataclass
class Profile:
    urn: str
    full_name: str
    headline: str
    location: str
    summary: str
    current_company: str
    profile_url: str
    connection_degree: int = 3  # 1, 2, or 3+


@dataclass
class Comment:
    urn: str
    author_name: str
    text: str


class LinkedInReader:
    """
    Read-only interface to LinkedIn via the unofficial linkedin-api library.
    Used for: feed search, people search, profile reads, comment reads.
    """

    def __init__(self, email: str, password: str, li_at: str = "") -> None:
        if li_at:
            # Cookie-based auth bypasses LinkedIn's CHALLENGE security check
            self._api = Linkedin(email, password, cookies={"li_at": li_at})
        else:
            self._api = Linkedin(email, password)

    # ------------------------------------------------------------------
    # Feed / Post discovery
    # ------------------------------------------------------------------

    def get_feed_posts(self, keywords: list[str], count: int = 20) -> list[FeedPost]:
        """Search the feed for posts matching the given keywords."""
        posts: list[FeedPost] = []
        for keyword in keywords[:3]:  # Limit keyword searches to avoid rate limits
            try:
                results = self._api.search_posts(keyword, limit=count // len(keywords[:3]) + 1)
                for r in results:
                    post = self._parse_post(r)
                    if post:
                        posts.append(post)
                time.sleep(2)
            except Exception:
                continue
        # Deduplicate by URN
        seen: set[str] = set()
        unique: list[FeedPost] = []
        for p in posts:
            if p.urn not in seen:
                seen.add(p.urn)
                unique.append(p)
        return unique[:count]

    def _parse_post(self, raw: dict) -> Optional[FeedPost]:
        try:
            urn = raw.get("entityUrn", "")
            actor = raw.get("actor", {})
            author_name = actor.get("name", {}).get("text", "Unknown")
            author_headline = actor.get("description", {}).get("text", "")
            commentary = raw.get("commentary", {})
            text = commentary.get("text", {}).get("text", "") if isinstance(commentary, dict) else ""
            social = raw.get("socialDetail", {})
            reaction_count = social.get("totalSocialActivityCounts", {}).get("numLikes", 0)
            comment_count = social.get("totalSocialActivityCounts", {}).get("numComments", 0)
            # Build URL from URN
            post_id = urn.split(":")[-1] if urn else ""
            url = f"https://www.linkedin.com/feed/update/{urn}/" if urn else ""
            return FeedPost(
                urn=urn,
                author_name=author_name,
                author_headline=author_headline,
                text=text,
                reaction_count=reaction_count,
                comment_count=comment_count,
                url=url,
            )
        except Exception:
            return None

    # ------------------------------------------------------------------
    # People search
    # ------------------------------------------------------------------

    def search_people(
        self,
        keywords: list[str],
        location: str = "Italy",
        limit: int = 20,
    ) -> list[Profile]:
        """Search for people matching job title keywords."""
        profiles: list[Profile] = []
        for keyword in keywords[:2]:
            try:
                results = self._api.search_people(
                    keywords=keyword,
                    network_depths=["F", "S"],  # 1st and 2nd degree
                    limit=limit // 2 + 1,
                )
                for r in results:
                    profile = self._parse_profile_summary(r)
                    if profile:
                        profiles.append(profile)
                time.sleep(2)
            except Exception:
                continue
        seen: set[str] = set()
        unique: list[Profile] = []
        for p in profiles:
            if p.urn not in seen:
                seen.add(p.urn)
                unique.append(p)
        return unique[:limit]

    def _parse_profile_summary(self, raw: dict) -> Optional[Profile]:
        try:
            urn = raw.get("entityUrn", "")
            public_id = raw.get("publicIdentifier", "")
            name = raw.get("name", "")
            headline = raw.get("headline", "")
            location = raw.get("subline", {}).get("text", "") if isinstance(raw.get("subline"), dict) else ""
            degree = raw.get("memberDistance", {}).get("value", "DISTANCE_3")
            degree_map = {"DISTANCE_1": 1, "DISTANCE_2": 2, "OUT_OF_NETWORK": 3}
            return Profile(
                urn=urn,
                full_name=name,
                headline=headline,
                location=location,
                summary="",
                current_company="",
                profile_url=f"https://www.linkedin.com/in/{public_id}/",
                connection_degree=degree_map.get(degree, 3),
            )
        except Exception:
            return None

    def get_profile(self, public_id: str) -> Optional[Profile]:
        """Fetch a full profile by public LinkedIn ID (slug)."""
        try:
            raw = self._api.get_profile(public_id)
            summary = raw.get("summary", "")
            headline = raw.get("headline", "")
            location = raw.get("locationName", "")
            first = raw.get("firstName", "")
            last = raw.get("lastName", "")
            name = f"{first} {last}".strip()
            urn = raw.get("entityUrn", "")
            # Current company from experience
            experience = raw.get("experience", [])
            current_company = ""
            if experience:
                current_company = experience[0].get("companyName", "")
            return Profile(
                urn=urn,
                full_name=name,
                headline=headline,
                location=location,
                summary=summary,
                current_company=current_company,
                profile_url=f"https://www.linkedin.com/in/{public_id}/",
            )
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    def get_post_comments(self, post_urn: str, limit: int = 10) -> list[Comment]:
        """Read existing comments on a post."""
        try:
            raw_comments = self._api.get_post_comments(post_urn, comment_count=limit)
            comments: list[Comment] = []
            for c in raw_comments:
                urn = c.get("entityUrn", "")
                actor = c.get("commenter", {})
                author = actor.get("name", {}).get("text", "Unknown") if isinstance(actor.get("name"), dict) else ""
                text = c.get("comment", {}).get("text", {}).get("text", "") if isinstance(c.get("comment"), dict) else ""
                comments.append(Comment(urn=urn, author_name=author, text=text))
            return comments
        except Exception:
            return []
