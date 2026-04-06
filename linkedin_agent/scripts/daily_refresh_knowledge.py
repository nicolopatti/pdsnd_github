"""
Incremental daily refresh entrypoint for the knowledge base.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from linkedin_agent.modules.knowledge_pipeline import (
    CommentOpportunityRanker,
    ProfileOpportunityRanker,
    SignalRanker,
)
from linkedin_agent.scripts.cli_common import run_cli_job
from linkedin_agent.scripts.job_runtime import collect_context, ensure_browser_session, ingest_snapshot, load_core_runtime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh knowledge base with today's LinkedIn delta.")
    parser.add_argument(
        "--rank-limit",
        type=int,
        default=int(os.environ.get("DAILY_REFRESH_RANK_LIMIT", "20")),
        help="How many ranked posts/profiles to inspect while producing the summary report.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    def _handler(logger):
        settings, tracker, store, _ = load_core_runtime(require_llm=False)
        browser_detail = ensure_browser_session(settings)
        logger.info("Sessione browser valida: %s", browser_detail)
        snapshot = collect_context(settings, tracker, logger)
        delta, overview = ingest_snapshot(settings, store, snapshot, run_kind="daily_incremental")

        signal_ranker = SignalRanker(settings, store)
        ranked_posts = signal_ranker.rank_posts_for_today(limit=args.rank_limit)
        ranked_profiles = signal_ranker.rank_profiles_for_today(limit=args.rank_limit)
        comment_candidates, comment_report = CommentOpportunityRanker().build(
            ranked_posts,
            limit=5,
            posts_read=snapshot.niche_posts_count,
        )
        connection_candidates, profile_report = ProfileOpportunityRanker().build(
            ranked_profiles,
            limit=5,
            profiles_read=snapshot.niche_profiles_count,
        )
        delta.comment_candidates = len(comment_candidates)
        delta.connection_candidates = len(connection_candidates)
        delta.skipped_posts = [
            f"{item.label}: {', '.join(item.reasons)}"
            for item in comment_report.excluded_final[:8]
        ]
        delta.skipped_profiles = [
            f"{item.label}: {', '.join(item.reasons)}"
            for item in profile_report.excluded_final[:8]
        ]

        summary = {
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_status": snapshot.status,
            "counts": {
                "own_posts": snapshot.own_posts_count,
                "niche_posts": snapshot.niche_posts_count,
                "niche_profiles": snapshot.niche_profiles_count,
            },
            "delta": delta.to_dict(),
            "ranking": {
                "posts_ranked": len(ranked_posts),
                "profiles_ranked": len(ranked_profiles),
                "comment_candidates": [
                    {
                        "urn": item.urn,
                        "author_name": item.author_name,
                        "score": item.score,
                        "decision": item.decision,
                        "reasons": item.reasons,
                    }
                    for item in comment_candidates
                ],
                "comment_report": comment_report.to_dict(),
                "connection_candidates": [
                    {
                        "urn": item.urn,
                        "full_name": item.full_name,
                        "score": item.score,
                        "decision": item.decision,
                        "reasons": item.reasons,
                    }
                    for item in connection_candidates
                ],
                "profile_report": profile_report.to_dict(),
                "skipped_posts": delta.skipped_posts,
                "skipped_profiles": delta.skipped_profiles,
            },
            "knowledge_overview": overview,
        }
        return summary, snapshot.notes

    return run_cli_job("daily_refresh_knowledge", _handler)


if __name__ == "__main__":
    raise SystemExit(main())
