"""
Playwright browser session manager.
Handles login persistence, random human-like delays, and session reuse.
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from linkedin_agent.config.settings import Settings

LINKEDIN_BASE = "https://www.linkedin.com"
_SESSION_FILE = "browser_session.json"  # Relative to data_dir


class BrowserSession:
    """
    Context manager for a Playwright Chromium browser session.
    On first run, opens a visible browser so the user can log in manually.
    Subsequent runs reuse saved cookies/localStorage.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session_path = settings.data_dir / _SESSION_FILE
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._action_count = 0

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "BrowserSession":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._playwright = sync_playwright().start()
        headless = self._settings.safety.headless_browser
        self._browser = self._playwright.chromium.launch(headless=headless)

        if self._session_path.exists():
            storage = json.loads(self._session_path.read_text())
            self._context = self._browser.new_context(storage_state=storage)
        else:
            self._context = self._browser.new_context()

        self._page = self._context.new_page()
        self._action_count = 0

        if not self._is_logged_in():
            self._handle_login()

    def stop(self) -> None:
        if self._context:
            self._save_session()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def _is_logged_in(self) -> bool:
        """Check if the current session has a valid LinkedIn login."""
        try:
            self._page.goto(f"{LINKEDIN_BASE}/feed/", timeout=15000)
            return "feed" in self._page.url
        except Exception:
            return False

    def _handle_login(self) -> None:
        """Open the login page and wait for the user to log in manually."""
        print("\n[Browser] Prima esecuzione: accedi a LinkedIn nel browser che si è aperto.")
        print("[Browser] Dopo il login, premi INVIO qui per continuare.\n")
        self._page.goto(f"{LINKEDIN_BASE}/login")
        input()  # Wait for user confirmation
        if "feed" not in self._page.url:
            raise RuntimeError(
                "Login non rilevato. Assicurati di aver completato il login su LinkedIn."
            )
        self._save_session()
        print("[Browser] Sessione salvata. I prossimi avvii non richiederanno il login.")

    def _save_session(self) -> None:
        self._session_path.parent.mkdir(parents=True, exist_ok=True)
        storage = self._context.storage_state()
        self._session_path.write_text(json.dumps(storage))

    # ------------------------------------------------------------------
    # Page access
    # ------------------------------------------------------------------

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("Browser session not started. Use as context manager.")
        return self._page

    # ------------------------------------------------------------------
    # Safety
    # ------------------------------------------------------------------

    def random_delay(self) -> None:
        """Sleep for a random duration between configured min/max values."""
        min_s = self._settings.safety.min_delay_between_actions_seconds
        max_s = self._settings.safety.max_delay_between_actions_seconds
        delay = random.uniform(min_s, max_s)
        time.sleep(delay)

    def check_action_limit(self) -> None:
        """Raise if the session's action limit has been reached."""
        self._action_count += 1
        if self._action_count > self._settings.safety.session_max_actions:
            raise RuntimeError(
                f"Limite azioni per sessione raggiunto "
                f"({self._settings.safety.session_max_actions}). "
                "Riavvia l'agente per continuare."
            )

    def human_type(self, locator, text: str) -> None:
        """Type text character by character with random human-like delays."""
        for char in text:
            locator.type(char)
            time.sleep(random.uniform(0.04, 0.12))
