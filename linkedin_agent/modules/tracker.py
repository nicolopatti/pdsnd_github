"""
SQLite-backed activity tracker.
Single source of truth for deduplication, daily limits, and progress reporting.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Dataclasses used across modules
# ---------------------------------------------------------------------------

@dataclass
class PostDraft:
    content: str
    hashtags: list[str]
    pillar: str
    format_type: str
    rationale: str = ""
    chosen_pattern: str = ""
    context_sources: list[str] = None
    id: Optional[int] = None
    status: str = "pending"   # pending | approved | rejected | published
    created_at: Optional[str] = None
    published_at: Optional[str] = None
    linkedin_post_urn: Optional[str] = None
    style_feedback: Optional[str] = None   # JSON string from StrategyAdvisor

    def __post_init__(self) -> None:
        if self.context_sources is None:
            self.context_sources = []


@dataclass
class PostGenerationResult:
    status: str  # ok | invalid_ai_output | insufficient_context | provider_error
    draft: Optional[PostDraft] = None
    error_message: str = ""
    raw_response_excerpt: str = ""
    validation_errors: list[str] = None
    snapshot_id: Optional[int] = None
    run_id: Optional[int] = None
    created_at: Optional[str] = None

    def __post_init__(self) -> None:
        if self.validation_errors is None:
            self.validation_errors = []

    @property
    def is_ok(self) -> bool:
        return self.status == "ok" and self.draft is not None


@dataclass
class CommentDraft:
    post_urn: str
    post_url: str
    post_author: str
    post_text_snippet: str
    comment_text: str
    relevance_score: float
    id: Optional[int] = None
    status: str = "pending"   # pending | approved | rejected | published
    created_at: Optional[str] = None
    published_at: Optional[str] = None


@dataclass
class ConnectionRequest:
    profile_urn: str
    full_name: str
    headline: str
    profile_url: str
    relevance_score: float
    motivation: str           # Why this person is worth connecting with
    id: Optional[int] = None
    status: str = "pending"   # pending | approved | rejected | sent | connected
    requested_at: Optional[str] = None


@dataclass
class ReactionItem:
    post_urn: str
    post_url: str
    post_author: str
    post_text_snippet: str
    reaction_type: str        # "like" or "repost"
    motivation: str
    id: Optional[int] = None
    status: str = "pending"   # pending | approved | rejected | done
    created_at: Optional[str] = None
    done_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

class ActivityTracker:
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

    # ------------------------------------------------------------------
    # Schema creation
    # ------------------------------------------------------------------

    def init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    hashtags TEXT,
                    pillar TEXT,
                    format_type TEXT,
                    rationale TEXT DEFAULT '',
                    chosen_pattern TEXT DEFAULT '',
                    context_sources TEXT DEFAULT '[]',
                    status TEXT DEFAULT 'pending',
                    style_feedback TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    published_at TEXT,
                    linkedin_post_urn TEXT
                );

                CREATE TABLE IF NOT EXISTS comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_urn TEXT NOT NULL,
                    post_url TEXT,
                    post_author TEXT,
                    post_text_snippet TEXT,
                    comment_text TEXT NOT NULL,
                    relevance_score REAL DEFAULT 0.0,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT DEFAULT (datetime('now')),
                    published_at TEXT
                );

                CREATE TABLE IF NOT EXISTS connections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_urn TEXT NOT NULL UNIQUE,
                    full_name TEXT,
                    headline TEXT,
                    profile_url TEXT,
                    relevance_score REAL DEFAULT 0.0,
                    motivation TEXT,
                    status TEXT DEFAULT 'pending',
                    requested_at TEXT,
                    connected_at TEXT
                );

                CREATE TABLE IF NOT EXISTS reactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_urn TEXT NOT NULL,
                    post_url TEXT,
                    post_author TEXT,
                    post_text_snippet TEXT,
                    reaction_type TEXT DEFAULT 'like',
                    motivation TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT DEFAULT (datetime('now')),
                    done_at TEXT
                );

                CREATE TABLE IF NOT EXISTS feed_posts_seen (
                    post_urn TEXT PRIMARY KEY,
                    first_seen_at TEXT DEFAULT (datetime('now')),
                    relevance_score REAL DEFAULT 0.0,
                    acted_on INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS recent_posts_seen (
                    post_urn TEXT PRIMARY KEY,
                    post_url TEXT,
                    author_name TEXT,
                    author_headline TEXT,
                    text_snippet TEXT,
                    reaction_count INTEGER DEFAULT 0,
                    comment_count INTEGER DEFAULT 0,
                    source_query TEXT DEFAULT '',
                    first_seen_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS niche_posts_seen (
                    post_urn TEXT PRIMARY KEY,
                    post_url TEXT,
                    author_name TEXT,
                    author_headline TEXT,
                    text_snippet TEXT,
                    reaction_count INTEGER DEFAULT 0,
                    comment_count INTEGER DEFAULT 0,
                    source_query TEXT DEFAULT '',
                    first_seen_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS profiles_seen (
                    profile_urn TEXT PRIMARY KEY,
                    first_seen_at TEXT DEFAULT (datetime('now')),
                    relevance_score REAL DEFAULT 0.0,
                    action_taken TEXT DEFAULT 'none',
                    full_name TEXT DEFAULT '',
                    headline TEXT DEFAULT '',
                    profile_url TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS profile_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT,
                    headline TEXT,
                    about_text TEXT,
                    featured_json TEXT DEFAULT '[]',
                    experience_json TEXT DEFAULT '[]',
                    profile_url TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS context_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_kind TEXT DEFAULT 'daily_plan',
                    status TEXT DEFAULT 'insufficient',
                    summary_json TEXT NOT NULL,
                    notes_json TEXT DEFAULT '[]',
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS post_generation_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id INTEGER,
                    model TEXT DEFAULT '',
                    status TEXT NOT NULL,
                    error_message TEXT DEFAULT '',
                    raw_excerpt TEXT DEFAULT '',
                    validation_errors_json TEXT DEFAULT '[]',
                    draft_post_id INTEGER,
                    created_at TEXT DEFAULT (datetime('now'))
                );
            """)
            self._ensure_column(conn, "posts", "rationale", "TEXT DEFAULT ''")
            self._ensure_column(conn, "posts", "chosen_pattern", "TEXT DEFAULT ''")
            self._ensure_column(conn, "posts", "context_sources", "TEXT DEFAULT '[]'")
            self._ensure_column(conn, "profiles_seen", "full_name", "TEXT DEFAULT ''")
            self._ensure_column(conn, "profiles_seen", "headline", "TEXT DEFAULT ''")
            self._ensure_column(conn, "profiles_seen", "profile_url", "TEXT DEFAULT ''")

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    # ------------------------------------------------------------------
    # Posts
    # ------------------------------------------------------------------

    def log_post(self, draft: PostDraft) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO posts
                   (content, hashtags, pillar, format_type, rationale, chosen_pattern, context_sources, status, style_feedback)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    draft.content,
                    ",".join(draft.hashtags),
                    draft.pillar,
                    draft.format_type,
                    draft.rationale,
                    draft.chosen_pattern,
                    json.dumps(draft.context_sources),
                    draft.status,
                    draft.style_feedback,
                ),
            )
            return cur.lastrowid

    def update_post_status(self, post_id: int, status: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE posts SET status=? WHERE id=?", (status, post_id))

    def update_post_content(self, post_id: int, content: str, hashtags: list[str]) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE posts SET content=?, hashtags=? WHERE id=?",
                (content, ",".join(hashtags), post_id),
            )

    def mark_post_published(self, post_id: int, urn: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE posts SET status='published', published_at=datetime('now'), linkedin_post_urn=? WHERE id=?",
                (urn, post_id),
            )

    def get_pending_posts(self) -> list[PostDraft]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM posts WHERE status='pending' ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_post(r) for r in rows]

    def get_approved_posts(self) -> list[PostDraft]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM posts WHERE status='approved' ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_post(r) for r in rows]

    def get_published_posts(self, since_days: int = 30) -> list[PostDraft]:
        since = (datetime.now() - timedelta(days=since_days)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM posts WHERE status='published' AND published_at >= ? ORDER BY published_at DESC",
                (since,),
            ).fetchall()
        return [self._row_to_post(r) for r in rows]

    def _row_to_post(self, r: sqlite3.Row) -> PostDraft:
        return PostDraft(
            id=r["id"],
            content=r["content"],
            hashtags=r["hashtags"].split(",") if r["hashtags"] else [],
            pillar=r["pillar"] or "",
            format_type=r["format_type"] or "",
            rationale=r["rationale"] or "",
            chosen_pattern=r["chosen_pattern"] or "",
            context_sources=json.loads(r["context_sources"]) if r["context_sources"] else [],
            status=r["status"],
            style_feedback=r["style_feedback"],
            created_at=r["created_at"],
            published_at=r["published_at"],
            linkedin_post_urn=r["linkedin_post_urn"],
        )

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    def log_comment(self, draft: CommentDraft) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO comments
                   (post_urn, post_url, post_author, post_text_snippet, comment_text, relevance_score, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    draft.post_urn,
                    draft.post_url,
                    draft.post_author,
                    draft.post_text_snippet,
                    draft.comment_text,
                    draft.relevance_score,
                    draft.status,
                ),
            )
            return cur.lastrowid

    def update_comment_status(self, comment_id: int, status: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE comments SET status=? WHERE id=?", (status, comment_id))

    def mark_comment_published(self, comment_id: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE comments SET status='published', published_at=datetime('now') WHERE id=?",
                (comment_id,),
            )

    def get_pending_comments(self) -> list[CommentDraft]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM comments WHERE status='pending' ORDER BY relevance_score DESC"
            ).fetchall()
        return [self._row_to_comment(r) for r in rows]

    def get_approved_comments(self) -> list[CommentDraft]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM comments WHERE status='approved' ORDER BY relevance_score DESC"
            ).fetchall()
        return [self._row_to_comment(r) for r in rows]

    def _row_to_comment(self, r: sqlite3.Row) -> CommentDraft:
        return CommentDraft(
            id=r["id"],
            post_urn=r["post_urn"],
            post_url=r["post_url"] or "",
            post_author=r["post_author"] or "",
            post_text_snippet=r["post_text_snippet"] or "",
            comment_text=r["comment_text"],
            relevance_score=r["relevance_score"],
            status=r["status"],
            created_at=r["created_at"],
            published_at=r["published_at"],
        )

    # ------------------------------------------------------------------
    # Connections
    # ------------------------------------------------------------------

    def log_connection(self, req: ConnectionRequest) -> Optional[int]:
        with self._conn() as conn:
            try:
                cur = conn.execute(
                    """INSERT INTO connections
                       (profile_urn, full_name, headline, profile_url, relevance_score, motivation, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        req.profile_urn,
                        req.full_name,
                        req.headline,
                        req.profile_url,
                        req.relevance_score,
                        req.motivation,
                        req.status,
                    ),
                )
                return cur.lastrowid
            except sqlite3.IntegrityError:
                return None  # Already seen

    def update_connection_status(self, conn_id: int, status: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE connections SET status=? WHERE id=?", (status, conn_id))

    def mark_connection_sent(self, conn_id: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE connections SET status='sent', requested_at=datetime('now') WHERE id=?",
                (conn_id,),
            )

    def get_pending_connections(self) -> list[ConnectionRequest]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM connections WHERE status='pending' ORDER BY relevance_score DESC"
            ).fetchall()
        return [self._row_to_connection(r) for r in rows]

    def get_approved_connections(self) -> list[ConnectionRequest]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM connections WHERE status='approved' ORDER BY relevance_score DESC"
            ).fetchall()
        return [self._row_to_connection(r) for r in rows]

    def _row_to_connection(self, r: sqlite3.Row) -> ConnectionRequest:
        return ConnectionRequest(
            id=r["id"],
            profile_urn=r["profile_urn"],
            full_name=r["full_name"] or "",
            headline=r["headline"] or "",
            profile_url=r["profile_url"] or "",
            relevance_score=r["relevance_score"],
            motivation=r["motivation"] or "",
            status=r["status"],
            requested_at=r["requested_at"],
        )

    # ------------------------------------------------------------------
    # Reactions
    # ------------------------------------------------------------------

    def log_reaction(self, item: ReactionItem) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO reactions
                   (post_urn, post_url, post_author, post_text_snippet, reaction_type, motivation, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.post_urn,
                    item.post_url,
                    item.post_author,
                    item.post_text_snippet,
                    item.reaction_type,
                    item.motivation,
                    item.status,
                ),
            )
            return cur.lastrowid

    def update_reaction_status(self, reaction_id: int, status: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE reactions SET status=? WHERE id=?", (status, reaction_id))

    def mark_reaction_done(self, reaction_id: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE reactions SET status='done', done_at=datetime('now') WHERE id=?",
                (reaction_id,),
            )

    def get_pending_reactions(self) -> list[ReactionItem]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM reactions WHERE status='pending'"
            ).fetchall()
        return [self._row_to_reaction(r) for r in rows]

    def get_approved_reactions(self) -> list[ReactionItem]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM reactions WHERE status='approved'"
            ).fetchall()
        return [self._row_to_reaction(r) for r in rows]

    def _row_to_reaction(self, r: sqlite3.Row) -> ReactionItem:
        return ReactionItem(
            id=r["id"],
            post_urn=r["post_urn"],
            post_url=r["post_url"] or "",
            post_author=r["post_author"] or "",
            post_text_snippet=r["post_text_snippet"] or "",
            reaction_type=r["reaction_type"],
            motivation=r["motivation"] or "",
            status=r["status"],
            created_at=r["created_at"],
            done_at=r["done_at"],
        )

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def mark_post_seen(self, post_urn: str, score: float = 0.0) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO feed_posts_seen (post_urn, relevance_score) VALUES (?, ?)",
                (post_urn, score),
            )

    def is_post_seen(self, post_urn: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM feed_posts_seen WHERE post_urn=?", (post_urn,)
            ).fetchone()
        return row is not None

    def mark_profile_seen(
        self,
        profile_urn: str,
        score: float = 0.0,
        full_name: str = "",
        headline: str = "",
        profile_url: str = "",
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO profiles_seen
                (profile_urn, relevance_score, full_name, headline, profile_url)
                VALUES (?, ?, ?, ?, ?)
                """,
                (profile_urn, score, full_name, headline, profile_url),
            )
            conn.execute(
                """
                UPDATE profiles_seen
                SET relevance_score=?,
                    full_name=CASE WHEN ? != '' THEN ? ELSE full_name END,
                    headline=CASE WHEN ? != '' THEN ? ELSE headline END,
                    profile_url=CASE WHEN ? != '' THEN ? ELSE profile_url END
                WHERE profile_urn=?
                """,
                (
                    score,
                    full_name, full_name,
                    headline, headline,
                    profile_url, profile_url,
                    profile_urn,
                ),
            )

    def is_profile_seen(self, profile_urn: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM profiles_seen WHERE profile_urn=?", (profile_urn,)
            ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Daily / weekly counters
    # ------------------------------------------------------------------

    def get_daily_comment_count(self) -> int:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*)
                FROM comments
                WHERE status IN ('approved','published')
                  AND date(created_at, 'localtime') = date('now', 'localtime')
                """
            ).fetchone()
        return row[0]

    def get_daily_reaction_count(self) -> int:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*)
                FROM reactions
                WHERE status IN ('approved','done')
                  AND date(created_at, 'localtime') = date('now', 'localtime')
                """
            ).fetchone()
        return row[0]

    def get_daily_connection_count(self) -> int:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*)
                FROM connections
                WHERE status IN ('approved','sent','connected')
                  AND date(requested_at, 'localtime') = date('now', 'localtime')
                """
            ).fetchone()
        return row[0]

    def get_weekly_post_count(self) -> int:
        monday = (date.today() - timedelta(days=date.today().weekday())).isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM posts WHERE status IN ('approved','published') AND date(created_at, 'localtime')>=?",
                (monday,),
            ).fetchone()
        return row[0]

    # ------------------------------------------------------------------
    # Progress report
    # ------------------------------------------------------------------

    def export_progress_report(self) -> dict:
        with self._conn() as conn:
            total_posts = conn.execute("SELECT COUNT(*) FROM posts WHERE status='published'").fetchone()[0]
            total_comments = conn.execute("SELECT COUNT(*) FROM comments WHERE status='published'").fetchone()[0]
            total_connections = conn.execute("SELECT COUNT(*) FROM connections WHERE status IN ('sent','connected')").fetchone()[0]
            total_reactions = conn.execute("SELECT COUNT(*) FROM reactions WHERE status='done'").fetchone()[0]
            total_profiles_seen = conn.execute("SELECT COUNT(*) FROM profiles_seen").fetchone()[0]
            total_recent_posts = conn.execute("SELECT COUNT(*) FROM recent_posts_seen").fetchone()[0]
            total_niche_posts = conn.execute("SELECT COUNT(*) FROM niche_posts_seen").fetchone()[0]
            total_context_runs = conn.execute("SELECT COUNT(*) FROM context_runs").fetchone()[0]
            total_post_generation_runs = conn.execute("SELECT COUNT(*) FROM post_generation_runs").fetchone()[0]
            this_week_posts = self.get_weekly_post_count()
            today_comments = self.get_daily_comment_count()
            today_reactions = self.get_daily_reaction_count()
            today_connections = self.get_daily_connection_count()
        return {
            "all_time": {
                "posts_published": total_posts,
                "comments_posted": total_comments,
                "connections_sent": total_connections,
                "reactions_done": total_reactions,
                "profiles_seen": total_profiles_seen,
                "recent_posts_seen": total_recent_posts,
                "niche_posts_seen": total_niche_posts,
                "context_runs": total_context_runs,
                "post_generation_runs": total_post_generation_runs,
            },
            "this_week": {"posts": this_week_posts},
            "today": {
                "comments": today_comments,
                "reactions": today_reactions,
                "connections": today_connections,
            },
        }

    def get_recent_seen_profiles(self, limit: int = 20) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT profile_urn, full_name, headline, profile_url, relevance_score, first_seen_at
                FROM profiles_seen
                ORDER BY datetime(first_seen_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "profile_urn": row["profile_urn"],
                "full_name": row["full_name"] or "",
                "headline": row["headline"] or "",
                "profile_url": row["profile_url"] or "",
                "relevance_score": row["relevance_score"] or 0.0,
                "first_seen_at": row["first_seen_at"] or "",
            }
            for row in rows
        ]

    def log_profile_snapshot(self, snapshot) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO profile_snapshots
                (full_name, headline, about_text, featured_json, experience_json, profile_url)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.full_name,
                    snapshot.headline,
                    snapshot.about,
                    json.dumps(snapshot.featured_items),
                    json.dumps(snapshot.experience_items),
                    snapshot.profile_url,
                ),
            )
            return cur.lastrowid

    def log_recent_post_seen(self, post) -> None:
        self._upsert_context_post("recent_posts_seen", post)

    def log_niche_post_seen(self, post) -> None:
        self._upsert_context_post("niche_posts_seen", post)

    def _upsert_context_post(self, table: str, post) -> None:
        with self._conn() as conn:
            conn.execute(
                f"""
                INSERT OR REPLACE INTO {table}
                (post_urn, post_url, author_name, author_headline, text_snippet, reaction_count, comment_count, source_query, first_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT first_seen_at FROM {table} WHERE post_urn=?), datetime('now')))
                """,
                (
                    post.urn,
                    post.url,
                    post.author_name,
                    post.author_headline,
                    post.text[:500],
                    post.reaction_count,
                    post.comment_count,
                    getattr(post, "source_query", ""),
                    post.urn,
                ),
            )

    def log_context_run(self, snapshot, run_kind: str = "daily_plan") -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO context_runs (run_kind, status, summary_json, notes_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    run_kind,
                    snapshot.status,
                    json.dumps(snapshot.to_dict()),
                    json.dumps(snapshot.notes),
                ),
            )
            return cur.lastrowid

    def get_latest_context_run(self) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, run_kind, status, summary_json, notes_json, created_at
                FROM context_runs
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "run_kind": row["run_kind"],
            "status": row["status"],
            "summary": json.loads(row["summary_json"]),
            "notes": json.loads(row["notes_json"]) if row["notes_json"] else [],
            "created_at": row["created_at"],
        }

    def log_post_generation_run(
        self,
        *,
        snapshot_id: Optional[int],
        model: str,
        status: str,
        error_message: str = "",
        raw_excerpt: str = "",
        validation_errors: Optional[list[str]] = None,
        draft_post_id: Optional[int] = None,
    ) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO post_generation_runs
                (snapshot_id, model, status, error_message, raw_excerpt, validation_errors_json, draft_post_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    model,
                    status,
                    error_message,
                    raw_excerpt[:800],
                    json.dumps(validation_errors or []),
                    draft_post_id,
                ),
            )
            return cur.lastrowid

    def get_latest_post_generation_run(self) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, snapshot_id, model, status, error_message, raw_excerpt,
                       validation_errors_json, draft_post_id, created_at
                FROM post_generation_runs
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "snapshot_id": row["snapshot_id"],
            "model": row["model"] or "",
            "status": row["status"],
            "error_message": row["error_message"] or "",
            "raw_excerpt": row["raw_excerpt"] or "",
            "validation_errors": json.loads(row["validation_errors_json"]) if row["validation_errors_json"] else [],
            "draft_post_id": row["draft_post_id"],
            "created_at": row["created_at"],
        }

    def get_recent_seen_posts(self, table: str, limit: int = 15) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT post_urn, post_url, author_name, author_headline, text_snippet,
                       reaction_count, comment_count, source_query, first_seen_at
                FROM {table}
                ORDER BY datetime(first_seen_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "post_urn": row["post_urn"],
                "post_url": row["post_url"] or "",
                "author_name": row["author_name"] or "",
                "author_headline": row["author_headline"] or "",
                "text_snippet": row["text_snippet"] or "",
                "reaction_count": row["reaction_count"] or 0,
                "comment_count": row["comment_count"] or 0,
                "source_query": row["source_query"] or "",
                "first_seen_at": row["first_seen_at"] or "",
            }
            for row in rows
        ]
