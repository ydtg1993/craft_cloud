"""Database Manager — SQLAlchemy-backed.

Public API is unchanged: db.dirs, db.files, db.sync_status, and the helper
methods directory_exists() / get_directory_info() work identically.
"""
import hashlib
from sqlalchemy import select, func, and_
from model.orm_models import Directory, File, DirectoryRecord  # noqa: F401 — re-export
from model.directory_repository import DirectoryRepository
from model.file_repository import FileRepository
from model.sync_status_repository import SyncStatusRepository
from model.task_repository import TaskRepository
from model.user_repository import UserRepository
from core.database import get_session_factory, init_db
from loguru import logger


def compute_file_hash(file_path, algorithm='md5'):
    """Compute the hash of a file. Standalone utility, unchanged."""
    try:
        hash_obj = hashlib.new(algorithm)
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                hash_obj.update(chunk)
        return hash_obj.hexdigest()
    except (IOError, OSError) as e:
        logger.warning(f"文件哈希计算失败 {file_path}: {e}")
        return None


class DBManager:
    """Public interface to the database. Holds repository references."""

    def __init__(self):
        init_db()
        self.dirs = DirectoryRepository(self)
        self.files = FileRepository(self)
        self.sync_status = SyncStatusRepository(self)
        self.tasks = TaskRepository(self)
        self.users = UserRepository(self)
        self._ensure_default_directories()
        logger.info(f"[DB] DBManager 已初始化, 文件总数: {self.get_file_count()}")

    def _ensure_default_directories(self):
        """Create default system directories on first run.

        - "Saved Messages" (channel_id="me"): maps to Telegram's Saved Messages chat.
          This is the default upload target when no specific channel is needed.

        Handles legacy databases where Saved Messages may have been created
        without channel_id="me", avoiding duplicates.
        """
        session = self._get_session()

        # 1. Check for a proper Saved Messages directory (with channel_id="me")
        existing = session.execute(
            select(Directory).where(
                and_(
                    Directory.parent_id == 0,
                    Directory.channel_id == "me",
                )
            )
        ).scalars().first()

        if existing is not None:
            session.rollback()  # release read transaction (no write, no WAL lock)
            return  # Already correctly configured

        # 2. Check for legacy Saved Messages (by name, possibly without channel_id="me")
        legacy = session.execute(
            select(Directory).where(
                and_(
                    Directory.parent_id == 0,
                    Directory.name == "Saved Messages",
                )
            )
        ).scalars().all()

        if legacy:
            # Upgrade the first matching row and remove any duplicates
            first = legacy[0]
            first.channel_id = "me"
            for dup in legacy[1:]:
                session.delete(dup)
            session.commit()
            logger.info(
                f"[DB] 已将旧版 Saved Messages 升级 (id={first.id}, channel_id=me)"
                + (f"，已移除 {len(legacy) - 1} 个重复项" if len(legacy) > 1 else "")
            )
        else:
            # add_directory handles its own session commit internally
            self.dirs.add_directory("Saved Messages", parent_id=0, channel_id="me")
            logger.info("[DB] 已创建默认文件夹: Saved Messages (channel_id=me)")
            session.rollback()  # release read lock (writes committed by add_directory)

    def _get_session(self):
        """Return the thread-local SQLAlchemy Session.

        Replaces the old _get_conn(). Returns a scoped session that is
        automatically associated with the calling thread.
        """
        return get_session_factory()

    def directory_exists(self, dir_id):
        """Check if a directory with the given id exists."""
        session = self._get_session()
        try:
            return session.query(
                session.query(Directory).filter(Directory.id == dir_id).exists()
            ).scalar()
        finally:
            session.rollback()

    def get_directory_info(self, dir_id):
        """Return a DirectoryRecord for the given dir_id, or None."""
        session = self._get_session()
        try:
            row = session.get(Directory, dir_id)
            return row.to_record() if row else None
        finally:
            session.rollback()

    def get_file_count(self):
        """Return the total number of files in the database."""
        session = self._get_session()
        try:
            return session.scalar(select(func.count()).select_from(File)) or 0
        finally:
            session.rollback()
