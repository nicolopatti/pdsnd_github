"""
Standalone weekly strategy briefing generator.
Can be run any day to get a strategic analysis of your LinkedIn presence.

Usage:
    python -m linkedin_agent.scripts.weekly_strategy
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from linkedin_agent.config.settings import load_settings
from linkedin_agent.core.ai_client import AIClient as ClaudeClient
from linkedin_agent.modules.strategy_advisor import StrategyAdvisor
from linkedin_agent.modules.tracker import ActivityTracker
from linkedin_agent.scripts.run_daily import _print_weekly_brief, _print_summary


def main() -> None:
    settings = load_settings()
    db_path = settings.data_dir / "activity_log.db"
    tracker = ActivityTracker(db_path)
    tracker.init_db()

    claude = ClaudeClient(api_key=settings.gemini_api_key)
    advisor = StrategyAdvisor(settings, claude, tracker)

    from rich.console import Console
    from rich.rule import Rule
    console = Console()
    console.print(Rule("[bold cyan]Briefing Strategico LinkedIn[/bold cyan]", style="cyan"))
    console.print("[dim]Analisi in corso...[/dim]\n")

    brief = advisor.generate_weekly_strategy_brief()
    _print_weekly_brief(brief)
    _print_summary(tracker)


if __name__ == "__main__":
    main()
