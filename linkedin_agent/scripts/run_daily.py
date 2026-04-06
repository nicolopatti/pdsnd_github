"""
Main entry point for the daily routine.
Orchestrates the full workflow:
  1. Build daily plan (generate content + discover engagement + network opportunities)
  2. Human review & approval via terminal CLI
  3. Execute approved actions via Playwright
  4. Print progress summary
  5. On Fridays: generate weekly strategy brief

Usage:
    python -m linkedin_agent.scripts.run_daily           # Full run
    python -m linkedin_agent.scripts.run_daily --dry-run # Test with mock data, no LinkedIn/API calls
    python -m linkedin_agent.scripts.run_daily --plan-only  # Generate plan, skip execution
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from rich.console import Console
from rich.rule import Rule
from rich.table import Table

# Add repo root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from linkedin_agent.automation.browser import BrowserSession
from linkedin_agent.automation.browser_reader import BrowserLinkedInReader
from linkedin_agent.automation.comment_publisher import CommentPublisher
from linkedin_agent.automation.post_publisher import PostPublisher
from linkedin_agent.automation.reaction_publisher import ReactionPublisher
from linkedin_agent.config.settings import load_settings
from linkedin_agent.core.provider_factory import create_llm_provider
from linkedin_agent.modules.context_collector import ContextCollector
from linkedin_agent.modules.content_generator import ContentGenerator
from linkedin_agent.modules.engagement import EngagementModule
from linkedin_agent.modules.knowledge_store import SectorKnowledgeStore
from linkedin_agent.modules.network import NetworkModule
from linkedin_agent.modules.scheduler import DailyScheduler
from linkedin_agent.modules.strategy_advisor import StrategyAdvisor
from linkedin_agent.modules.tracker import ActivityTracker
from linkedin_agent.review.approval_cli import ApprovalCLI

console = Console()


def main(dry_run: bool = False, plan_only: bool = False) -> None:
    console.print(Rule("[bold cyan]LinkedIn Growth Agent — Avvio[/bold cyan]", style="cyan"))

    # -- Load settings --
    settings = load_settings()
    db_path = settings.data_dir / "activity_log.db"

    # -- Initialize core components --
    tracker = ActivityTracker(db_path)
    tracker.init_db()
    knowledge_store = SectorKnowledgeStore(db_path)
    knowledge_store.init_db()

    llm = create_llm_provider(settings)
    content_gen = ContentGenerator(settings, llm, tracker)
    advisor = StrategyAdvisor(settings, llm, tracker)

    context_collector = None
    if dry_run:
        engagement = None
        network = None
    else:
        browser_ok, browser_detail = BrowserSession.probe_saved_session(settings)
        if browser_ok:
            console.print(f"[cyan]Sessione browser LinkedIn valida.[/cyan] [dim]{browser_detail}[/dim]")
            reader = BrowserLinkedInReader(settings)
            engagement = EngagementModule(settings, llm, reader, tracker)
            network = NetworkModule(settings, llm, reader, tracker)
            context_collector = ContextCollector(settings, tracker, reader)
        else:
            console.print("[yellow]LinkedIn non autenticato via browser.[/yellow]")
            console.print("[dim]Accedi dal launcher o salva una sessione browser prima di eseguire il piano.[/dim]")
            engagement = None
            network = None

    # For dry_run, pass stub modules (scheduler handles None gracefully via dry_run flag)
    scheduler = DailyScheduler(
        settings=settings,
        tracker=tracker,
        content_gen=content_gen,
        engagement=engagement or _StubEngagement(),
        network=network or _StubNetwork(),
        context_collector=context_collector,
        knowledge_store=knowledge_store,
    )

    # -- Build daily plan --
    console.print("[dim]Costruzione del piano giornaliero...[/dim]")
    try:
        plan = scheduler.build_daily_plan(dry_run=dry_run)
    except Exception as e:
        console.print(f"[red]{llm.describe_error(e, llm.model_name)}[/red]")
        return

    if (
        not plan.post_draft
        and not plan.comments
        and not plan.reactions
        and not plan.connections
        and not plan.post_slot_available
    ):
        console.print("[yellow]Nessuna attività pianificata per oggi.[/yellow]")
        if plan.notes:
            for note in plan.notes:
                console.print(f"  [dim]{note}[/dim]")
        return

    if (
        not dry_run
        and plan.context_snapshot
        and plan.context_snapshot.status == "sufficient"
        and plan.post_slot_available
        and plan.content_brief
    ):
        post_result = content_gen.generate_post_draft(snapshot=plan.context_snapshot, brief=plan.content_brief)
        if post_result.is_ok:
            plan.post_draft = post_result.draft
            console.print("[green]Post generato e pronto per revisione.[/green]")
        else:
            plan.notes.append(f"Generazione post non riuscita: {post_result.error_message}")
            console.print(f"[yellow]{post_result.error_message}[/yellow]")
    elif plan.post_slot_available and not plan.content_brief:
        console.print("[yellow]Nessun content brief disponibile: la knowledge base non e' ancora abbastanza ricca.[/yellow]")

    # -- Human review --
    cli = ApprovalCLI(tracker=tracker, content_gen=content_gen, advisor=advisor)
    cli.run_review_session(plan)

    if plan_only:
        console.print("[yellow]Modalità --plan-only: nessuna azione eseguita.[/yellow]")
        _print_summary(tracker)
        return

    # -- Execute approved actions --
    console.print(Rule("[bold]Esecuzione Azioni Approvate[/bold]", style="blue"))

    approved_posts = tracker.get_approved_posts()
    approved_comments = tracker.get_approved_comments()
    approved_reactions = tracker.get_approved_reactions()
    approved_connections = tracker.get_approved_connections()

    total = len(approved_posts) + len(approved_comments) + len(approved_reactions) + len(approved_connections)
    if total == 0:
        console.print("[yellow]Nessuna azione approvata da eseguire.[/yellow]")
    else:
        console.print(f"[dim]Avvio browser per {total} azioni...[/dim]")
        with BrowserSession(settings) as session:
            post_pub = PostPublisher(session)
            comment_pub = CommentPublisher(session)
            reaction_pub = ReactionPublisher(session)

            for post in approved_posts:
                console.print(f"[blue]Pubblicazione post...[/blue]")
                urn = post_pub.publish(post)
                tracker.mark_post_published(post.id, urn)
                console.print("[green]✓ Post pubblicato.[/green]")
                session.random_delay()

            for comment in approved_comments:
                console.print(f"[green]Invio commento su post di {comment.post_author}...[/green]")
                ok = comment_pub.post_comment(comment)
                if ok:
                    tracker.mark_comment_published(comment.id)
                    console.print("[green]✓ Commento pubblicato.[/green]")
                else:
                    console.print("[red]✗ Errore nel pubblicare il commento.[/red]")
                session.random_delay()

            for reaction in approved_reactions:
                icon = "🔁" if reaction.reaction_type == "repost" else "👍"
                console.print(f"[yellow]{icon} Reazione su post di {reaction.post_author}...[/yellow]")
                ok = reaction_pub.react(reaction)
                if ok:
                    tracker.mark_reaction_done(reaction.id)
                    console.print("[green]✓ Reazione applicata.[/green]")
                else:
                    console.print("[red]✗ Errore nell'applicare la reazione.[/red]")
                session.random_delay()

            for conn in approved_connections:
                console.print(f"[magenta]Connessione a {conn.full_name}...[/magenta]")
                try:
                    session.page.goto(conn.profile_url, timeout=20000)
                    session.page.wait_for_load_state("networkidle", timeout=15000)
                    session.random_delay()
                    connect_btn = session.page.locator(
                        "button[aria-label*='Collegati'], button[aria-label*='Connect']"
                    ).first
                    connect_btn.click()
                    session.page.wait_for_timeout(2000)
                    # Dismiss "Add a note" modal with "Send now"
                    try:
                        send_btn = session.page.locator(
                            "button[aria-label*='Invia ora'], button[aria-label*='Send now']"
                        ).first
                        send_btn.click()
                        session.page.wait_for_timeout(1500)
                    except Exception:
                        pass
                    tracker.mark_connection_sent(conn.id)
                    console.print("[green]✓ Richiesta di connessione inviata.[/green]")
                except Exception as e:
                    console.print(f"[red]✗ Errore connessione: {e}[/red]")
                session.random_delay()

    # -- Weekly strategy brief (Fridays) --
    if date.today().weekday() == 4:  # Friday
        console.print(Rule("[bold cyan]Briefing Strategico Settimanale[/bold cyan]", style="cyan"))
        console.print("[dim]Generazione briefing...[/dim]")
        brief = advisor.generate_weekly_strategy_brief()
        _print_weekly_brief(brief)

    # -- Progress summary --
    _print_summary(tracker)


def _print_summary(tracker: ActivityTracker) -> None:
    report = tracker.export_progress_report()
    console.print(Rule("[bold]Riepilogo[/bold]", style="dim"))

    table = Table(show_header=False, box=None)
    table.add_column(style="dim", width=25)
    table.add_column(style="bold cyan")
    table.add_row("Post pubblicati (tot):", str(report["all_time"]["posts_published"]))
    table.add_row("Commenti postati (tot):", str(report["all_time"]["comments_posted"]))
    table.add_row("Connessioni inviate (tot):", str(report["all_time"]["connections_sent"]))
    table.add_row("Reazioni fatte (tot):", str(report["all_time"]["reactions_done"]))
    table.add_row("Post questa settimana:", str(report["this_week"]["posts"]))
    table.add_row("Commenti oggi:", str(report["today"]["comments"]))
    table.add_row("Reazioni oggi:", str(report["today"]["reactions"]))
    console.print(table)
    console.print()


def _print_weekly_brief(brief) -> None:
    from rich.panel import Panel

    if brief.week_summary:
        console.print(Panel(brief.week_summary, title="Sommario Settimanale", border_style="cyan"))

    if brief.what_worked:
        console.print("\n[bold green]✓ Cosa ha funzionato[/bold green]")
        for item in brief.what_worked:
            console.print(f"  [green]•[/green] {item.pattern}")
            console.print(f"    [dim]{item.evidence}[/dim]")
            console.print(f"    → {item.recommendation}")

    if brief.what_to_improve:
        console.print("\n[bold yellow]⚡ Cosa migliorare[/bold yellow]")
        for item in brief.what_to_improve:
            console.print(f"  [yellow]•[/yellow] {item.pattern}")
            console.print(f"    [dim]{item.evidence}[/dim]")
            console.print(f"    → {item.recommendation}")

    if brief.top_3_recommendations:
        console.print("\n[bold cyan]🎯 Top 3 Raccomandazioni per la Prossima Settimana[/bold cyan]")
        for i, rec in enumerate(brief.top_3_recommendations, 1):
            console.print(f"  {i}. {rec}")

    if brief.content_mix_feedback:
        console.print(f"\n[bold]Mix di Contenuti:[/bold] {brief.content_mix_feedback}")

    if brief.next_week_focus:
        console.print(
            Panel(
                brief.next_week_focus,
                title="[bold cyan]Priorità della Prossima Settimana[/bold cyan]",
                border_style="cyan",
            )
        )


# Stub classes for dry-run mode
class _StubEngagement:
    def get_daily_engagement_queue(self, limit=None):
        return []
    def get_reaction_queue(self, limit=None):
        return []


class _StubNetwork:
    def get_connection_queue(self, limit=None):
        return []


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LinkedIn Growth Agent — Daily Run")
    parser.add_argument("--dry-run", action="store_true", help="Usa dati mock senza chiamate API")
    parser.add_argument("--plan-only", action="store_true", help="Genera piano e review, senza eseguire")
    args = parser.parse_args()
    main(dry_run=args.dry_run, plan_only=args.plan_only)
