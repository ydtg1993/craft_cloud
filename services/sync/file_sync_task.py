"""扁平文件列表同步任务。

收集本地文件列表，按大小分组上传，支持：
- 单文件大小限制过滤
- 每日上传总量/数量限制
- 去重（通过哈希匹配）
- 已删除文件的清理
"""
from pathlib import Path

from loguru import logger

from core.db_manager import compute_file_hash
from core.telegram_uploader import TelethonUploader
from core.utils import get_cache_dir
from core.media_utils import generate_media_cache
from core.translator import tr
from model.shared_types import SYNC_PENDING, SYNC_SUCCESS, SYNC_FAILED
from services.sync.base_sync_task import BaseSyncTask


class FileSyncTask(BaseSyncTask):
    """扁平文件列表同步任务（原 SyncTask，更名以区分目录树同步）。

    收集本地文件 → 过滤超限 → 确保目录结构 → 分组上传 → 清理已删除。
    """

    # ── 主同步入口 ────────────────────────────────────────────

    def _do_sync(self, target_dir_id, telethon_cfg, folder_config):
        """执行文件列表同步。"""
        config = self.config_manager.config

        # 收集本地文件
        local_files = self._collect_files(folder_config)

        # 单文件大小限制过滤
        limit_settings = config.get("upload_limit_settings", {})
        max_single_gb = limit_settings.get("max_single_file_size_gb", 0)
        if max_single_gb > 0:
            max_single_bytes = int(max_single_gb * 1024 ** 3)
            eligible_files = []
            skipped_count = 0
            for f in local_files:
                try:
                    size = Path(f).stat().st_size
                except OSError:
                    continue
                if size > max_single_bytes:
                    skipped_count += 1
                else:
                    eligible_files.append(f)
            if skipped_count > 0:
                logger.info(f"[{self._log_tag}] 本次同步跳过 {skipped_count} 个超限文件")
            local_files = eligible_files

        total_files = len(local_files)

        dir_map, all_dir_ids = self._ensure_dirs(local_files, target_dir_id)

        self.db.sync_status.upsert_sync_folder_status(
            self.folder_path,
            total_files=total_files,
            synced_files=0,
            status=SYNC_PENDING,
            error_message=None,
            _bg=True,
        )
        self.signals.progress.emit(0, total_files)

        # 每日总量检查
        if not self._check_daily_limits(local_files, limit_settings):
            self.db.sync_status.upsert_sync_folder_status(
                self.folder_path, status=SYNC_FAILED,
                error_message=tr("Daily upload limit reached"),
                _bg=True,
            )
            self.signals.error.emit(tr("Daily upload limit reached"))
            return

        def progress_callback(done, total):
            self.signals.progress.emit(done, total)
            self.db.sync_status.upsert_sync_folder_status(
                self.folder_path, synced_files=done, status=SYNC_PENDING, _bg=True
            )

        upload_interval = config.get("auto_sync_settings", {}).get("upload_interval", 1)

        count = self._sync_files(
            local_files, telethon_cfg, target_dir_id, dir_map, all_dir_ids,
            total_files=total_files,
            progress_callback=progress_callback,
            upload_interval=upload_interval,
        )

        if self.stop_event.is_set():
            self.db.sync_status.upsert_sync_folder_status(
                self.folder_path, synced_files=count, status=SYNC_PENDING, _bg=True
            )
            self.signals.cancelled.emit()
        else:
            self.db.sync_status.upsert_sync_folder_status(
                self.folder_path, synced_files=count, status=SYNC_SUCCESS, _bg=True
            )
            self.signals.completed.emit(count)

    # ── 文件收集 ──────────────────────────────────────────────

    def _collect_files(self, folder_config):
        """收集本地文件列表（始终递归包含子目录）。"""
        files = []
        for file_path in Path(self.folder_path).rglob('*'):
            if file_path.is_file():
                files.append(str(file_path))
        return files

    # ── 目录确保 ──────────────────────────────────────────────

    def _ensure_dirs(self, local_files, target_dir_id):
        """确保本地文件所需的目录结构在数据库中存在。"""
        dir_map = {}
        dir_map[""] = target_dir_id

        folder_path = Path(self.folder_path)
        unique_dirs = set()
        for file_path in local_files:
            try:
                rel_path = Path(file_path).relative_to(folder_path)
            except ValueError:
                continue
            parent_dir = str(rel_path.parent) if rel_path.parent != Path('.') else ''
            if parent_dir:
                unique_dirs.add(parent_dir)

        for dir_path in sorted(unique_dirs):
            parts = Path(dir_path).parts
            current_parent = target_dir_id
            current_path = ""
            for part in parts:
                if not part:
                    continue
                current_path = str(Path(current_path) / part) if current_path else part
                if current_path in dir_map:
                    current_parent = dir_map[current_path]
                    continue
                existing = self.db.dirs.get_directories(parent_id=current_parent)
                existing_dict = {name: did for did, name, is_sync in existing}
                if part in existing_dict:
                    dir_id = existing_dict[part]
                else:
                    dir_id = self.db.dirs.add_directory(part, parent_id=current_parent, is_sync=1, _bg=True)
                dir_map[current_path] = dir_id
                current_parent = dir_id

        all_dir_ids = list(dir_map.values())
        return dir_map, all_dir_ids

    # ── 每日限额 ──────────────────────────────────────────────

    def _check_daily_limits(self, files, limit_settings):
        """检查每日上传限制。"""
        if not limit_settings.get("enabled", False):
            return True
        uploaded_size = self.db.files.get_today_upload_size()
        uploaded_count = self.db.files.get_today_upload_count()
        max_size_bytes = limit_settings.get("max_daily_size_gb", 10) * 1024 ** 3
        max_count = limit_settings.get("max_daily_files", 100)

        new_total_size = sum(Path(f).stat().st_size for f in files if Path(f).exists())

        if uploaded_size + new_total_size > max_size_bytes:
            return False
        if uploaded_count + len(files) > max_count:
            return False
        return True

    # ── 文件同步（分组上传版本） ──────────────────────────────

    def _sync_files(self, local_files, telethon_cfg, target_dir_id, dir_map, all_dir_ids,
                    total_files=None, progress_callback=None, upload_interval=1):
        """分组上传文件，处理去重和已删除清理。"""
        GROUP_SIZE_LIMIT = 1 * 1024 ** 3

        db_records = []
        for did in all_dir_ids:
            records = self.db.files.get_local_files_in_directory(did)
            db_records.extend(records)

        db_by_path = {}
        for rec in db_records:
            if rec.local_path:
                db_by_path[rec.local_path] = rec

        # 清理本地已不存在的文件
        for path, rec in list(db_by_path.items()):
            if self.stop_event.is_set():
                return 0
            if path not in local_files and not Path(path).exists():
                self._delete_tg_message(rec.chat_id, rec.message_id)
                self.db.files.delete_file(rec.id, _bg=True)
                del db_by_path[path]

        synced = 0
        upload_items = []

        for file_path in local_files:
            if self.stop_event.is_set():
                return synced
            if not Path(file_path).is_file():
                continue
            file_hash = compute_file_hash(file_path)
            if file_hash is None:
                continue

            try:
                rel_path = Path(file_path).relative_to(folder_path)
            except ValueError:
                continue
            parent_rel = str(rel_path.parent) if rel_path.parent != Path('.') else ''
            file_dir_id = dir_map.get(parent_rel, target_dir_id)

            if file_path in db_by_path:
                rec = db_by_path[file_path]
                if rec.file_hash and rec.file_hash == file_hash:
                    synced += 1
                    if progress_callback:
                        progress_callback(synced, total_files)
                    continue
                else:
                    upload_items.append(
                        (Path(file_path).stat().st_size, file_path, rec.chat_id, rec.message_id, file_dir_id)
                    )
                    self.db.files.delete_file(rec.id, _bg=True)
                    del db_by_path[file_path]
                    continue

            existing = self.db.files.get_file_by_hash_in_directory(file_dir_id, file_hash)
            if existing:
                if existing.local_path != file_path:
                    new_display = Path(file_path).name
                    self.db.files.update_file_local_info(existing.id, file_path, new_display, file_hash, _bg=True)
                    self._edit_tg_message_caption(existing.chat_id, existing.message_id, new_display)
                    db_by_path[file_path] = existing
                synced += 1
                if progress_callback:
                    progress_callback(synced, total_files)
                continue

            upload_items.append((Path(file_path).stat().st_size, file_path, None, None, file_dir_id))

        # 按大小分组上传
        upload_items.sort(key=lambda x: x[0])
        groups = []
        current_group = []
        current_group_size = 0
        for item in upload_items:
            size, path, chat_id_old, msg_id_old, file_dir_id = item
            if current_group_size + size > GROUP_SIZE_LIMIT and current_group:
                groups.append(current_group)
                current_group = []
                current_group_size = 0
            current_group.append((size, path, chat_id_old, msg_id_old, file_dir_id))
            current_group_size += size
        if current_group:
            groups.append(current_group)

        uploader = TelethonUploader(telethon_cfg["api_id"], telethon_cfg["api_hash"])

        for group in groups:
            for size, file_path, chat_id_old, msg_id_old, file_dir_id in group:
                if self.stop_event.is_set():
                    return synced
                try:
                    if msg_id_old is not None:
                        self._delete_tg_message(chat_id_old, msg_id_old)

                    chat_id = self.db.dirs.get_directory_channel(target_dir_id)
                    file_id, msg_id, real_chat_id = self.loop.run_until_complete(
                        uploader.upload(
                            chat_id, file_path, db=self.db,
                            dir_id=file_dir_id,
                            dir_name=self._get_dir_name(file_dir_id),
                            client=self.client,
                        )
                    )
                    file_size = Path(file_path).stat().st_size
                    ext = Path(file_path).suffix.lower()
                    filename = Path(file_path).name

                    cache_dir = get_cache_dir()
                    thumb_path, media_clip_path = generate_media_cache(file_path, cache_dir, resource_id=file_id)

                    self.db.files.add_file(
                        file_id, msg_id, real_chat_id,
                        filename, filename,
                        file_dir_id, file_size, ext,
                        local_path=file_path, file_hash=compute_file_hash(file_path),
                        thumbnail_path=thumb_path,
                        cached_video_path=media_clip_path,
                        _bg=True,
                    )
                    synced += 1
                    if progress_callback:
                        progress_callback(synced, total_files)
                except Exception as e:
                    logger.error(f"[{self._log_tag}] 上传失败 {file_path}: {e}")

                # 上传间隔：避免触发 Telegram flood control
                if upload_interval > 0 and not self.stop_event.is_set():
                    import time as _time
                    _time.sleep(upload_interval)

        # 二次清理：再次检查本地已不存在的文件
        for path, rec in list(db_by_path.items()):
            if self.stop_event.is_set():
                return synced
            if path not in local_files:
                self._delete_tg_message(rec.chat_id, rec.message_id)
                self.db.files.delete_file(rec.id, _bg=True)
                del db_by_path[path]

        return synced
