"""Sync status repository — SQLAlchemy-backed.

All public method signatures are unchanged from the sqlite3 version.
"""
from sqlalchemy import select, delete
from model.orm_models import AutoSyncStatus
from core.utils import beijing_now_str
from core.database import db_write_guard


class SyncStatusRepository:
    def __init__(self, db):
        self.db = db

    def _session(self):
        return self.db._get_session()

    def _read(self, func):
        """Execute a read-only function and rollback to release DB locks."""
        session = self._session()
        try:
            return func(session)
        finally:
            session.rollback()

    def upsert_sync_folder_status(self, folder_path, total_files=None,
                                  synced_files=None, status=None,
                                  error_message=None, _bg=False):
        with db_write_guard(timeout=None if _bg else 5.0):
            session = self._session()

            obj = session.get(AutoSyncStatus, folder_path)
            if obj is None:
                obj = AutoSyncStatus(folder_path=folder_path)
                session.add(obj)

            if total_files is not None:
                obj.total_files = total_files
            if synced_files is not None:
                obj.synced_files = synced_files
            if status is not None:
                obj.status = status
            if error_message is not None:
                obj.error_message = error_message
            obj.last_sync_time = beijing_now_str()

            session.commit()

    def get_all_sync_folder_status(self):
        def _query(session):
            rows = session.execute(
                select(AutoSyncStatus).order_by(AutoSyncStatus.folder_path)
            ).scalars().all()
            return [
                (r.folder_path, r.total_files, r.synced_files, r.status,
                 r.last_sync_time, r.error_message)
                for r in rows
            ]
        return self._read(_query)

    def delete_sync_folder_status(self, folder_path, _bg=False):
        with db_write_guard(timeout=None if _bg else 5.0):
            session = self._session()
            session.execute(
                delete(AutoSyncStatus).where(AutoSyncStatus.folder_path == folder_path)
            )
            session.commit()
