"""
Publishes an approved post draft to LinkedIn via Playwright.
"""
from __future__ import annotations

from linkedin_agent.automation.browser import BrowserSession, LINKEDIN_BASE
from linkedin_agent.modules.tracker import PostDraft

_FEED_URL = f"{LINKEDIN_BASE}/feed/"
_POST_BOX_SELECTOR = "[data-placeholder='Inizia un post']"
_POST_BUTTON_SELECTOR = "button.share-actions__primary-action"


class PostPublisher:
    def __init__(self, session: BrowserSession) -> None:
        self._session = session

    def publish(self, draft: PostDraft) -> str:
        """
        Publish a post to LinkedIn.
        Returns the URL of the published post (best-effort).
        """
        page = self._session.page
        self._session.check_action_limit()
        self._session.random_delay()

        # Navigate to feed
        page.goto(_FEED_URL, timeout=20000)
        page.wait_for_load_state("networkidle", timeout=15000)
        self._session.random_delay()

        # Click "Start a post"
        start_btn = page.locator(_POST_BOX_SELECTOR).first
        start_btn.click()
        page.wait_for_timeout(2000)

        # Find the editor and type the full post content
        editor = page.locator("div.ql-editor[contenteditable='true']").first
        full_text = draft.content
        if draft.hashtags:
            full_text += "\n\n" + "\n".join(draft.hashtags)
        self._session.human_type(editor, full_text)
        self._session.random_delay()

        # Click Post button
        post_btn = page.locator(_POST_BUTTON_SELECTOR).first
        post_btn.click()
        page.wait_for_timeout(3000)

        # Try to get the post URL from the confirmation or profile
        # (LinkedIn doesn't always surface a direct URL immediately)
        post_url = ""
        try:
            # Wait for the success notification or modal close
            page.wait_for_selector("div.artdeco-toast-item", timeout=10000)
        except Exception:
            pass

        return post_url
