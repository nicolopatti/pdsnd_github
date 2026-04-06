"""
Bootstrap the persistent sector knowledge base from the current LinkedIn session.

Usage:
    python -m linkedin_agent.scripts.bootstrap_knowledge
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from rich.console import Console

from linkedin_agent.automation.browser import BrowserSession
from linkedin_agent.automation.browser_reader import BrowserLinkedInReader
from linkedin_agent.config.settings import load_settings
from linkedin_agent.modules.context_collector import ContextCollector
from linkedin_agent.modules.knowledge_pipeline import SectorAnalyzer
from linkedin_agent.modules.knowledge_store import SectorKnowledgeStore
from linkedin_agent.modules.tracker import ActivityTracker

console = Console()


def main() -> None:
    console.print("[cyan]Avvio bootstrap della base conoscenza...[/cyan]")
    settings = load_settings()
    console.print("[cyan]Verifico la sessione browser LinkedIn salvata...[/cyan]")
    browser_ok, browser_detail = BrowserSession.probe_saved_session(settings)
    if not browser_ok:
        console.print(f"[red]Sessione browser non valida:[/red] {browser_detail}")
        return
    console.print(f"[green]Sessione valida.[/green] {browser_detail}")

    db_path = settings.data_dir / "activity_log.db"
    tracker = ActivityTracker(db_path)
    tracker.init_db()
    store = SectorKnowledgeStore(db_path)
    store.init_db()

    collector = ContextCollector(settings, tracker, BrowserLinkedInReader(settings))
    console.print("[cyan]Raccolgo il contesto LinkedIn. Questa fase puo richiedere 1-3 minuti...[/cyan]")
    snapshot = collector.collect_daily_context()
    console.print(
        "[green]Contesto raccolto.[/green] "
        f"Profilo: {'si' if snapshot.profile_snapshot else 'no'} · "
        f"Tuoi post: {snapshot.own_posts_count} · "
        f"Post settore: {snapshot.niche_posts_count} · "
        f"Profili settore: {snapshot.niche_profiles_count}"
    )
    analyzer = SectorAnalyzer(settings, store)
    console.print("[cyan]Aggiorno la base conoscenza persistente...[/cyan]")
    delta = analyzer.bootstrap_from_snapshot(snapshot, run_kind="bootstrap")
    overview = store.get_overview()

    console.print("[green]Bootstrap knowledge completato.[/green]")
    console.print(f"Snapshot: {snapshot.snapshot_id} · stato {snapshot.status}")
    console.print(f"Delta: post {delta.new_posts}, profili {delta.new_profiles}, segnali {delta.signals_emerged}")
    console.print(
        f"Base conoscenza: post {overview['sector_posts']} · "
        f"profili {overview['sector_profiles']} · "
        f"segnali {overview['sector_signals']} · "
        f"pattern {overview['market_patterns']}"
    )


if __name__ == "__main__":
    main()
