"""
MSSQL database connection management via pyodbc.
Provides connection pooling and a FastAPI dependency for cursor injection.
"""
import logging
from contextlib import contextmanager
from typing import Generator

import pyodbc

from app.config import settings

logger = logging.getLogger(__name__)

# pyodbc connection pooling is enabled by default.
# We control pool size via the module-level flag.
pyodbc.pooling = True

_CONNECTION_STRING = settings.db_connection_string


def get_connection() -> pyodbc.Connection:
    """Create or retrieve a pooled connection."""
    try:
        conn = pyodbc.connect(_CONNECTION_STRING, autocommit=False)
        return conn
    except pyodbc.Error as exc:
        logger.error("Database connection failed: %s", exc)
        raise


@contextmanager
def get_cursor_ctx() -> Generator[pyodbc.Cursor, None, None]:
    """Context manager that yields a cursor and handles commit/rollback."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def get_db() -> Generator[pyodbc.Cursor, None, None]:
    """FastAPI dependency that yields a pyodbc cursor.
    Commits on success, rolls back on exception.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()
