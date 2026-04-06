import sqlite3

from linkedin_agent.modules.knowledge_store import SectorKnowledgeStore


def test_init_db_migrates_legacy_tables_without_runtime_default_errors(tmp_path):
    db_path = tmp_path / "activity_log.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE sector_posts (
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
            first_seen_at TEXT DEFAULT (datetime('now')),
            last_seen_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        INSERT INTO sector_posts
        (post_urn, post_url, author_name, text_raw, normalized_text)
        VALUES ('urn:test', 'https://linkedin.com/posts/test', 'Autore', 'Testo', 'testo')
        """
    )
    conn.commit()
    conn.close()

    store = SectorKnowledgeStore(db_path)
    store.init_db()

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT collected_at FROM sector_posts WHERE post_urn = 'urn:test'").fetchone()
    conn.close()

    assert row is not None
    assert row[0]
