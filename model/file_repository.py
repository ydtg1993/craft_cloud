"""File repository — SQLAlchemy-backed.

All public method signatures are unchanged from the sqlite3 version.
Whoosh full-text search integration is preserved.

Write serialization:
    All mutating methods acquire db_write_guard() to prevent cross-thread
    SQLite write conflicts (main thread vs sync thread). _bg=True is used
    for sync/background operations (infinite wait), _bg=False for UI-thread
    operations (5s timeout → DatabaseBusyError).
"""
from collections import namedtuple
from pathlib import Path
from sqlalchemy import select, update, delete, func, text
from sqlalchemy.exc import SQLAlchemyError
from model.orm_models import File, DailyUploadLog, Directory
from model.orm_models import FileRecord, DirectoryItem  # re-export for callers
from core.utils import beijing_now_str, beijing_today_str
from core.cache_manager import remove_media_cache_files
from core.database import db_write_guard
from core.translator import tr
from loguru import logger

# Re-export for backward compatibility
__all__ = ['FileRepository', 'FileRecord', 'DirectoryItem']

# Legacy namedtuples kept here for callers that import from this module
# (actual definitions are in orm_models.py; re-import here to avoid breaking imports)


class FileRepository:
    def __init__(self, db):
        self.db = db
        self._indexer = None

    def set_indexer(self, indexer):
        """注入搜索索引器（如 WhooshSearch）。由 services 层在初始化时调用。"""
        self._indexer = indexer

    def _session(self):
        return self.db._get_session()

    def _read(self, func):
        """Execute a read-only function and rollback to release DB locks.

        Uses rollback() instead of commit() to avoid touching the WAL file
        outside db_write_guard — prevents cross-thread write conflicts.
        """
        session = self._session()
        try:
            return func(session)
        finally:
            session.rollback()

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_items_in_directory(self, directory_id=0):
        def _query(session):
            # Directories: is_dir=1, file-specific fields = None
            dir_objs = session.execute(
                select(Directory)
                .where(Directory.parent_id == directory_id)
                .order_by(Directory.name)
            ).scalars().all()

            dirs = [
                (d.id, d.name, 1, None, None, None, None, None, None, None, d.is_sync)
                for d in dir_objs
            ]

            # Files: is_dir=0, name=None
            file_objs = session.execute(
                select(File)
                .where(File.directory_id == directory_id)
                .order_by(File.display_name, File.original_name)
            ).scalars().all()

            files = [
                (f.id, None, 0, f.message_id, f.original_name, f.display_name,
                 f.file_size, f.upload_time, f.mime_type, f.thumbnail_path, f.is_sync)
                for f in file_objs
            ]

            return [DirectoryItem(*row) for row in (dirs + files)]

        return self._read(_query)

    def get_files_in_directory(self, directory_id=0):
        session = self._session()
        try:
            rows = session.execute(
                select(File).where(File.directory_id == directory_id)
                .order_by(File.upload_time.desc())
            ).scalars().all()
            return [f.to_record() for f in rows]
        finally:
            session.rollback()

    def get_file_by_id(self, local_id):
        session = self._session()
        try:
            f = session.get(File, local_id)
            return f.to_record() if f else None
        finally:
            session.rollback()

    def get_local_files_in_directory(self, directory_id):
        session = self._session()
        try:
            rows = session.execute(
                select(File).where(
                    File.directory_id == directory_id,
                    File.local_path.isnot(None),
                )
            ).scalars().all()
            return [f.to_record() for f in rows]
        finally:
            session.rollback()

    def get_file_by_local_path(self, directory_id, local_path):
        session = self._session()
        try:
            f = session.execute(
                select(File).where(
                    File.directory_id == directory_id,
                    File.local_path == local_path,
                ).limit(1)
            ).scalar_one_or_none()
            return f.to_record() if f else None
        finally:
            session.rollback()

    def get_file_by_hash_in_directory(self, directory_id, file_hash):
        session = self._session()
        try:
            f = session.execute(
                select(File).where(
                    File.directory_id == directory_id,
                    File.file_hash == file_hash,
                ).limit(1)
            ).scalar_one_or_none()
            return f.to_record() if f else None
        finally:
            session.rollback()

    def get_all_files_recursive(self, dir_id):
        """Get all files in dir_id and its subdirectories."""
        def _query(session):
            dirs_to_process = [dir_id]
            all_dirs = [dir_id]
            while dirs_to_process:
                current = dirs_to_process.pop()
                children = session.execute(
                    select(Directory.id).where(Directory.parent_id == current)
                ).scalars().all()
                for c in children:
                    all_dirs.append(c)
                    dirs_to_process.append(c)

            if not all_dirs:
                return []

            rows = session.execute(
                select(File).where(File.directory_id.in_(all_dirs))
            ).scalars().all()
            return [f.to_record() for f in rows]
        return self._read(_query)

    def get_files_by_original_name(self, directory_id, original_name):
        """Find files by original name (dedup check)."""
        session = self._session()
        try:
            f = session.execute(
                select(File).where(
                    File.directory_id == directory_id,
                    File.original_name == original_name,
                ).limit(1)
            ).scalar_one_or_none()
            return f.to_record() if f else None
        finally:
            session.rollback()

    def get_today_upload_size(self):
        session = self._session()
        try:
            today = beijing_today_str()
            row = session.execute(
                select(func.coalesce(func.sum(DailyUploadLog.file_size), 0))
                .where(func.date(DailyUploadLog.upload_time) == today)
            ).scalar()
            return row
        finally:
            session.rollback()

    def get_today_upload_count(self):
        session = self._session()
        try:
            today = beijing_today_str()
            row = session.execute(
                select(func.count())
                .where(func.date(DailyUploadLog.upload_time) == today)
            ).scalar()
            return row
        finally:
            session.rollback()

    def get_total_uploaded_size(self):
        """Return total size (bytes) of all files stored in the cloud."""
        session = self._session()
        try:
            row = session.execute(
                select(func.coalesce(func.sum(File.file_size), 0))
            ).scalar()
            return row
        finally:
            session.rollback()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def add_file(self, file_id, message_id, chat_id, original_name, display_name,
                 directory_id, file_size, mime_type, local_path=None, file_hash=None,
                 thumbnail_path=None, cached_video_path=None, is_sync=0, _bg=False):
        # Phase 1: DB write under guard (short-lived lock)
        with db_write_guard(timeout=None if _bg else 5.0):
            session = self._session()
            try:
                upload_time = beijing_now_str()
                f = File(
                    file_id=file_id, message_id=message_id, chat_id=chat_id,
                    original_name=original_name, display_name=display_name,
                    directory_id=directory_id, file_size=file_size, mime_type=mime_type,
                    is_sync=is_sync, upload_time=upload_time,
                    local_path=local_path, file_hash=file_hash,
                    thumbnail_path=thumbnail_path, cached_video_path=cached_video_path,
                )
                session.add(f)
                session.flush()  # Get the auto-generated id
                file_pk = f.id

                session.add(DailyUploadLog(file_size=file_size, upload_time=upload_time))
                session.commit()
                indexer_name = display_name or original_name
                logger.info(f"[DB] 文件记录已保存: id={file_pk}, name={indexer_name}, dir={directory_id}")
            except Exception:
                session.rollback()
                logger.exception(
                    f"[DB] 保存文件记录失败: "
                    f"name={display_name or original_name}, dir={directory_id}"
                )
                raise

        # Phase 2: Whoosh indexing OUTSIDE db_write_guard
        # Must happen AFTER commit (so DB row exists), but does NOT need
        # the write lock. Moving it here reduces lock contention with
        # concurrent sync operations and prevents UI-thread blocking.
        if self._indexer:
            try:
                self._update_whoosh(file_pk, indexer_name)
            except Exception:
                logger.exception(f"[DB] Whoosh索引更新失败: id={file_pk}")

        return file_pk

    def update_file_cache_paths(self, file_id, thumbnail_path, cached_video_path, _bg=False):
        with db_write_guard(timeout=None if _bg else 5.0):
            session = self._session()
            session.execute(
                update(File).where(File.id == file_id).values(
                    thumbnail_path=thumbnail_path, cached_video_path=cached_video_path
                )
            )
            session.commit()

    def update_display_name(self, file_id, new_name, _bg=False):
        with db_write_guard(timeout=None if _bg else 5.0):
            session = self._session()
            try:
                session.execute(
                    update(File).where(File.id == file_id).values(display_name=new_name)
                )
                session.commit()
                logger.info(f"[DB] 文件显示名已更新: id={file_id}, new_name={new_name}")
            except SQLAlchemyError as e:
                session.rollback()
                logger.error(f"[DB] 更新文件显示名失败: {e}, id={file_id}")
                raise

        # Whoosh index update outside db_write_guard — reduces lock contention
        if self._indexer:
            self._update_whoosh(file_id, new_name)

    def update_file_original_name(self, file_id, original_name, _bg=False):
        with db_write_guard(timeout=None if _bg else 5.0):
            session = self._session()
            try:
                session.execute(
                    update(File).where(File.id == file_id).values(original_name=original_name)
                )
                session.commit()
            except SQLAlchemyError as e:
                session.rollback()
                logger.error(f"[DB] 更新文件原始名失败: {e}, id={file_id}")
                raise

    def move_file(self, file_id, new_directory_id, _bg=False):
        with db_write_guard(timeout=None if _bg else 5.0):
            session = self._session()
            try:
                session.execute(
                    update(File).where(File.id == file_id).values(directory_id=new_directory_id)
                )
                session.commit()
                logger.info(f"[DB] 文件已移动: id={file_id}, new_dir={new_directory_id}")
            except SQLAlchemyError as e:
                session.rollback()
                logger.error(f"[DB] 移动文件失败: {e}, id={file_id}")
                raise

    def delete_file(self, file_id, _bg=False):
        with db_write_guard(timeout=None if _bg else 5.0):
            session = self._session()
            try:
                # 删除前先查出缓存文件路径
                f = session.get(File, file_id)
                thumb = f.thumbnail_path if f else None
                clip = f.cached_video_path if f else None

                session.execute(delete(File).where(File.id == file_id))
                session.commit()
                session.expire_all()  # Ensure next query re-reads
                self._delete_index(file_id)

                # 清理磁盘上的预览缓存文件
                remove_media_cache_files(thumb, clip)
                logger.info(f"[DB] 文件记录已删除: id={file_id}")
            except SQLAlchemyError as e:
                session.rollback()
                logger.error(f"[DB] 删除文件记录失败: {e}, id={file_id}")
                raise

    def update_file_local_info(self, file_id, local_path, display_name, file_hash=None, _bg=False):
        with db_write_guard(timeout=None if _bg else 5.0):
            session = self._session()
            try:
                values = {"local_path": local_path, "display_name": display_name}
                if file_hash:
                    values["file_hash"] = file_hash
                session.execute(
                    update(File).where(File.id == file_id).values(**values)
                )
                session.commit()
            except SQLAlchemyError as e:
                session.rollback()
                logger.error(f"[DB] 更新文件本地信息失败: {e}, id={file_id}")
                raise

    def update_file(self, file_id, file_id_new=None, message_id=None, chat_id=None,
                    file_size=None, file_hash=None, local_path=None, _bg=False):
        with db_write_guard(timeout=None if _bg else 5.0):
            session = self._session()
            try:
                values = {}
                if file_id_new is not None:
                    values["file_id"] = file_id_new
                if message_id is not None:
                    values["message_id"] = message_id
                if chat_id is not None:
                    values["chat_id"] = chat_id
                if file_size is not None:
                    values["file_size"] = file_size
                if file_hash is not None:
                    values["file_hash"] = file_hash
                if local_path is not None:
                    values["local_path"] = local_path

                if values:
                    session.execute(update(File).where(File.id == file_id).values(**values))
                    session.commit()
            except SQLAlchemyError as e:
                session.rollback()
                logger.error(f"[DB] 更新文件信息失败: {e}, id={file_id}")
                raise

    def log_upload_size(self, file_size, _bg=False):
        with db_write_guard(timeout=None if _bg else 5.0):
            session = self._session()
            session.add(DailyUploadLog(file_size=file_size, upload_time=beijing_now_str()))
            session.commit()

    # ------------------------------------------------------------------
    # Search operations
    # ------------------------------------------------------------------

    def search_files_by_name(self, keyword, force_like=False):
        """Search files by name using Whoosh full-text search with SQL fallback."""
        keyword = keyword.strip()
        if not keyword:
            return []
        session = self._session()
        try:
            # Primary: Whoosh full-text search (if indexer injected)
            try:
                matched_ids = self._indexer.search(keyword) if self._indexer else []
                if matched_ids:
                    files = session.execute(
                        select(File.id, File.file_id, File.message_id, File.chat_id,
                               File.original_name, File.display_name, File.directory_id,
                               File.file_size, File.upload_time, File.mime_type,
                               Directory.name.label('dir_name'))
                        .outerjoin(Directory, File.directory_id == Directory.id)
                        .where(File.id.in_(matched_ids))
                        .order_by(func.coalesce(File.display_name, File.original_name).collate('NOCASE'))
                    ).all()
                    if files:
                        return self._build_results(files, session)
            except Exception as e:
                logger.debug(f"Whoosh搜索失败，回退到SQL LIKE: {e}")  # Fall through to SQL LIKE fallback

            # Fallback: SQL LIKE search
            like_kw = f"%{keyword}%"
            files = session.execute(
                select(File.id, File.file_id, File.message_id, File.chat_id,
                       File.original_name, File.display_name, File.directory_id,
                       File.file_size, File.upload_time, File.mime_type,
                       Directory.name.label('dir_name'))
                .outerjoin(Directory, File.directory_id == Directory.id)
                .where(
                    func.coalesce(File.display_name, '').ilike(like_kw)
                    | func.coalesce(File.original_name, '').ilike(like_kw)
                )
                .order_by(func.coalesce(File.display_name, File.original_name).collate('NOCASE'))
            ).all()
            return self._build_results(files, session)
        finally:
            session.rollback()

    def search_files_by_date_range(self, start_date, end_date):
        session = self._session()
        try:
            files = session.execute(
                select(File.id, File.file_id, File.message_id, File.chat_id,
                       File.original_name, File.display_name, File.directory_id,
                       File.file_size, File.upload_time, File.mime_type,
                       Directory.name.label('dir_name'))
                .outerjoin(Directory, File.directory_id == Directory.id)
                .where(
                    func.date(File.upload_time) >= start_date,
                    func.date(File.upload_time) <= end_date,
                )
                .order_by(File.upload_time.desc())
            ).all()
            return self._build_results(files, session)
        finally:
            session.rollback()

    def _build_results(self, rows, session):
        """Build search result dicts with full path strings."""
        dir_ids = set()
        for row in rows:
            dir_ids.add(row.directory_id)
        path_cache = {}
        for did in dir_ids:
            path_cache[did] = self._get_path_to_directory(did, session)
        results = []
        for row in rows:
            path_str = self._build_path_string(path_cache[row.directory_id])
            results.append({
                'id': row.id,
                'name': row.display_name or row.original_name,
                'directory_id': row.directory_id,
                'full_path': path_str,
                'original_name': row.original_name,
                'display_name': row.display_name,
                'file_size': row.file_size,
                'upload_time': row.upload_time,
                'mime_type': row.mime_type,
            })
        return results

    def _get_path_to_directory(self, dir_id, session):
        root_name = tr("Root")
        path = [(0, root_name)]
        if dir_id == 0:
            return path
        segments = []
        current = dir_id
        while current:
            d = session.get(Directory, current)
            if not d:
                break
            segments.append((d.id, d.name))
            current = d.parent_id
        for seg in reversed(segments):
            path.append(seg)
        return path

    def _build_path_string(self, path_parts):
        root_name = tr("Root")
        parts = []
        for _, name in path_parts:
            if name != root_name:
                parts.append(name)
        if not parts:
            return "/"
        return "/" + "/".join(parts)

    # ------------------------------------------------------------------
    # Index management (Whoosh)
    # ------------------------------------------------------------------

    def _update_whoosh(self, file_id, name):
        """Update Whoosh index (must be called AFTER DB commit to avoid WAL conflicts)."""
        session = self._session()
        try:
            # Get data for Whoosh indexing
            _dir_id_row = session.execute(
                text("SELECT directory_id FROM files WHERE id = :fid"),
                {"fid": file_id}
            ).scalar_one_or_none()
            dir_id = _dir_id_row or 0
            _dir_name_row = session.execute(
                text("SELECT d.name FROM directories d JOIN files f ON f.directory_id = d.id WHERE f.id = :fid"),
                {"fid": file_id}
            ).scalar_one_or_none()
            dir_name = _dir_name_row or ""
            _orig_row = session.execute(
                text("SELECT original_name FROM files WHERE id = :fid"),
                {"fid": file_id}
            ).scalar_one_or_none()
            original_name = _orig_row or ""
            self._indexer.index_file(file_id, name, original_name, dir_name, dir_id)
        finally:
            session.rollback()

    def _delete_index(self, file_id):
        """Remove file from search index."""
        if self._indexer:
            self._indexer.remove_file(file_id)
