"""SQLAlchemy engine and session management.

Provides a thread-local scoped session. Each thread gets its own
SQLAlchemy Session; each Session gets its own SQLite connection
(NullPool). Combined with WAL mode, this allows multiple readers
and one writer to operate concurrently without "database is locked".

Cross-thread write coordination:
    _db_write_lock is a global threading.Lock that serializes all DB
    write operations across threads. Since SQLite WAL permits only one
    writer at a time, this lock prevents the busy_timeout-based wait
    (which freezes the UI thread for up to 30s).

Usage:
    from core.database import db_write_guard
    with db_write_guard(timeout=3.0):  # 3s timeout for UI operations
        session.commit()
    with db_write_guard():             # infinite wait for sync tasks
        session.commit()
"""
import threading
import sys
import contextlib
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import NullPool
from model.orm_models import Base
from loguru import logger

# ── Cross-thread write lock ──────────────────────────────────────────
# SQLite WAL allows 1 writer at a time. When sync (separate thread) and
# UI (main thread) both try to write, one blocks on busy_timeout (30s).
# This lock serializes writes at the application level with controllable
# timeouts, preventing UI freezes.
_db_write_lock = threading.Lock()

class DatabaseBusyError(Exception):
    """Raised when db_write_guard cannot acquire the lock within timeout."""


@contextlib.contextmanager
def db_write_guard(timeout=None):
    """Cross-thread write serialization context manager.

    Args:
        timeout: Max seconds to wait for the write lock.
                 None = block indefinitely (for background/sync threads).
                 Recommended: 3.0 for UI-triggered operations.

    Raises:
        DatabaseBusyError: if lock cannot be acquired within timeout.
    """
    acquired = _db_write_lock.acquire(timeout=timeout) if timeout is not None else (
        _db_write_lock.acquire() or True  # .acquire(blocking=True) returns True
    )
    if not acquired:
        raise DatabaseBusyError(
            f"数据库写入繁忙，请稍后重试（{timeout}s 超时）"
        )
    try:
        yield
    finally:
        _db_write_lock.release()

_engine = None
_SessionFactory = None


def _get_db_path() -> str:
    """Return the absolute path to the SQLite database file."""
    if getattr(sys, 'frozen', False):
        return str(Path(sys.executable).parent / "data" / "craftfiles.db")
    return str(Path("data/craftfiles.db"))


def get_engine():
    """Return the global SQLAlchemy Engine (lazy-initialized).

    Uses NullPool so each thread gets its own SQLite connection.
    WAL mode (set via connect event) allows concurrent readers +
    one writer at the file level. busy_timeout=30s ensures
    operations wait instead of immediately raising "database is locked".
    """
    global _engine
    if _engine is None:
        db_path = _get_db_path()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        _engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={
                "check_same_thread": False,
                "timeout": 30,
            },
            poolclass=NullPool,
        )

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):
            try:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA busy_timeout=30000;")
                cursor.close()
            except Exception as e:
                logger.warning(f"[DB] SQLite PRAGMA 设置失败: {e}")

    return _engine


def get_session_factory():
    """Return the thread-local scoped session factory (lazy-initialized)."""
    global _SessionFactory
    if _SessionFactory is None:
        engine = get_engine()
        _SessionFactory = scoped_session(
            sessionmaker(bind=engine, autoflush=False, autocommit=False),
            scopefunc=threading.get_ident,
        )
    return _SessionFactory


def _run_migrations(engine):
    """Apply incremental schema migrations for existing databases.

    Placeholder: add new migrations below as needed.
    """


def init_db():
    """Create all tables if they don't exist. Called once at startup.

    Attempts a passive WAL checkpoint to clean up accumulated WAL frames
    from previous runs. If the checkpoint blocks (e.g. due to stale
    locks from a crashed process), it is skipped — the next write will
    auto-checkpoint anyway.
    """
    engine = get_engine()
    Base.metadata.create_all(engine, checkfirst=True)
    _run_migrations(engine)
    # Try passive checkpoint (non-blocking) to clean accumulated WAL
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA busy_timeout=2000")
            conn.exec_driver_sql("PRAGMA wal_checkpoint(PASSIVE)")
            conn.commit()
    except Exception as e:
        logger.warning(f"[DB] WAL checkpoint 跳过（非致命）: {e}")
    logger.info(f"[DB] 数据库已初始化: {_get_db_path()}")
