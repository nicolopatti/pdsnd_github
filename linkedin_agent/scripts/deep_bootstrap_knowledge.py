"""
Deep bootstrap entrypoint for the persistent knowledge base.

Designed for automation systems such as n8n:
- logs to stderr
- emits a single JSON result to stdout
- uses exit code 0/1/2 for success/recoverable/critical errors
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from linkedin_agent.automation.browser_reader import BrowserLinkedInReader
from linkedin_agent.modules.context_collector import ContextPost, ContextProfile, ContextSnapshot
from linkedin_agent.scripts.cli_common import RecoverableCLIError, run_cli_job
from linkedin_agent.scripts.job_runtime import (
    ensure_browser_session,
    ingest_snapshot,
    load_core_runtime,
    payload_to_snapshot,
    persist_snapshot,
    snapshot_to_payload,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap knowledge base from LinkedIn context.")
    parser.add_argument(
        "--market-scope",
        default=os.environ.get("BOOTSTRAP_MARKET_SCOPE", "italy"),
        help="Logical market scope label for the job metadata.",
    )
    parser.add_argument("--job-name", default=os.environ.get("BOOTSTRAP_JOB_NAME", "deep_bootstrap_default"))
    parser.add_argument("--post-limit-per-keyword", type=int, default=int(os.environ.get("BOOTSTRAP_POST_LIMIT_PER_KEYWORD", "8")))
    parser.add_argument("--profile-limit-per-title", type=int, default=int(os.environ.get("BOOTSTRAP_PROFILE_LIMIT_PER_TITLE", "8")))
    parser.add_argument("--own-post-limit", type=int, default=int(os.environ.get("BOOTSTRAP_OWN_POST_LIMIT", "8")))
    parser.add_argument("--max-requests", type=int, default=int(os.environ.get("BOOTSTRAP_MAX_REQUESTS", "12")))
    parser.add_argument("--min-delay", type=float, default=float(os.environ.get("BOOTSTRAP_MIN_DELAY_SECONDS", "3")))
    parser.add_argument("--max-delay", type=float, default=float(os.environ.get("BOOTSTRAP_MAX_DELAY_SECONDS", "5")))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    def _sleep_with_throttle(logger) -> None:
        delay = random.uniform(args.min_delay, args.max_delay)
        logger.info("Throttle %.2fs prima della prossima richiesta LinkedIn", delay)
        time.sleep(delay)

    def _is_recoverable_linkedin_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return any(token in text for token in ["429", "rate limit", "login", "not authenticated", "sessione browser", "challenge"])

    def _run_reader_call(logger, store, state, phase, func):
        backoff = 2.0
        attempts = 0
        while attempts < 3:
            try:
                return func()
            except Exception as exc:
                attempts += 1
                if _is_recoverable_linkedin_error(exc):
                    store.save_bootstrap_checkpoint(
                        job_name=args.job_name,
                        status="paused",
                        phase=phase,
                        cursor=state["cursor"],
                        payload=snapshot_to_payload(state["snapshot"]),
                        last_error=str(exc),
                    )
                    if attempts >= 3:
                        raise RecoverableCLIError(
                            f"Bootstrap fermato su `{phase}` dopo backoff esponenziale: {exc}"
                        ) from exc
                    logger.warning("Errore LinkedIn recuperabile su %s: %s. Retry tra %.1fs", phase, exc, backoff)
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise

    def _append_unique_posts(target: list[ContextPost], items: list, source_query: str) -> int:
        seen = {post.urn for post in target}
        added = 0
        for post in items:
            if not post.urn or post.urn in seen:
                continue
            target.append(
                ContextPost(
                    urn=post.urn,
                    url=post.url,
                    author_name=post.author_name,
                    author_headline=post.author_headline,
                    text=post.text,
                    reaction_count=post.reaction_count,
                    comment_count=post.comment_count,
                    published_at=post.published_at or "",
                    source_query=source_query,
                )
            )
            seen.add(post.urn)
            added += 1
        return added

    def _append_unique_profiles(target: list[ContextProfile], items: list, source_query: str) -> int:
        seen = {profile.profile_urn for profile in target}
        added = 0
        for profile in items:
            if not profile.urn or profile.urn in seen:
                continue
            target.append(
                ContextProfile(
                    profile_urn=profile.urn,
                    full_name=profile.full_name,
                    headline=profile.headline,
                    location=profile.location,
                    summary=profile.summary,
                    current_company=profile.current_company,
                    profile_url=profile.profile_url,
                    source_query=source_query,
                )
            )
            seen.add(profile.urn)
            added += 1
        return added

    def _handler(logger):
        settings, tracker, store, _ = load_core_runtime(require_llm=False)
        browser_detail = ensure_browser_session(settings)
        logger.info("Sessione browser valida: %s", browser_detail)
        reader = BrowserLinkedInReader(settings)
        checkpoint = store.get_bootstrap_checkpoint(args.job_name)
        if checkpoint and checkpoint.get("payload"):
            snapshot = payload_to_snapshot(checkpoint["payload"])
            cursor = checkpoint.get("cursor", {})
            logger.info("Riprendo bootstrap dal checkpoint `%s` (fase %s)", args.job_name, checkpoint.get("phase"))
        else:
            snapshot = ContextSnapshot(created_at=datetime.now().isoformat(timespec="seconds"))
            cursor = {"posts_keyword_index": 0, "profiles_title_index": 0, "requests_made": 0}

        state = {"snapshot": snapshot, "cursor": cursor}

        if cursor.get("requests_made", 0) >= args.max_requests:
            raise RecoverableCLIError("Limite massimo di richieste per sessione di bootstrap raggiunto.")

        if not snapshot.profile_snapshot:
            logger.info("Leggo il profilo principale")
            snapshot.profile_snapshot = _run_reader_call(logger, store, state, "own_profile", reader.get_own_profile)
            state["cursor"]["requests_made"] = state["cursor"].get("requests_made", 0) + 1
            store.save_bootstrap_checkpoint(
                job_name=args.job_name,
                status="running",
                phase="own_profile",
                cursor=state["cursor"],
                payload=snapshot_to_payload(snapshot),
            )
            _sleep_with_throttle(logger)

        if not snapshot.recent_posts_snapshot:
            logger.info("Leggo i post recenti del profilo")
            own_posts = _run_reader_call(
                logger,
                store,
                state,
                "own_recent_posts",
                lambda: reader.get_own_recent_posts(limit=args.own_post_limit),
            )
            _append_unique_posts(snapshot.recent_posts_snapshot, own_posts, "own_recent_posts")
            state["cursor"]["requests_made"] = state["cursor"].get("requests_made", 0) + 1
            store.save_bootstrap_checkpoint(
                job_name=args.job_name,
                status="running",
                phase="own_recent_posts",
                cursor=state["cursor"],
                payload=snapshot_to_payload(snapshot),
            )
            _sleep_with_throttle(logger)

        keywords = settings.niche.primary_keywords[:]
        for idx in range(cursor.get("posts_keyword_index", 0), len(keywords)):
            if state["cursor"].get("requests_made", 0) >= args.max_requests:
                raise RecoverableCLIError("Limite massimo di richieste per sessione di bootstrap raggiunto.")
            keyword = keywords[idx]
            logger.info("Cerco post per keyword %s (%s/%s)", keyword, idx + 1, len(keywords))
            posts = _run_reader_call(
                logger,
                store,
                state,
                f"posts:{keyword}",
                lambda kw=keyword: reader.search_sector_posts([kw], limit=args.post_limit_per_keyword),
            )
            added = _append_unique_posts(snapshot.niche_posts_snapshot, posts, keyword)
            logger.info("Aggiunti %s post per keyword %s (totale %s)", added, keyword, len(snapshot.niche_posts_snapshot))
            state["cursor"]["posts_keyword_index"] = idx + 1
            state["cursor"]["requests_made"] = state["cursor"].get("requests_made", 0) + 1
            store.save_bootstrap_checkpoint(
                job_name=args.job_name,
                status="running",
                phase=f"posts:{keyword}",
                cursor=state["cursor"],
                payload=snapshot_to_payload(snapshot),
            )
            _sleep_with_throttle(logger)

        titles = settings.target_profiles.job_titles[:]
        location = settings.target_profiles.locations[0] if settings.target_profiles.locations else ""
        for idx in range(cursor.get("profiles_title_index", 0), len(titles)):
            if state["cursor"].get("requests_made", 0) >= args.max_requests:
                raise RecoverableCLIError("Limite massimo di richieste per sessione di bootstrap raggiunto.")
            title = titles[idx]
            logger.info("Cerco profili per titolo %s (%s/%s)", title, idx + 1, len(titles))
            profiles = _run_reader_call(
                logger,
                store,
                state,
                f"profiles:{title}",
                lambda t=title: reader.search_sector_profiles([t], location=location, limit=args.profile_limit_per_title),
            )
            added = _append_unique_profiles(snapshot.niche_profiles_snapshot, profiles, title)
            logger.info("Aggiunti %s profili per titolo %s (totale %s)", added, title, len(snapshot.niche_profiles_snapshot))
            state["cursor"]["profiles_title_index"] = idx + 1
            state["cursor"]["requests_made"] = state["cursor"].get("requests_made", 0) + 1
            store.save_bootstrap_checkpoint(
                job_name=args.job_name,
                status="running",
                phase=f"profiles:{title}",
                cursor=state["cursor"],
                payload=snapshot_to_payload(snapshot),
            )
            _sleep_with_throttle(logger)

        snapshot.status = "sufficient" if snapshot.has_minimum_context else "insufficient"
        persist_snapshot(tracker, snapshot, run_kind="deep_bootstrap")
        delta, overview = ingest_snapshot(settings, store, snapshot, run_kind="bootstrap")
        store.clear_bootstrap_checkpoint(args.job_name)
        summary = {
            "market_scope": args.market_scope,
            "job_name": args.job_name,
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_status": snapshot.status,
            "counts": {
                "own_posts": snapshot.own_posts_count,
                "niche_posts": snapshot.niche_posts_count,
                "niche_profiles": snapshot.niche_profiles_count,
            },
            "requests_made": state["cursor"].get("requests_made", 0),
            "delta": delta.to_dict(),
            "knowledge_overview": overview,
        }
        return summary, snapshot.notes

    return run_cli_job("deep_bootstrap_knowledge", _handler)


if __name__ == "__main__":
    raise SystemExit(main())
