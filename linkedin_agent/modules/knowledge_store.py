"""
Persistent sector knowledge store built on the same SQLite database used by the tracker.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from linkedin_agent.modules.knowledge_types import (
    ContentBrief,
    DailyDelta,
    MarketPattern,
    NormalizedPost,
    NormalizedProfile,
    SectorSignal,
)


class SectorKnowledgeStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_kind TEXT NOT NULL,
                    market_scope TEXT DEFAULT 'italy',
                    status TEXT DEFAULT 'ok',
                    summary_json TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS sector_posts (
                    post_urn TEXT PRIMARY KEY,
                    post_url TEXT,
                    author_name TEXT,
                    author_headline TEXT,
                    text_raw TEXT,
                    normalized_text TEXT,
                    reaction_count INTEGER DEFAULT 0,
                    comment_count INTEGER DEFAULT 0,
                    source_query TEXT DEFAULT '',
                    market_scope TEXT DEFAULT 'italy',
                    language TEXT DEFAULT 'it',
                    importance_score REAL DEFAULT 0.0,
                    topic_labels_json TEXT DEFAULT '[]',
                    collected_at TEXT DEFAULT (datetime('now')),
                    first_seen_at TEXT DEFAULT (datetime('now')),
                    last_seen_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS sector_profiles (
                    profile_urn TEXT PRIMARY KEY,
                    full_name TEXT,
                    headline TEXT,
                    location TEXT,
                    summary TEXT,
                    current_company TEXT,
                    profile_url TEXT,
                    source_query TEXT DEFAULT '',
                    market_scope TEXT DEFAULT 'italy',
                    relevance_score REAL DEFAULT 0.0,
                    role_labels_json TEXT DEFAULT '[]',
                    collected_at TEXT DEFAULT (datetime('now')),
                    first_seen_at TEXT DEFAULT (datetime('now')),
                    last_seen_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS sector_signals (
                    signal_key TEXT PRIMARY KEY,
                    signal_type TEXT NOT NULL,
                    label TEXT NOT NULL,
                    evidence_json TEXT DEFAULT '[]',
                    market_scope TEXT DEFAULT 'italy',
                    strength_score REAL DEFAULT 0.0,
                    collected_at TEXT DEFAULT (datetime('now')),
                    first_seen_at TEXT DEFAULT (datetime('now')),
                    last_seen_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS market_patterns (
                    pattern_key TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    summary TEXT DEFAULT '',
                    evidence_json TEXT DEFAULT '[]',
                    market_scope TEXT DEFAULT 'italy',
                    score REAL DEFAULT 0.0,
                    collected_at TEXT DEFAULT (datetime('now')),
                    first_seen_at TEXT DEFAULT (datetime('now')),
                    last_seen_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS content_briefs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id INTEGER,
                    angle_label TEXT NOT NULL,
                    brief_json TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS daily_deltas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id INTEGER,
                    delta_json TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS external_research_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    source_kind TEXT DEFAULT 'web',
                    summary TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS bootstrap_checkpoints (
                    job_name TEXT PRIMARY KEY,
                    status TEXT DEFAULT 'running',
                    phase TEXT DEFAULT '',
                    cursor_json TEXT DEFAULT '{}',
                    payload_json TEXT DEFAULT '{}',
                    last_error TEXT DEFAULT '',
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                """
            )
            self._ensure_column(conn, "sector_posts", "collected_at", "TEXT DEFAULT (datetime('now'))")
            self._ensure_column(conn, "sector_profiles", "collected_at", "TEXT DEFAULT (datetime('now'))")
            self._ensure_column(conn, "sector_signals", "collected_at", "TEXT DEFAULT (datetime('now'))")
            self._ensure_column(conn, "market_patterns", "collected_at", "TEXT DEFAULT (datetime('now'))")

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            # SQLite does not allow adding a column with a non-constant default
            # (for example DEFAULT (datetime('now'))) through ALTER TABLE.
            # For legacy databases we therefore add the column without that
            # runtime default and immediately backfill existing rows. Fresh
            # databases still get the richer CREATE TABLE definitions above.
            alter_definition = definition
            if "DEFAULT (datetime('now'))" in definition:
                alter_definition = definition.replace(" DEFAULT (datetime('now'))", "")
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {alter_definition}")
            if column == "collected_at":
                conn.execute(
                    f"""
                    UPDATE {table}
                    SET {column} = datetime('now')
                    WHERE {column} IS NULL OR {column} = ''
                    """
                )

    def log_knowledge_run(self, run_kind: str, market_scope: str, status: str, summary: dict) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO knowledge_runs (run_kind, market_scope, status, summary_json)
                VALUES (?, ?, ?, ?)
                """,
                (run_kind, market_scope, status, json.dumps(summary)),
            )
            return cur.lastrowid

    def upsert_sector_post(self, post: NormalizedPost) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO sector_posts
                (post_urn, post_url, author_name, author_headline, text_raw, normalized_text,
                 reaction_count, comment_count, source_query, market_scope, language,
                 importance_score, topic_labels_json, collected_at, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), datetime('now'))
                ON CONFLICT(post_urn) DO UPDATE SET
                    post_url=excluded.post_url,
                    author_name=excluded.author_name,
                    author_headline=excluded.author_headline,
                    text_raw=excluded.text_raw,
                    normalized_text=excluded.normalized_text,
                    reaction_count=excluded.reaction_count,
                    comment_count=excluded.comment_count,
                    source_query=excluded.source_query,
                    market_scope=excluded.market_scope,
                    language=excluded.language,
                    importance_score=excluded.importance_score,
                    topic_labels_json=excluded.topic_labels_json,
                    collected_at=datetime('now'),
                    last_seen_at=datetime('now')
                """,
                (
                    post.urn,
                    post.url,
                    post.author_name,
                    post.author_headline,
                    post.text,
                    post.normalized_text,
                    post.reaction_count,
                    post.comment_count,
                    post.source_query,
                    post.market_scope,
                    post.language,
                    post.importance_score,
                    json.dumps(post.topic_labels),
                ),
            )

    def upsert_sector_profile(self, profile: NormalizedProfile) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO sector_profiles
                (profile_urn, full_name, headline, location, summary, current_company, profile_url,
                 source_query, market_scope, relevance_score, role_labels_json, collected_at, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), datetime('now'))
                ON CONFLICT(profile_urn) DO UPDATE SET
                    full_name=excluded.full_name,
                    headline=excluded.headline,
                    location=excluded.location,
                    summary=excluded.summary,
                    current_company=excluded.current_company,
                    profile_url=excluded.profile_url,
                    source_query=excluded.source_query,
                    market_scope=excluded.market_scope,
                    relevance_score=excluded.relevance_score,
                    role_labels_json=excluded.role_labels_json,
                    collected_at=datetime('now'),
                    last_seen_at=datetime('now')
                """,
                (
                    profile.urn,
                    profile.full_name,
                    profile.headline,
                    profile.location,
                    profile.summary,
                    profile.current_company,
                    profile.profile_url,
                    profile.source_query,
                    profile.market_scope,
                    profile.relevance_score,
                    json.dumps(profile.role_labels),
                ),
            )

    def upsert_signal(self, signal: SectorSignal) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO sector_signals
                (signal_key, signal_type, label, evidence_json, market_scope, strength_score, collected_at, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), datetime('now'))
                ON CONFLICT(signal_key) DO UPDATE SET
                    signal_type=excluded.signal_type,
                    label=excluded.label,
                    evidence_json=excluded.evidence_json,
                    market_scope=excluded.market_scope,
                    strength_score=MAX(sector_signals.strength_score, excluded.strength_score),
                    collected_at=datetime('now'),
                    last_seen_at=datetime('now')
                """,
                (
                    signal.signal_key,
                    signal.signal_type,
                    signal.label,
                    json.dumps(signal.evidence),
                    signal.market_scope,
                    signal.strength_score,
                ),
            )

    def upsert_pattern(self, pattern: MarketPattern) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO market_patterns
                (pattern_key, label, summary, evidence_json, market_scope, score, collected_at, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), datetime('now'))
                ON CONFLICT(pattern_key) DO UPDATE SET
                    label=excluded.label,
                    summary=excluded.summary,
                    evidence_json=excluded.evidence_json,
                    market_scope=excluded.market_scope,
                    score=MAX(market_patterns.score, excluded.score),
                    collected_at=datetime('now'),
                    last_seen_at=datetime('now')
                """,
                (
                    pattern.pattern_key,
                    pattern.label,
                    pattern.summary,
                    json.dumps(pattern.evidence),
                    pattern.market_scope,
                    pattern.score,
                ),
            )

    def save_content_brief(self, brief: ContentBrief) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO content_briefs (snapshot_id, angle_label, brief_json)
                VALUES (?, ?, ?)
                """,
                (brief.snapshot_id, brief.angle_label, json.dumps(brief.to_dict())),
            )
            return cur.lastrowid

    def log_daily_delta(self, delta: DailyDelta) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO daily_deltas (snapshot_id, delta_json)
                VALUES (?, ?)
                """,
                (delta.snapshot_id, json.dumps(delta.to_dict())),
            )
            return cur.lastrowid

    def _decay_after_days(self) -> int:
        return int(os.environ.get("KNOWLEDGE_DECAY_AFTER_DAYS", "30"))

    def _archive_after_days(self) -> int:
        return int(os.environ.get("KNOWLEDGE_ARCHIVE_AFTER_DAYS", "90"))

    def _decayed_score_sql(self, base_column: str) -> str:
        decay_after = self._decay_after_days()
        archive_after = self._archive_after_days()
        return f"""
            ({base_column}) * CASE
                WHEN julianday('now') - julianday(COALESCE(collected_at, last_seen_at, first_seen_at)) > {archive_after}
                    THEN 0.0
                WHEN julianday('now') - julianday(COALESCE(collected_at, last_seen_at, first_seen_at)) > {decay_after}
                    THEN 0.5
                ELSE 1.0
            END
        """

    def get_top_sector_posts(self, limit: int = 20, market_scope: Optional[str] = None) -> list[dict]:
        query = """
            SELECT *, {score_sql} AS ranking_score
            FROM sector_posts
        """.format(score_sql=self._decayed_score_sql("importance_score"))
        params: list[object] = []
        if market_scope:
            query += " WHERE market_scope = ?"
            params.append(market_scope)
        query += " ORDER BY ranking_score DESC, datetime(last_seen_at) DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_top_sector_profiles(self, limit: int = 20, market_scope: Optional[str] = None) -> list[dict]:
        query = """
            SELECT *, {score_sql} AS ranking_score
            FROM sector_profiles
        """.format(score_sql=self._decayed_score_sql("relevance_score"))
        params: list[object] = []
        if market_scope:
            query += " WHERE market_scope = ?"
            params.append(market_scope)
        query += " ORDER BY ranking_score DESC, datetime(last_seen_at) DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_top_signals(self, limit: int = 15) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT *, {score_sql} AS ranking_score
                FROM sector_signals
                ORDER BY ranking_score DESC, datetime(last_seen_at) DESC
                LIMIT ?
                """.format(score_sql=self._decayed_score_sql("strength_score")),
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_top_patterns(self, limit: int = 10) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT *, {score_sql} AS ranking_score
                FROM market_patterns
                ORDER BY ranking_score DESC, datetime(last_seen_at) DESC
                LIMIT ?
                """.format(score_sql=self._decayed_score_sql("score")),
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_bootstrap_checkpoint(
        self,
        *,
        job_name: str,
        status: str,
        phase: str,
        cursor: dict,
        payload: dict,
        last_error: str = "",
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO bootstrap_checkpoints
                (job_name, status, phase, cursor_json, payload_json, last_error, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(job_name) DO UPDATE SET
                    status=excluded.status,
                    phase=excluded.phase,
                    cursor_json=excluded.cursor_json,
                    payload_json=excluded.payload_json,
                    last_error=excluded.last_error,
                    updated_at=datetime('now')
                """,
                (job_name, status, phase, json.dumps(cursor), json.dumps(payload), last_error),
            )

    def get_bootstrap_checkpoint(self, job_name: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT job_name, status, phase, cursor_json, payload_json, last_error, updated_at
                FROM bootstrap_checkpoints
                WHERE job_name = ?
                """,
                (job_name,),
            ).fetchone()
        if not row:
            return None
        return {
            "job_name": row["job_name"],
            "status": row["status"],
            "phase": row["phase"],
            "cursor": json.loads(row["cursor_json"]) if row["cursor_json"] else {},
            "payload": json.loads(row["payload_json"]) if row["payload_json"] else {},
            "last_error": row["last_error"] or "",
            "updated_at": row["updated_at"],
        }

    def clear_bootstrap_checkpoint(self, job_name: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM bootstrap_checkpoints WHERE job_name = ?", (job_name,))

    def cleanup_stale_knowledge(self, archive_after_days: Optional[int] = None) -> dict[str, int]:
        threshold = archive_after_days or self._archive_after_days()
        deleted: dict[str, int] = {}
        with self._conn() as conn:
            for table in ["sector_posts", "sector_profiles", "sector_signals", "market_patterns"]:
                cur = conn.execute(
                    f"""
                    DELETE FROM {table}
                    WHERE julianday('now') - julianday(COALESCE(collected_at, last_seen_at, first_seen_at)) > ?
                    """,
                    (threshold,),
                )
                deleted[table] = cur.rowcount
        return deleted

    def get_latest_brief(self) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, snapshot_id, angle_label, brief_json, created_at
                FROM content_briefs
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "snapshot_id": row["snapshot_id"],
            "angle_label": row["angle_label"],
            "brief": json.loads(row["brief_json"]),
            "created_at": row["created_at"],
        }

    def get_brief(self, brief_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, snapshot_id, angle_label, brief_json, created_at
                FROM content_briefs
                WHERE id = ?
                LIMIT 1
                """,
                (brief_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "snapshot_id": row["snapshot_id"],
            "angle_label": row["angle_label"],
            "brief": json.loads(row["brief_json"]),
            "created_at": row["created_at"],
        }

    def get_latest_delta(self) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, snapshot_id, delta_json, created_at
                FROM daily_deltas
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "snapshot_id": row["snapshot_id"],
            "delta": json.loads(row["delta_json"]),
            "created_at": row["created_at"],
        }

    def get_latest_knowledge_run(self) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, run_kind, market_scope, status, summary_json, created_at
                FROM knowledge_runs
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "run_kind": row["run_kind"],
            "market_scope": row["market_scope"],
            "status": row["status"],
            "summary": json.loads(row["summary_json"]) if row["summary_json"] else {},
            "created_at": row["created_at"],
        }

    def get_overview(self) -> dict:
        with self._conn() as conn:
            posts = conn.execute("SELECT COUNT(*) FROM sector_posts").fetchone()[0]
            profiles = conn.execute("SELECT COUNT(*) FROM sector_profiles").fetchone()[0]
            signals = conn.execute("SELECT COUNT(*) FROM sector_signals").fetchone()[0]
            patterns = conn.execute("SELECT COUNT(*) FROM market_patterns").fetchone()[0]
            briefs = conn.execute("SELECT COUNT(*) FROM content_briefs").fetchone()[0]
            deltas = conn.execute("SELECT COUNT(*) FROM daily_deltas").fetchone()[0]
        return {
            "sector_posts": posts,
            "sector_profiles": profiles,
            "sector_signals": signals,
            "market_patterns": patterns,
            "content_briefs": briefs,
            "daily_deltas": deltas,
        }
