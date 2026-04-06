"""
Generate multiple post variants from the latest persisted content brief.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from linkedin_agent.modules.content_generator import ContentGenerator
from linkedin_agent.modules.knowledge_types import ContentBrief
from linkedin_agent.modules.tracker import PostDraft
from linkedin_agent.scripts.cli_common import RecoverableCLIError, run_cli_job
from linkedin_agent.scripts.job_runtime import load_core_runtime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate post variants from the latest saved content brief.")
    parser.add_argument(
        "--brief-id",
        type=int,
        default=int(os.environ.get("CONTENT_BRIEF_ID", "0")) or None,
        help="Optional explicit content brief id to retry. If omitted, uses the latest brief.",
    )
    parser.add_argument(
        "--variants",
        type=int,
        default=int(os.environ.get("POST_VARIANTS_COUNT", "3")),
        help="How many variants to try to generate.",
    )
    return parser


def _brief_from_store(store, brief_id: int | None) -> tuple[int, ContentBrief]:
    row = store.get_brief(brief_id) if brief_id else store.get_latest_brief()
    if not row:
        if brief_id:
            raise RecoverableCLIError(f"Content brief {brief_id} non trovato nel database.")
        raise RecoverableCLIError("Nessun content brief disponibile nel database.")
    return row["id"], ContentBrief(**row["brief"])


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    def _handler(logger):
        settings, tracker, store, llm = load_core_runtime(require_llm=True)
        brief_id, brief = _brief_from_store(store, args.brief_id)
        generator = ContentGenerator(settings, llm, tracker)
        draft_set = generator.generate_post_variants(brief=brief, count=args.variants)

        minimum_expected = 2 if args.variants >= 2 else 1
        if len(draft_set.variants) < minimum_expected:
            raise RecoverableCLIError(
                f"Generate solo {len(draft_set.variants)} varianti valide dal brief {brief_id}; minimo richiesto {minimum_expected}."
            )

        saved_post_ids: list[int] = []
        for variant in draft_set.variants:
            post_id = tracker.log_post(
                PostDraft(
                    content=variant.content,
                    hashtags=variant.hashtags,
                    pillar=brief.angle_label,
                    format_type="brief_variant",
                    rationale=variant.rationale,
                    chosen_pattern=brief.selected_pattern,
                    context_sources=variant.context_sources,
                )
            )
            saved_post_ids.append(post_id)

        summary = {
            "brief_id": brief_id,
            "snapshot_id": brief.snapshot_id,
            "requested_variants": args.variants,
            "generated_variants": len(draft_set.variants),
            "saved_post_ids": saved_post_ids,
            "draft_set": {
                "brief": brief.to_dict(),
                "variants": [
                    {
                        "angle_label": variant.angle_label,
                        "content": variant.content,
                        "hashtags": variant.hashtags,
                        "rationale": variant.rationale,
                        "context_sources": variant.context_sources,
                        "editorial_score": variant.editorial_score,
                    }
                    for variant in draft_set.variants
                ],
            },
        }
        return summary, brief.notes

    return run_cli_job("generate_post_variants", _handler)


if __name__ == "__main__":
    raise SystemExit(main())
