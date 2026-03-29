"""
Posts a comment on a LinkedIn post via Playwright.
"""
from __future__ import annotations

from linkedin_agent.automation.browser import BrowserSession, LINKEDIN_BASE
from linkedin_agent.modules.tracker import CommentDraft

_COMMENT_BOX_SELECTOR = "div.comments-comment-box__text-editor div.ql-editor"


class CommentPublisher:
    def __init__(self, session: BrowserSession) -> None:
        self._session = session

    def post_comment(self, draft: CommentDraft) -> bool:
        """
        Navigate to the post and submit the comment.
        Returns True on success.
        """
        page = self._session.page
        self._session.check_action_limit()
        self._session.random_delay()

        # Navigate to the post
        post_url = draft.post_url
        if not post_url:
            return False

        page.goto(post_url, timeout=20000)
        page.wait_for_load_state("networkidle", timeout=15000)
        self._session.random_delay()

        # Click "Add a comment…" to focus the comment box
        try:
            comment_trigger = page.locator(
                "button[aria-label*='comment'], button[aria-label*='commento']"
            ).first
            comment_trigger.click()
            page.wait_for_timeout(1500)
        except Exception:
            pass  # Box may already be visible

        # Type in the comment editor
        editor = page.locator(_COMMENT_BOX_SELECTOR).first
        editor.click()
        page.wait_for_timeout(500)
        self._session.human_type(editor, draft.comment_text)
        self._session.random_delay()

        # Submit with Ctrl+Enter or the Post button
        try:
            submit_btn = page.locator(
                "button.comments-comment-box__submit-button"
            ).first
            submit_btn.click()
            page.wait_for_timeout(2000)
            return True
        except Exception:
            # Fallback: keyboard shortcut
            editor.press("Control+Enter")
            page.wait_for_timeout(2000)
            return True
