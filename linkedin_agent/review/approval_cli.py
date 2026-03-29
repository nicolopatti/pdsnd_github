"""
Interactive terminal UI for the human-in-the-loop review step.
The user reviews each generated item (post, comment, reaction, connection)
and approves, edits, regenerates, or skips it before any action is taken.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Optional

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from linkedin_agent.modules.content_generator import ContentGenerator
from linkedin_agent.modules.strategy_advisor import StrategyAdvisor, StyleFeedback
from linkedin_agent.modules.tracker import (
    ActivityTracker,
    CommentDraft,
    ConnectionRequest,
    PostDraft,
    ReactionItem,
)
from linkedin_agent.modules.scheduler import DailyPlan

console = Console()

_HEADER = "[bold cyan]LinkedIn Growth Agent[/bold cyan] — Revisione Giornaliera"
_MAX_CHAR = 1300


class ApprovalCLI:
    def __init__(
        self,
        tracker: ActivityTracker,
        content_gen: ContentGenerator,
        advisor: StrategyAdvisor,
    ) -> None:
        self._tracker = tracker
        self._content_gen = content_gen
        self._advisor = advisor

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run_review_session(self, plan: DailyPlan) -> None:
        """
        Present the full DailyPlan to the user for review.
        Each approved item is saved to the DB with status='approved'.
        """
        console.print(Rule(_HEADER, style="cyan"))
        console.print(f"[dim]Piano del {plan.plan_date.strftime('%A %d %B %Y')}[/dim]\n")

        if plan.is_weekend:
            console.print("[yellow]Weekend — nessuna attività pianificata.[/yellow]")
            return

        for note in plan.notes:
            console.print(f"[dim italic]ℹ {note}[/dim italic]")
        console.print()

        approved_count = 0

        # -- Post --
        if plan.post_draft:
            console.print(Rule("[bold]POST DA PUBBLICARE[/bold]", style="blue"))
            approved = self._review_post(plan.post_draft)
            if approved:
                approved_count += 1

        # -- Comments --
        if plan.comments:
            console.print(Rule(f"[bold]COMMENTI ({len(plan.comments)})[/bold]", style="green"))
            for i, comment in enumerate(plan.comments, 1):
                console.print(f"\n[dim]Commento {i}/{len(plan.comments)}[/dim]")
                approved = self._review_comment(comment)
                if approved:
                    approved_count += 1

        # -- Reactions --
        if plan.reactions:
            console.print(Rule(f"[bold]REAZIONI ({len(plan.reactions)})[/bold]", style="yellow"))
            for i, reaction in enumerate(plan.reactions, 1):
                console.print(f"\n[dim]Reazione {i}/{len(plan.reactions)}[/dim]")
                approved = self._review_reaction(reaction)
                if approved:
                    approved_count += 1

        # -- Connections --
        if plan.connections:
            console.print(Rule(f"[bold]CONNESSIONI ({len(plan.connections)})[/bold]", style="magenta"))
            for i, conn in enumerate(plan.connections, 1):
                console.print(f"\n[dim]Connessione {i}/{len(plan.connections)}[/dim]")
                approved = self._review_connection(conn)
                if approved:
                    approved_count += 1

        # -- Summary --
        console.print(Rule(style="cyan"))
        console.print(
            f"\n[bold green]Revisione completata.[/bold green] "
            f"{approved_count} azioni approvate su "
            f"{plan.total_actions} suggerite.\n"
        )

    # ------------------------------------------------------------------
    # Review: Post
    # ------------------------------------------------------------------

    def _review_post(self, draft: PostDraft) -> bool:
        # Get style feedback from advisor
        console.print("[dim]Analisi del post in corso...[/dim]")
        feedback = self._advisor.audit_content_style(draft)
        self._display_post(draft, feedback)

        while True:
            choice = Prompt.ask(
                "\n[bold]Cosa vuoi fare?[/bold]",
                choices=["a", "e", "r", "s", "q"],
                default="a",
            )
            if choice == "a":  # Approve
                draft_id = self._tracker.log_post(draft)
                self._tracker.update_post_status(draft_id, "approved")
                draft.id = draft_id
                console.print("[green]✓ Post approvato.[/green]")
                return True
            elif choice == "e":  # Edit in $EDITOR
                edited_content = self._open_in_editor(draft.content)
                if edited_content and edited_content != draft.content:
                    draft.content = edited_content
                    console.print("[cyan]Post aggiornato.[/cyan]")
                    self._display_post(draft)
            elif choice == "r":  # Regenerate
                fb = Prompt.ask("Feedback per la rigenerazione (opzionale)", default="")
                console.print("[dim]Rigenerazione in corso...[/dim]")
                new_draft = self._content_gen.improve_draft(draft, fb or "Migliora il post mantenendo il pilastro e il formato")
                draft.content = new_draft.content
                draft.hashtags = new_draft.hashtags
                new_feedback = self._advisor.audit_content_style(draft)
                self._display_post(draft, new_feedback)
            elif choice == "s":  # Skip
                console.print("[yellow]Post saltato.[/yellow]")
                return False
            elif choice == "q":  # Quit entire session
                console.print("[red]Sessione di revisione interrotta.[/red]")
                raise SystemExit(0)

    def _display_post(self, draft: PostDraft, feedback: Optional[StyleFeedback] = None) -> None:
        char_count = len(draft.content) + sum(len(h) + 1 for h in draft.hashtags)
        count_color = "green" if char_count <= _MAX_CHAR else "red"
        full_text = draft.content + "\n\n" + "\n".join(draft.hashtags)

        post_panel = Panel(
            full_text,
            title=f"[blue]{draft.pillar}[/blue] · [dim]{draft.format_type}[/dim]",
            subtitle=f"[{count_color}]{char_count}/{_MAX_CHAR} caratteri[/{count_color}]",
            border_style="blue",
            padding=(1, 2),
        )
        console.print(post_panel)

        if feedback:
            score_color_v = "green" if feedback.value_score >= 7 else ("yellow" if feedback.value_score >= 5 else "red")
            score_color_a = "green" if feedback.authority_score >= 7 else ("yellow" if feedback.authority_score >= 5 else "red")

            feedback_lines = []
            feedback_lines.append(
                f"[{score_color_v}]Valore: {feedback.value_score:.1f}/10[/{score_color_v}]  "
                f"[{score_color_a}]Autorevolezza: {feedback.authority_score:.1f}/10[/{score_color_a}]"
            )
            if feedback.suggestions:
                feedback_lines.append("\n[bold]Suggerimenti:[/bold]")
                for s in feedback.suggestions:
                    feedback_lines.append(f"  • {s}")
            if feedback.evidence:
                feedback_lines.append("\n[dim][bold]Evidence:[/bold]")
                for e in feedback.evidence:
                    feedback_lines.append(f"  [italic]{e}[/italic][/dim]")

            console.print(
                Panel(
                    "\n".join(feedback_lines),
                    title="[cyan]Analisi Strategica[/cyan]",
                    border_style="cyan",
                    padding=(0, 2),
                )
            )
        console.print(
            "\n  [bold][a][/bold]pprova  "
            "[bold][e][/bold]dita  "
            "[bold][r][/bold]igenera  "
            "[bold][s][/bold]alta  "
            "[bold][q][/bold]uit"
        )

    # ------------------------------------------------------------------
    # Review: Comment
    # ------------------------------------------------------------------

    def _review_comment(self, draft: CommentDraft) -> bool:
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column(style="dim", width=15)
        table.add_column()
        table.add_row("Post di:", draft.post_author)
        table.add_row("Estratto:", f"[italic]{draft.post_text_snippet[:120]}...[/italic]")
        table.add_row("Rilevanza:", f"[cyan]{draft.relevance_score:.0%}[/cyan]")
        table.add_row("URL:", f"[link={draft.post_url}]{draft.post_url[:60]}[/link]" if draft.post_url else "N/A")

        console.print(
            Panel(
                table,
                title="[green]Contesto Post[/green]",
                border_style="dim",
                padding=(0, 1),
            )
        )
        console.print(
            Panel(
                draft.comment_text,
                title="[green]Commento Generato[/green]",
                border_style="green",
                padding=(1, 2),
            )
        )
        console.print(
            "  [bold][a][/bold]pprova  [bold][e][/bold]dita  [bold][s][/bold]alta  [bold][q][/bold]uit"
        )

        while True:
            choice = Prompt.ask("", choices=["a", "e", "s", "q"], default="a")
            if choice == "a":
                comment_id = self._tracker.log_comment(draft)
                self._tracker.update_comment_status(comment_id, "approved")
                draft.id = comment_id
                console.print("[green]✓ Commento approvato.[/green]")
                return True
            elif choice == "e":
                edited = self._open_in_editor(draft.comment_text)
                if edited:
                    draft.comment_text = edited.strip()
                    console.print(Panel(draft.comment_text, border_style="green"))
            elif choice == "s":
                console.print("[yellow]Commento saltato.[/yellow]")
                return False
            elif choice == "q":
                raise SystemExit(0)

    # ------------------------------------------------------------------
    # Review: Reaction
    # ------------------------------------------------------------------

    def _review_reaction(self, item: ReactionItem) -> bool:
        icon = "🔁" if item.reaction_type == "repost" else "👍"
        action = "Diffondi (repost)" if item.reaction_type == "repost" else "Consiglia (like)"

        console.print(
            Panel(
                f"{icon} [bold]{action}[/bold]\n\n"
                f"[dim]Di:[/dim] {item.post_author}\n"
                f"[dim]Estratto:[/dim] [italic]{item.post_text_snippet[:120]}...[/italic]\n\n"
                f"[dim]Perché:[/dim] {item.motivation}",
                title="[yellow]Reazione Suggerita[/yellow]",
                border_style="yellow",
                padding=(1, 2),
            )
        )
        console.print(
            "  [bold][a][/bold]pprova  [bold][s][/bold]alta  [bold][q][/bold]uit"
        )

        choice = Prompt.ask("", choices=["a", "s", "q"], default="a")
        if choice == "a":
            reaction_id = self._tracker.log_reaction(item)
            self._tracker.update_reaction_status(reaction_id, "approved")
            item.id = reaction_id
            console.print("[green]✓ Reazione approvata.[/green]")
            return True
        elif choice == "s":
            console.print("[yellow]Reazione saltata.[/yellow]")
            return False
        elif choice == "q":
            raise SystemExit(0)
        return False

    # ------------------------------------------------------------------
    # Review: Connection
    # ------------------------------------------------------------------

    def _review_connection(self, req: ConnectionRequest) -> bool:
        score_color = "green" if req.relevance_score >= 0.8 else ("yellow" if req.relevance_score >= 0.6 else "white")

        console.print(
            Panel(
                f"[bold]{req.full_name}[/bold]\n"
                f"[italic]{req.headline}[/italic]\n\n"
                f"[{score_color}]Rilevanza: {req.relevance_score:.0%}[/{score_color}]\n"
                f"[dim]{req.motivation}[/dim]\n\n"
                f"[link={req.profile_url}]{req.profile_url}[/link]",
                title="[magenta]Connessione Suggerita[/magenta]",
                border_style="magenta",
                padding=(1, 2),
            )
        )
        console.print(
            "  [bold][a][/bold]pprova  [bold][s][/bold]alta  [bold][q][/bold]uit"
        )

        choice = Prompt.ask("", choices=["a", "s", "q"], default="a")
        if choice == "a":
            conn_id = self._tracker.log_connection(req)
            if conn_id:
                self._tracker.update_connection_status(conn_id, "approved")
                req.id = conn_id
            console.print("[green]✓ Connessione approvata.[/green]")
            return True
        elif choice == "s":
            console.print("[yellow]Connessione saltata.[/yellow]")
            return False
        elif choice == "q":
            raise SystemExit(0)
        return False

    # ------------------------------------------------------------------
    # Editor helper
    # ------------------------------------------------------------------

    def _open_in_editor(self, text: str) -> Optional[str]:
        """Open text in $EDITOR and return edited content."""
        editor = os.environ.get("EDITOR", "nano")
        with tempfile.NamedTemporaryFile(
            suffix=".txt", mode="w", encoding="utf-8", delete=False
        ) as f:
            f.write(text)
            tmp_path = f.name
        try:
            subprocess.run([editor, tmp_path], check=True)
            with open(tmp_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            console.print(f"[red]Errore apertura editor: {e}[/red]")
            return None
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
