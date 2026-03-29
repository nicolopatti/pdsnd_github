"""
SQLite-backed activity tracker.
Single source of truth for deduplication, daily limits, and progress reporting.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
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
    id: Optional[int] = None
    status: str = "pending"   # pending | approved | rejected | published
    created_at: Optional[str] = None
    published_at: Optional[str] = None
    linkedin_post_urn: Optional[str] = None
    style_feedback: Optional[str] = None   # JSON string from StrategyAdvisor


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

                CREATE TABLE IF NOT EXISTS profiles_seen (
                    profile_urn TEXT PRIMARY KEY,
                    first_seen_at TEXT DEFAULT (datetime('now')),
                    relevance_score REAL DEFAULT 0.0,
                    action_taken TEXT DEFAULT 'none'
                );
            """)

    # ------------------------------------------------------------------
    # Posts
    # ------------------------------------------------------------------

    def log_post(self, draft: PostDraft) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO posts (content, hashtags, pillar, format_type, status, style_feedback)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    draft.content,
                    ",".join(draft.hashtags),
                    draft.pillar,
                    draft.format_type,
                    draft.status,
                    draft.style_feedback,
                ),
            )
            return cur.lastrowid

    def update_post_status(self, post_id: int, status: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE posts SET status=? WHERE id=?", (status, post_id))

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

    def mark_profile_seen(self, profile_urn: str, score: float = 0.0) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO profiles_seen (profile_urn, relevance_score) VALUES (?, ?)",
                (profile_urn, score),
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
        today = date.today().isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM comments WHERE status IN ('approved','published') AND date(created_at)=?",
                (today,),
            ).fetchone()
        return row[0]

    def get_daily_reaction_count(self) -> int:
        today = date.today().isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM reactions WHERE status IN ('approved','done') AND date(created_at)=?",
                (today,),
            ).fetchone()
        return row[0]

    def get_daily_connection_count(self) -> int:
        today = date.today().isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM connections WHERE status IN ('approved','sent','connected') AND date(requested_at)=?",
                (today,),
            ).fetchone()
        return row[0]

    def get_weekly_post_count(self) -> int:
        monday = (date.today() - timedelta(days=date.today().weekday())).isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM posts WHERE status IN ('approved','published') AND date(created_at)>=?",
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
            },
            "this_week": {"posts": this_week_posts},
            "today": {
                "comments": today_comments,
                "reactions": today_reactions,
                "connections": today_connections,
            },
        }
