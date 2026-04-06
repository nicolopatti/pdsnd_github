"""
Playwright-based LinkedIn reader used for all planning-time data collection.
It relies on an authenticated browser session saved by BrowserSession.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote_plus

from linkedin_agent.automation.browser import BrowserSession, LINKEDIN_BASE
from linkedin_agent.config.settings import Settings
from linkedin_agent.core.linkedin_client import FeedPost, Profile


@dataclass
class OwnProfileSnapshot:
    full_name: str
    headline: str
    about: str
    featured_items: list[str] = field(default_factory=list)
    experience_items: list[str] = field(default_factory=list)
    profile_url: str = ""


class BrowserLinkedInReader:
    """
    Read-only LinkedIn collector through a saved Playwright session.
    Runs headless by default to avoid opening UI during planning.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def get_own_profile(self) -> Optional[OwnProfileSnapshot]:
        with BrowserSession(self._settings, headless_override=True) as session:
            page = session.page
            url = self._settings.user.linkedin_url
            self._open_page(page, url)
            sections = self._collect_section_texts(page)
            name = self._first_non_empty([
                self._safe_text(page, "h1"),
                self._extract_first_line(page),
                self._settings.user.name,
            ])
            headline = self._first_non_empty([
                self._safe_text(page, "div.text-body-medium"),
                self._find_line_after_name(sections, name),
                self._settings.user.headline,
            ])
            about = self._find_section(sections, ["informazioni", "about"])
            featured = self._extract_bullets(self._find_section(sections, ["in primo piano", "featured"]))
            experience = self._extract_bullets(self._find_section(sections, ["esperienza", "experience"]))

            return OwnProfileSnapshot(
                full_name=name or self._settings.user.name,
                headline=headline or self._settings.user.headline,
                about=about,
                featured_items=featured[:5],
                experience_items=experience[:5],
                profile_url=url,
            )

    def get_own_recent_posts(self, limit: int = 5) -> list[FeedPost]:
        with BrowserSession(self._settings, headless_override=True) as session:
            page = session.page
            activity_url = self._settings.user.linkedin_url.rstrip("/") + "/recent-activity/all/"
            self._open_page(page, activity_url)
            cards = self._iter_post_like_cards(page)
            return self._collect_posts_from_cards(cards, limit=limit, default_author=self._settings.user.name)

    def search_sector_posts(self, keywords: list[str], limit: int = 12) -> list[FeedPost]:
        posts: list[FeedPost] = []
        seen: set[str] = set()
        with BrowserSession(self._settings, headless_override=True) as session:
            page = session.page
            for keyword in keywords[:4]:
                url = f"{LINKEDIN_BASE}/search/results/content/?keywords={quote_plus(keyword)}"
                self._open_page(page, url)
                cards = self._iter_post_like_cards(page)
                for post in self._collect_posts_from_cards(cards, limit=limit, source_query=keyword):
                    if not post.urn or post.urn in seen:
                        continue
                    seen.add(post.urn)
                    posts.append(post)
                    if len(posts) >= limit:
                        return posts
        return posts[:limit]

    def search_sector_profiles(
        self,
        keywords: list[str],
        location: str = "",
        limit: int = 12,
    ) -> list[Profile]:
        profiles: list[Profile] = []
        seen: set[str] = set()
        with BrowserSession(self._settings, headless_override=True) as session:
            page = session.page
            for keyword in keywords[:4]:
                url = f"{LINKEDIN_BASE}/search/results/people/?keywords={quote_plus(keyword)}"
                self._open_page(page, url)
                cards = page.locator("li.reusable-search__result-container, div[data-chameleon-result-urn], main a[href*='/in/']")
                count = min(cards.count(), limit * 6 or 10)
                for idx in range(count):
                    try:
                        profile = self._parse_people_card(cards.nth(idx), source_query=keyword)
                    except Exception:
                        continue
                    if not profile or not profile.urn or profile.urn in seen:
                        continue
                    if location and profile.location and location.lower() not in profile.location.lower():
                        continue
                    seen.add(profile.urn)
                    profiles.append(profile)
                    if len(profiles) >= limit:
                        return profiles
        return profiles[:limit]

    def get_feed_posts(self, keywords: list[str], count: int = 20) -> list[FeedPost]:
        return self.search_sector_posts(keywords, limit=count)

    def search_people(self, keywords: list[str], location: str = "Italy", limit: int = 20) -> list[Profile]:
        return self.search_sector_profiles(keywords, location=location, limit=limit)

    def _collect_posts_from_cards(
        self,
        cards,
        limit: int,
        default_author: str = "",
        source_query: str = "",
    ) -> list[FeedPost]:
        posts: list[FeedPost] = []
        seen: set[str] = set()
        count = min(cards.count(), max(limit * 5, limit))
        for idx in range(count):
            try:
                post = self._parse_post_card(cards.nth(idx), default_author=default_author, source_query=source_query)
            except Exception:
                continue
            if not post or not post.urn or post.urn in seen:
                continue
            seen.add(post.urn)
            posts.append(post)
            if len(posts) >= limit:
                break
        return posts

    def _iter_post_like_cards(self, page):
        selectors = [
            "div.feed-shared-update-v2",
            "div.occludable-update",
            "li.search-results__list-item",
            "li.profile-creator-shared-feed-update__container",
            "div[data-chameleon-result-urn]",
        ]
        best = None
        best_count = 0
        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = locator.count()
            except Exception:
                continue
            if count > best_count:
                best = locator
                best_count = count
        return best or page.locator("main")

    def _parse_post_card(self, card, default_author: str = "", source_query: str = "") -> Optional[FeedPost]:
        text = " ".join(part.strip() for part in card.all_inner_texts() if part.strip())
        text = self._normalize_whitespace(text)
        if len(text) < 40:
            return None

        post_url = ""
        urn = ""
        links = card.locator("a[href*='/feed/update/'], a[href*='/posts/']")
        if links.count():
            href = links.first.get_attribute("href") or ""
            post_url = self._absolute_url(href)
            urn = self._extract_post_urn(post_url)

        author = default_author
        headline = ""
        profile_links = card.locator("a[href*='/in/']")
        if profile_links.count():
            author = self._normalize_whitespace(profile_links.first.inner_text()) or default_author
        if author:
            headline = self._extract_secondary_line(text, author)

        counts_text = " ".join(card.locator("button, span").all_inner_texts())
        reactions, comments = self._extract_social_counts(counts_text)

        return FeedPost(
            urn=urn or post_url or text[:60],
            author_name=author or "Autore LinkedIn",
            author_headline=headline,
            text=text[:1800],
            reaction_count=reactions,
            comment_count=comments,
            url=post_url,
            published_at=source_query or None,
        )

    def _parse_people_card(self, card, source_query: str = "") -> Optional[Profile]:
        if hasattr(card, "locator"):
            links = card.locator("a[href*='/in/']")
            if links.count():
                href = links.first.get_attribute("href") or ""
                name = self._normalize_whitespace(links.first.inner_text())
                body_text = self._normalize_whitespace(card.inner_text())
            else:
                href = card.get_attribute("href") or ""
                name = self._normalize_whitespace(card.inner_text())
                body_text = name
        else:
            return None

        profile_url = self._absolute_url(href)
        public_id = self._extract_public_id(profile_url)
        if not public_id:
            return None

        lines = [line.strip() for line in re.split(r"[\n•]", body_text) if line.strip()]
        headline = lines[1] if len(lines) > 1 else source_query
        location = lines[2] if len(lines) > 2 else ""

        return Profile(
            urn=profile_url,
            full_name=name or public_id,
            headline=headline,
            location=location,
            summary="",
            current_company="",
            profile_url=profile_url,
            connection_degree=2,
        )

    def _open_page(self, page, url: str) -> None:
        page.goto(url, timeout=25000, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        page.wait_for_timeout(2500)

    def _collect_section_texts(self, page) -> list[str]:
        sections = page.locator("section")
        collected: list[str] = []
        count = min(sections.count(), 20)
        for idx in range(count):
            try:
                text = self._normalize_whitespace(sections.nth(idx).inner_text())
            except Exception:
                continue
            if text:
                collected.append(text)
        return collected

    def _find_section(self, sections: list[str], keywords: list[str]) -> str:
        for section in sections:
            lower = section.lower()
            if any(keyword in lower for keyword in keywords):
                return section[:2000]
        return ""

    def _extract_bullets(self, section_text: str) -> list[str]:
        if not section_text:
            return []
        lines = [self._normalize_whitespace(part) for part in re.split(r"[\n•]", section_text) if self._normalize_whitespace(part)]
        return lines[1:] if len(lines) > 1 else lines

    def _extract_first_line(self, page) -> str:
        try:
            main_text = page.locator("main").inner_text()
        except Exception:
            return ""
        for line in main_text.splitlines():
            line = self._normalize_whitespace(line)
            if line:
                return line
        return ""

    def _find_line_after_name(self, sections: list[str], name: str) -> str:
        for section in sections:
            lines = [self._normalize_whitespace(line) for line in section.splitlines() if self._normalize_whitespace(line)]
            for idx, line in enumerate(lines):
                if name and name in line and idx + 1 < len(lines):
                    return lines[idx + 1]
        return ""

    def _extract_secondary_line(self, block_text: str, author: str) -> str:
        lines = [self._normalize_whitespace(line) for line in block_text.splitlines() if self._normalize_whitespace(line)]
        for idx, line in enumerate(lines):
            if author and author in line and idx + 1 < len(lines):
                return lines[idx + 1]
        return ""

    def _extract_social_counts(self, text: str) -> tuple[int, int]:
        cleaned = text.lower()
        reactions = 0
        comments = 0
        match = re.search(r"(\d+)\s+(?:reaction|reazioni|like)", cleaned)
        if match:
            reactions = int(match.group(1))
        match = re.search(r"(\d+)\s+(?:comment|commenti)", cleaned)
        if match:
            comments = int(match.group(1))
        if reactions == 0:
            reactions = self._extract_first_int(cleaned)
        return reactions, comments

    def _extract_first_int(self, text: str) -> int:
        match = re.search(r"(\d+)", text)
        return int(match.group(1)) if match else 0

    def _absolute_url(self, href: str) -> str:
        if not href:
            return ""
        if href.startswith("http"):
            return href.split("?")[0]
        return f"{LINKEDIN_BASE}{href}".split("?")[0]

    def _extract_post_urn(self, url: str) -> str:
        if "/feed/update/" in url:
            return url.rstrip("/").split("/feed/update/")[-1]
        if "/posts/" in url:
            return url.rstrip("/").split("/posts/")[-1]
        return url

    def _extract_public_id(self, profile_url: str) -> str:
        if "/in/" not in profile_url:
            return ""
        return profile_url.rstrip("/").split("/in/")[-1]

    def _safe_text(self, page, selector: str) -> str:
        try:
            locator = page.locator(selector).first
            return self._normalize_whitespace(locator.inner_text())
        except Exception:
            return ""

    def _normalize_whitespace(self, value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip()

    def _first_non_empty(self, values: list[str]) -> str:
        for value in values:
            if value:
                return value
        return ""
