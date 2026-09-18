"""SQLite database connection factory and lifecycle utilities."""

import os
import sqlite3
from contextlib import contextmanager
from typing import Generator


def configure_connection(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Apply PRAGMA configurations for SQLite connection."""
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        # WAL mode provides concurrent read while writing (file-based DBs only)
        cursor.execute("PRAGMA journal_mode = WAL;")
    except sqlite3.OperationalError:
        pass
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("PRAGMA busy_timeout = 10000;")
    cursor.close()
    return conn


def get_connection(db_path: str = "daas.db", timeout: float = 10.0) -> sqlite3.Connection:
    """Create and configure a new SQLite connection."""
    if db_path != ":memory:":
        db_dir = os.path.dirname(os.path.abspath(db_path))
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(db_path, timeout=timeout)
    return configure_connection(conn)


@contextmanager
def db_transaction(db_path: str = "daas.db", timeout: float = 10.0) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for atomic transactions on SQLite database."""
    conn = get_connection(db_path, timeout=timeout)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
