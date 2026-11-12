"""Database module for the Deep Research Engine.

Manages SQLite storage for sources and extracted facts with transactional integrity,
WAL mode for high efficiency, and safe connection lifecycles to protect low-RAM systems.
"""

import sqlite3
from contextlib import contextmanager
from typing import Dict, List, Optional, Tuple, Any
from config import DATABASE_PATH


@contextmanager
def get_connection(db_path: str = DATABASE_PATH):
    """Context manager for SQLite database connection.
    
    Ensures WAL mode is enabled, foreign keys are enforced, transactions are committed,
    and connections are strictly closed to prevent memory leaks and file lockouts.
    """
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        # WAL mode improves concurrent reads and reduces write stalls
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str = DATABASE_PATH) -> None:
    """Initialize database tables and indexes if they do not exist."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        
        # Table: sources
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                domain TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'completed', 'failed'))
            );
            """
        )

        # Table: facts
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                fact_or_review TEXT NOT NULL,
                verbatim_quote TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES sources (id) ON DELETE CASCADE
            );
            """
        )

        # Performance indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sources_domain ON sources(domain);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_facts_source_id ON facts(source_id);")


def add_sources(sources_list: List[Tuple[str, str]], db_path: str = DATABASE_PATH) -> int:
    """Insert a list of (url, domain) into sources table.
    
    Duplicates are safely ignored via INSERT OR IGNORE.
    Returns the number of new sources inserted.
    """
    if not sources_list:
        return 0

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        initial_count = cursor.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        cursor.executemany(
            """
            INSERT OR IGNORE INTO sources (url, domain, status)
            VALUES (?, ?, 'pending');
            """,
            sources_list
        )
        final_count = cursor.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        return final_count - initial_count


def get_pending_sources(limit: Optional[int] = None, db_path: str = DATABASE_PATH) -> List[Dict[str, Any]]:
    """Retrieve all pending sources ordered by ID."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        query = "SELECT id, url, domain, status FROM sources WHERE status = 'pending' ORDER BY id ASC"
        if limit is not None and limit > 0:
            query += f" LIMIT {int(limit)}"
        rows = cursor.execute(query).fetchall()
        return [dict(row) for row in rows]


def update_source_status(source_id: int, status: str, db_path: str = DATABASE_PATH) -> None:
    """Update status of a source to 'completed' or 'failed'."""
    if status not in ("pending", "completed", "failed"):
        raise ValueError(f"Invalid status '{status}'. Must be pending, completed, or failed.")

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE sources SET status = ? WHERE id = ?;",
            (status, source_id)
        )


def insert_facts(source_id: int, facts_list: List[Dict[str, str]], db_path: str = DATABASE_PATH) -> int:
    """Insert extracted facts tied to a source_id.
    
    Each fact dict must contain 'fact_or_review' and 'verbatim_quote'.
    Returns number of facts inserted.
    """
    if not facts_list:
        return 0

    records = []
    for item in facts_list:
        fact = (item.get("fact_or_review") or "").strip()
        quote = (item.get("verbatim_quote") or "").strip()
        if fact and quote:
            records.append((source_id, fact, quote))

    if not records:
        return 0

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.executemany(
            """
            INSERT INTO facts (source_id, fact_or_review, verbatim_quote)
            VALUES (?, ?, ?);
            """,
            records
        )
        return len(records)


def get_all_facts(db_path: str = DATABASE_PATH) -> List[Dict[str, Any]]:
    """Fetch all extracted facts joined with their source URL and domain."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT 
                f.id AS fact_id,
                f.source_id,
                s.url,
                s.domain,
                f.fact_or_review,
                f.verbatim_quote
            FROM facts f
            JOIN sources s ON f.source_id = s.id
            ORDER BY f.source_id ASC, f.id ASC;
            """
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_sources_map(db_path: str = DATABASE_PATH) -> Dict[int, Dict[str, Any]]:
    """Retrieve a dictionary mapping source_id to source details."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        rows = cursor.execute("SELECT id, url, domain, status FROM sources ORDER BY id ASC").fetchall()
        return {row["id"]: dict(row) for row in rows}


def get_stats(db_path: str = DATABASE_PATH) -> Dict[str, int]:
    """Retrieve operational statistics of the current database."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        total_sources = cursor.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        pending = cursor.execute("SELECT COUNT(*) FROM sources WHERE status = 'pending'").fetchone()[0]
        completed = cursor.execute("SELECT COUNT(*) FROM sources WHERE status = 'completed'").fetchone()[0]
        failed = cursor.execute("SELECT COUNT(*) FROM sources WHERE status = 'failed'").fetchone()[0]
        total_facts = cursor.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        return {
            "total_sources": total_sources,
            "pending": pending,
            "completed": completed,
            "failed": failed,
            "total_facts": total_facts,
        }


def reset_db(db_path: str = DATABASE_PATH) -> None:
    """Drop and recreate all tables for a fresh research session."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS facts;")
        cursor.execute("DROP TABLE IF EXISTS sources;")
    init_db(db_path)
