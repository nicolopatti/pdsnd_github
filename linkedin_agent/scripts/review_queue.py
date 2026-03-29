"""
Standalone review script: process previously generated items waiting for approval
without triggering new content generation or LinkedIn API calls.

Usage:
    python -m linkedin_agent.scripts.review_queue
"""
from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console
from rich.rule import Rule

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from linkedin_agent.config.settings import load_settings
from linkedin_agent.core.claude_client import ClaudeClient
from linkedin_agent.modules.content_generator import ContentGenerator
from linkedin_agent.modules.scheduler import DailyPlan
from linkedin_agent.modules.strategy_advisor import StrategyAdvisor
from linkedin_agent.modules.tracker import ActivityTracker
from linkedin_agent.review.approval_cli import ApprovalCLI

console = Console()


def main() -> None:
    settings = load_settings()
    db_path = settings.data_dir / "activity_log.db"
    tracker = ActivityTracker(db_path)
    tracker.init_db()

    # Load pending items from DB
    posts = tracker.get_pending_posts()
    comments = tracker.get_pending_comments()
    reactions = tracker.get_pending_reactions()
    connections = tracker.get_pending_connections()

    total = len(posts) + len(comments) + len(reactions) + len(connections)
    if total == 0:
        console.print("[yellow]Nessun elemento in attesa di revisione.[/yellow]")
        return

    console.print(
        Rule("[bold cyan]Revisione Coda[/bold cyan]", style="cyan")
    )
    console.print(
        f"[dim]Trovati: {len(posts)} post, {len(comments)} commenti, "
        f"{len(reactions)} reazioni, {len(connections)} connessioni[/dim]\n"
    )

    claude = ClaudeClient(api_key=settings.anthropic_api_key)
    content_gen = ContentGenerator(settings, claude)
    advisor = StrategyAdvisor(settings, claude, tracker)
    cli = ApprovalCLI(tracker=tracker, content_gen=content_gen, advisor=advisor)

    from datetime import date
    plan = DailyPlan(
        plan_date=date.today(),
        post_draft=posts[0] if posts else None,
        comments=comments,
        reactions=reactions,
        connections=connections,
    )
    if len(posts) > 1:
        plan.notes.append(
            f"{len(posts)} post in coda — solo il primo verrà mostrato in questa sessione."
        )

    cli.run_review_session(plan)


if __name__ == "__main__":
    main()
