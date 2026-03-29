"""
Applies reactions ("consiglia" / like or "diffondi" / repost) to LinkedIn posts via Playwright.
"""
from __future__ import annotations

from linkedin_agent.automation.browser import BrowserSession
from linkedin_agent.modules.tracker import ReactionItem

_LIKE_BUTTON_SELECTOR = "button[aria-label*='Like'], button[aria-label*='Consiglia']"
_REPOST_BUTTON_SELECTOR = "button[aria-label*='Repost'], button[aria-label*='Diffondi']"
_REPOST_CONFIRM_SELECTOR = "button[aria-label='Repost now']"


class ReactionPublisher:
    def __init__(self, session: BrowserSession) -> None:
        self._session = session

    def react(self, item: ReactionItem) -> bool:
        """
        Apply the reaction (like or repost) to the post.
        Returns True on success.
        """
        if item.reaction_type == "repost":
            return self._repost(item)
        return self._like(item)

    def _like(self, item: ReactionItem) -> bool:
        page = self._session.page
        self._session.check_action_limit()
        self._session.random_delay()

        page.goto(item.post_url, timeout=20000)
        page.wait_for_load_state("networkidle", timeout=15000)
        self._session.random_delay()

        try:
            btn = page.locator(_LIKE_BUTTON_SELECTOR).first
            btn.click()
            page.wait_for_timeout(1500)
            return True
        except Exception:
            return False

    def _repost(self, item: ReactionItem) -> bool:
        page = self._session.page
        self._session.check_action_limit()
        self._session.random_delay()

        page.goto(item.post_url, timeout=20000)
        page.wait_for_load_state("networkidle", timeout=15000)
        self._session.random_delay()

        try:
            # Click Repost button (opens modal)
            btn = page.locator(_REPOST_BUTTON_SELECTOR).first
            btn.click()
            page.wait_for_timeout(1500)
            # Confirm "Repost now" (no added text)
            confirm = page.locator(_REPOST_CONFIRM_SELECTOR).first
            confirm.click()
            page.wait_for_timeout(2000)
            return True
        except Exception:
            return False
