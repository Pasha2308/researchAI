"""Database connection management and initialization.

Provides context-managed SQLite connections with Write-Ahead Logging (WAL),
foreign keys enforcement, and graceful FTS5 full-text search initialization.
"""

import sqlite3
from contextlib import contextmanager
from typing import Generator, Optional
from config import settings
from research_engine.database.schema import SCHEMA_SQL, FTS5_SQL


@contextmanager
def get_connection(db_path: Optional[str] = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for SQLite database connection.
    
    Enforces WAL mode for performance, foreign keys for referential integrity,
    and automatic commit / rollback semantics.
    """
    path = db_path or settings.database_path
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
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


def init_database(db_path: Optional[str] = None) -> bool:
    """Initialize all database tables, indexes, and FTS5 search virtual tables.
    
    Detects and upgrades legacy schemas if present.
    """
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        
        # Check if legacy table 'sources' exists without 'run_id'
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sources';")
        has_sources = cursor.fetchone() is not None
        if has_sources:
            cursor.execute("PRAGMA table_info(sources);")
            columns = [row["name"] for row in cursor.fetchall()]
            if "run_id" not in columns:
                # Legacy schema detected - safely archive or recreate
                cursor.execute("ALTER TABLE sources RENAME TO legacy_sources_backup;")
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='facts';")
                if cursor.fetchone():
                    cursor.execute("ALTER TABLE facts RENAME TO legacy_facts_backup;")

        # Ensure no existing tables have dangling foreign keys referencing legacy_sources_backup
        for tbl in ("source_content", "evidence", "claim_evidence"):
            cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{tbl}';")
            tbl_row = cursor.fetchone()
            if tbl_row and "legacy_sources_backup" in tbl_row["sql"]:
                cursor.execute(f"DROP TABLE IF EXISTS {tbl};")

        cursor.executescript(SCHEMA_SQL)
        
        # Initialize FTS5 table if supported by sqlite build
        try:
            cursor.executescript(FTS5_SQL)
            fts5_enabled = True
        except sqlite3.OperationalError:
            fts5_enabled = False

    return fts5_enabled
