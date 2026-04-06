"""
Build and persist the daily content brief from the latest available snapshot.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from linkedin_agent.scripts.cli_common import RecoverableCLIError, run_cli_job
from linkedin_agent.scripts.job_runtime import (
    build_brief_from_snapshot,
    collect_context,
    ensure_browser_session,
    ingest_snapshot,
    load_core_runtime,
    load_latest_snapshot,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and persist the daily content brief.")
    parser.add_argument(
        "--refresh-context",
        action="store_true",
        default=os.environ.get("BUILD_BRIEF_REFRESH_CONTEXT", "").lower() in {"1", "true", "yes"},
        help="Collect a fresh context snapshot before building the brief.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    def _handler(logger):
        settings, tracker, store, _ = load_core_runtime(require_llm=False)
        if args.refresh_context:
            browser_detail = ensure_browser_session(settings)
            logger.info("Sessione browser valida: %s", browser_detail)
            snapshot = collect_context(settings, tracker, logger)
            ingest_snapshot(settings, store, snapshot, run_kind="daily_incremental")
        else:
            snapshot = load_latest_snapshot(tracker)
            logger.info("Uso l'ultimo snapshot disponibile: %s", snapshot.snapshot_id)

        if snapshot.status != "sufficient":
            raise RecoverableCLIError("Lo snapshot piu recente non e' sufficiente per costruire un brief.")

        brief, brief_id = build_brief_from_snapshot(settings, store, snapshot)
        summary = {
            "brief_id": brief_id,
            "snapshot_id": brief.snapshot_id,
            "angle_label": brief.angle_label,
            "selected_pattern": brief.selected_pattern,
            "target_reader": brief.target_reader,
            "recommended_cta": brief.recommended_cta,
            "supporting_points_count": len(brief.supporting_points),
            "context_sources_count": len(brief.context_sources),
            "brief": brief.to_dict(),
        }
        return summary, brief.notes

    return run_cli_job("build_daily_brief", _handler)


if __name__ == "__main__":
    raise SystemExit(main())
