"""Directory repository — SQLAlchemy-backed.

All public method signatures are unchanged from the sqlite3 version.

Write serialization:
    All mutating methods acquire db_write_guard() to prevent cross-thread
    SQLite write conflicts (main thread vs sync thread). bg=True is used
    for sync/background operations (infinite wait), bg=False for UI-thread
    operations (5s timeout → DatabaseBusyError).
"""
from pathlib import Path
from collections import defaultdict, deque
from sqlalchemy import select, update, delete, func, case
from sqlalchemy.exc import SQLAlchemyError
from model.orm_models import Directory, File, AutoSyncStatus
from model.shared_types import SyncFolderSummary, SYNC_PENDING
from core.cache_manager import remove_media_cache_files
from core.database import db_write_guard, DatabaseBusyError
from core.translator import tr
from loguru import logger


class DirectoryRepository:
    def __init__(self, db):
        self.db = db

    def _session(self):
        return self.db._get_session()

    def _read(self, func):
        """Execute a read-only function and rollback to release DB locks.

        Uses rollback() instead of commit() to avoid triggering autoflush
        and writing to the WAL file outside db_write_guard. This prevents
        "database is locked" errors when another thread holds a write lock.
        """
        session = self._session()
        try:
            return func(session)
        finally:
            session.rollback()

    def add_directory(self, name, parent_id=0, channel_id=None, is_sync=0, _bg=False):
        logger.info(f"[DB] add_directory: acquiring db_write_guard for name={name}")
        with db_write_guard(timeout=None if _bg else 5.0):
            logger.info(f"[DB] add_directory: db_write_guard acquired for name={name}")
            session = self._session()
            try:
                # Prevent creating a duplicate Saved Messages directory
                if parent_id == 0 and name == "Saved Messages":
                    existing = session.execute(
                        select(Directory.id).where(
                            Directory.parent_id == 0,
                            Directory.name == "Saved Messages",
                        )
                    ).scalar_one_or_none()
                    if existing is not None:
                        logger.warning("Saved Messages 已存在，跳过重复创建")
                        return existing
                d = Directory(name=name, parent_id=parent_id, channel_id=channel_id, is_sync=is_sync)
                session.add(d)
                logger.info(f"[DB] add_directory: committing for name={name}")
                session.commit()
                logger.info(f"[DB] 目录已创建: id={d.id}, name={name}, parent={parent_id}, is_sync={is_sync}")
                return d.id
            except SQLAlchemyError as e:
                session.rollback()
                logger.error(f"[DB] 创建目录失败: {e}, name={name}")
                raise

    def get_directories(self, parent_id=0, recursive=False):
        def _query(session):
            if not recursive:
                rows = session.execute(
                    select(Directory.id, Directory.name, Directory.is_sync)
                    .where(Directory.parent_id == parent_id)
                    .order_by(Directory.name)
                ).all()
                return [(r.id, r.name, r.is_sync) for r in rows]
            else:
                dirs_to_process = [parent_id]
                all_dirs = []
                while dirs_to_process:
                    current = dirs_to_process.pop()
                    children = session.execute(
                        select(Directory.id, Directory.name, Directory.parent_id, Directory.is_sync)
                        .where(Directory.parent_id == current)
                    ).all()
                    for c in children:
                        all_dirs.append((c.id, c.name, c.parent_id, c.is_sync))
                        dirs_to_process.append(c.id)
                return all_dirs
        return self._read(_query)

    def set_directory_sync(self, dir_id, is_sync, _bg=False):
        with db_write_guard(timeout=None if _bg else 5.0):
            session = self._session()
            try:
                session.execute(update(Directory).where(Directory.id == dir_id).values(is_sync=is_sync))
                session.commit()
            except SQLAlchemyError as e:
                session.rollback()
                logger.error(f"[DB] 设置目录同步状态失败: {e}, id={dir_id}")
                raise

    def move_directory(self, dir_id, new_parent_id, _bg=False):
        with db_write_guard(timeout=None if _bg else 5.0):
            session = self._session()
            try:
                session.execute(
                    update(Directory).where(Directory.id == dir_id).values(parent_id=new_parent_id)
                )
                session.commit()
                logger.info(f"[DB] 目录已移动: id={dir_id}, new_parent={new_parent_id}")
            except SQLAlchemyError as e:
                session.rollback()
                logger.error(f"[DB] 移动目录失败: {e}, id={dir_id}")
                raise

    def rename_directory(self, dir_id, new_name, _bg=False):
        with db_write_guard(timeout=None if _bg else 5.0):
            session = self._session()
            try:
                session.execute(update(Directory).where(Directory.id == dir_id).values(name=new_name))
                session.commit()
                logger.info(f"[DB] 目录已重命名: id={dir_id}, new_name={new_name}")
            except SQLAlchemyError as e:
                session.rollback()
                logger.error(f"[DB] 重命名目录失败: {e}, id={dir_id}")
                raise

    def get_directory_channel(self, dir_id):
        if dir_id == 0:
            return "me"
        session = self._session()
        try:
            row = session.execute(
                select(Directory.channel_id).where(Directory.id == dir_id)
            ).scalar_one_or_none()
            return row if row else None
        finally:
            session.rollback()

    def find_dir_id_by_channel(self, channel_id):
        """根据 channel_id 反向查找目录 ID（用于碰撞检测）。"""
        if not channel_id or channel_id == "me":
            return None
        session = self._session()
        try:
            row = session.execute(
                select(Directory.id).where(Directory.channel_id == str(channel_id))
            ).scalar_one_or_none()
            return row if row else None
        finally:
            session.rollback()

    def set_directory_channel(self, dir_id, channel_id, _bg=False):
        with db_write_guard(timeout=None if _bg else 5.0):
            session = self._session()
            try:
                session.execute(
                    update(Directory).where(Directory.id == dir_id).values(channel_id=channel_id)
                )
                session.commit()
                logger.info(f"[DB] 目录频道已设置: id={dir_id}, channel={channel_id}")
            except SQLAlchemyError as e:
                session.rollback()
                logger.error(f"[DB] 设置目录频道失败: {e}, id={dir_id}")
                raise

    def get_path_to_directory(self, dir_id):
        session = self._session()
        try:
            path = [(0, tr("Root"))]
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
        finally:
            session.rollback()

    def get_parent_id(self, dir_id):
        if dir_id == 0:
            return None
        session = self._session()
        try:
            row = session.execute(
                select(Directory.parent_id).where(Directory.id == dir_id)
            ).scalar_one_or_none()
            return row
        finally:
            session.rollback()

    def get_channel_root_id(self, dir_id):
        """向上追溯到频道根目录（parent_id=0），返回其 id。

        用于文件迁移时确定「同频道」范围。
        """
        if dir_id == 0:
            return 0
        session = self._session()
        try:
            current = dir_id
            while current:
                d = session.get(Directory, current)
                if not d:
                    break
                if d.parent_id == 0:
                    return d.id
                current = d.parent_id
            return 0
        finally:
            session.rollback()

    def get_descendant_dirs(self, root_id):
        """获取 root_id 下所有子孙目录（不含 root_id 自身）。

        返回 [(id, name, is_sync), ...] 列表，用于迁移下拉框。
        """
        session = self._session()
        try:
            result = []
            stack = [root_id]
            while stack:
                parent = stack.pop()
                children = session.execute(
                    select(Directory.id, Directory.name, Directory.is_sync)
                    .where(Directory.parent_id == parent)
                    .order_by(Directory.name)
                ).all()
                for c in children:
                    result.append((c.id, c.name, c.is_sync))
                    stack.append(c.id)
            return result
        finally:
            session.rollback()

    def get_sync_summaries(self, config_auto_sync_settings=None):
        """返回所有已配置同步目录的聚合统计列表。"""
        session = self._session()
        try:
            folders_cfg = (config_auto_sync_settings or {}).get("folders", {})

            if not folders_cfg:
                return []

            summaries = []
            for folder_path, cfg in folders_cfg.items():
                dir_id = cfg.get("target_dir_id")
                if not dir_id:
                    continue

                root = session.get(Directory, dir_id)
                if root is None:
                    # 目录尚未创建（未执行过同步），使用配置中的信息占位
                    status_row = session.get(AutoSyncStatus, folder_path)
                    summaries.append(SyncFolderSummary(
                        dir_id=dir_id,
                        dir_name=Path(folder_path).name if folder_path else "(pending)",
                        local_path=folder_path,
                        channel_id=None,
                        channel_name="",
                        total_files=0,
                        synced_files=0,
                        total_size=0,
                        synced_size=0,
                        status=status_row.status if status_row else SYNC_PENDING,
                        last_sync_time=status_row.last_sync_time if status_row else None,
                        error_message=status_row.error_message if status_row else None,
                    ))
                    continue

                # 收集所有子孙目录ID（含自身）
                descendant_ids = self._collect_descendant_ids(root.id, session)

                # 聚合查询 — synced_files 来自 File 表（已上传文件数），
                # total_size / synced_size 也来自 File 表
                agg = session.execute(
                    select(
                        func.count(File.id).label("synced_files"),
                        func.coalesce(func.sum(File.file_size), 0).label("total_size"),
                        func.coalesce(
                            func.sum(
                                case((File.is_sync == 1, File.file_size), else_=0)
                            ), 0
                        ).label("synced_size"),
                    ).where(File.directory_id.in_(descendant_ids))
                ).one()

                # total_files 从 AutoSyncStatus 读取（由 sync task 在开始时
                # 统计磁盘文件总数），避免与 File 表记录数混淆。
                # synced_files 从 File 表获取实际已上传文件数，反映真实同步进度。
                status_row = session.get(AutoSyncStatus, folder_path)
                total_files = status_row.total_files if status_row else 0
                synced_files = agg.synced_files

                # dir_name 优先取本地文件夹名，更直观（DB中可能是"Saved Messages"等通用名）
                display_name = Path(folder_path).name if folder_path else root.name

                summaries.append(SyncFolderSummary(
                    dir_id=root.id,
                    dir_name=display_name,
                    local_path=folder_path,
                    channel_id=root.channel_id,
                    channel_name=root.name,
                    total_files=total_files,
                    synced_files=synced_files,
                    total_size=agg.total_size,
                    synced_size=agg.synced_size,
                    status=status_row.status if status_row else SYNC_PENDING,
                    last_sync_time=status_row.last_sync_time if status_row else None,
                    error_message=status_row.error_message if status_row else None,
                ))

        finally:
            session.rollback()
        return summaries

    def _collect_descendant_ids(self, root_id, session=None):
        """BFS 收集 root_id 及其所有子孙目录的 ID 列表。

        使用迭代 BFS 而非递归，避免深层目录树导致 RecursionError。
        与 delete_directory_recursive 共用此方法。

        Args:
            root_id: 根目录 ID
            session: 可选，传入已有的 session 以复用；不传则自动获取
        """
        if session is None:
            session = self._session()
        ids = [root_id]
        queue = deque([root_id])
        seen = {root_id}
        while queue:
            if len(ids) > 10000:
                logger.warning(
                    f"[DB] _collect_descendant_ids 达到上限 10000，"
                    f"截断 root_id={root_id} 的部分子孙目录"
                )
                break
            parent = queue.popleft()
            children = session.execute(
                select(Directory.id).where(Directory.parent_id == parent)
            ).scalars().all()
            for c in children:
                if c in seen:
                    continue
                seen.add(c)
                ids.append(c)
                queue.append(c)
        return ids

    def delete_directory_recursive(self, dir_id, _bg=False):
        """递归删除目录及其所有子目录和文件。

        先收集所有子孙目录 ID（只读），再在写锁内分批删除文件、
        清理缓存、删除目录。分批提交避免长事务阻塞其他写入者。

        Args:
            dir_id: 要删除的根目录 ID
            _bg: True 表示后台线程调用（无限等锁），False 表示 UI 线程（5s 超时）
        """
        # Phase 1: read-only collection via iterative BFS (no write lock needed)
        session = self._session()
        try:
            dirs_to_delete = self._collect_descendant_ids(dir_id, session)
            logger.info(f"[DB] 递归删除目录: root={dir_id}, 共 {len(dirs_to_delete)} 个子目录")
        finally:
            session.rollback()  # release read lock (no writes in this phase)

        # Phase 2: destructive writes under write lock, batched commits
        with db_write_guard(timeout=None if _bg else 5.0):
            try:
                # 2a. 在写锁内重新查询缓存文件路径，防止 Phase 1→2 之间
                #     其他线程新增文件导致的 TOCTOU 竞态（遗漏缓存清理）。
                s = self._session()
                try:
                    cache_files = s.execute(
                        select(File.thumbnail_path, File.cached_video_path)
                        .where(File.directory_id.in_(dirs_to_delete))
                    ).all()
                finally:
                    pass  # scoped session — no explicit cleanup needed

                # 2b. Delete files in smaller batches to keep transactions short
                BATCH_SIZE = 500
                for i in range(0, len(dirs_to_delete), BATCH_SIZE):
                    batch = dirs_to_delete[i:i + BATCH_SIZE]
                    s = self._session()
                    try:
                        s.execute(delete(File).where(File.directory_id.in_(batch)))
                        s.commit()
                    except SQLAlchemyError:
                        s.rollback()
                        raise

                # 2c. Clean up media cache files on disk (outside DB transaction)
                for thumb_path, clip_path in cache_files:
                    remove_media_cache_files(thumb_path, clip_path)

                # 2d. Delete directories in reverse order (children first)
                for did in reversed(dirs_to_delete):
                    s = self._session()
                    try:
                        s.execute(delete(Directory).where(Directory.id == did))
                        s.commit()
                    except SQLAlchemyError:
                        s.rollback()
                        raise

                logger.info(f"[DB] 目录及其内容已删除: root={dir_id}")
            except SQLAlchemyError as e:
                logger.error(f"[DB] 递归删除目录失败: {e}, dir_id={dir_id}")
                raise
