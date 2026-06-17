"""UploadManager — 上传业务逻辑。

通过 Qt Signal 与 UI 通信，不直接使用 QFileDialog/QMessageBox。
"""
import time
from pathlib import Path
from PySide6.QtCore import QObject, Signal
from core.task_types import Task
from core.telegram_uploader import TelethonUploader
from core.media_utils import generate_media_cache
from core.utils import get_cache_dir
from core.translator import tr
from loguru import logger


class UploadManager(QObject):
    warning_requested = Signal(str, str)  # title, message

    def __init__(self, config_manager, db, task_manager, parent=None):
        super().__init__(parent)
        self.config = config_manager.config
        self.db = db
        self.tm = task_manager

    def start_upload(self, file_paths, target_dir_id=0):
        """执行业务逻辑。file_paths 和 target_dir_id 由 view 层提供。"""
        logger.info(f"[Upload] 开始上传 {len(file_paths)} 个文件, 目标目录: {target_dir_id}")
        telethon_cfg = self._get_telethon_config()
        if not telethon_cfg:
            self.warning_requested.emit(tr("Warning"), tr("Not logged in"))
            return

        # ========== 获取限制配置 ==========
        limit_cfg = self.config.get("upload_limit_settings", {})
        single_limit_gb = limit_cfg.get("max_single_file_size_gb", 0)
        single_limit_bytes = int(single_limit_gb * 1024**3) if single_limit_gb else 0
        daily_enabled = limit_cfg.get("enabled", False)
        daily_size_gb = limit_cfg.get("max_daily_size_gb", 10)
        daily_size_bytes = int(daily_size_gb * 1024**3)
        daily_files = limit_cfg.get("max_daily_files", 100)

        # ========== 过滤单文件超限 ==========
        skipped_files = []
        eligible_paths = []
        for fp in file_paths:
            try:
                size = Path(fp).stat().st_size
            except OSError:
                continue
            if single_limit_bytes and size > single_limit_bytes:
                skipped_files.append(fp)
            else:
                eligible_paths.append(fp)

        if skipped_files:
            msg = tr("The following files exceed the single file size limit ({limit}) and will be skipped:\\n{files}").format(
                limit=f"{single_limit_gb} GB",
                files="\n".join(Path(f).name for f in skipped_files[:5]) +
                      (f"\n... 等共 {len(skipped_files)} 个文件" if len(skipped_files) > 5 else "")
            )
            self.warning_requested.emit(tr("Warning"), msg)

        if not eligible_paths:
            return

        # ========== 同名文件去重 ==========
        dup_names = []
        deduped_paths = []
        for fp in eligible_paths:
            fname = Path(fp).name
            if self.db.files.get_files_by_original_name(target_dir_id, fname):
                dup_names.append(fname)
            else:
                deduped_paths.append(fp)

        if dup_names:
            msg = tr(
                "The following files already exist in the target directory and will be skipped:\n{files}"
            ).format(
                files="\n".join(dup_names[:5]) +
                      (f"\n... 等共 {len(dup_names)} 个文件" if len(dup_names) > 5 else "")
            )
            self.warning_requested.emit(tr("Duplicate Files"), msg)

        eligible_paths = deduped_paths
        if not eligible_paths:
            return

        # ========== 每日总量/数量检查 ==========
        if daily_enabled:
            uploaded_size = self.db.files.get_today_upload_size()
            uploaded_count = self.db.files.get_today_upload_count()
            new_size = sum(Path(f).stat().st_size for f in eligible_paths)
            new_count = len(eligible_paths)

            if uploaded_size + new_size > daily_size_bytes:
                self.warning_requested.emit(tr("Warning"),
                    tr("Daily upload limit reached") + f" (size: {uploaded_size/1024**3:.2f}+{new_size/1024**3:.2f} > {daily_size_gb} GB)")
                return
            if uploaded_count + new_count > daily_files:
                self.warning_requested.emit(tr("Warning"),
                    tr("Daily upload limit reached") + f" (files: {uploaded_count}+{new_count} > {daily_files})")
                return

        # ========== 提交任务 ==========
        for fp in eligible_paths:
            # 提前捕获所有循环变量为闭包参数，防止延迟执行时值被覆盖
            _task_id = f"upload_{id(fp)}"
            _filename = Path(fp).name
            _ext = Path(fp).suffix.lower()
            try:
                _size = Path(fp).stat().st_size
            except OSError:
                _size = 0

            async def upload_coro(client, signals, fp=fp, dir_id=target_dir_id,
                                  _task_id=_task_id, _filename=_filename,
                                  _ext=_ext, _size=_size):
                uploader = TelethonUploader(telethon_cfg["api_id"], telethon_cfg["api_hash"])
                chat_id = "me" if dir_id == 0 else self.db.dirs.get_directory_channel(dir_id)
                dir_name = self._get_dir_name(dir_id)

                last_pct = -1
                last_emit_time = 0.0   # 时间节流：至少间隔 200ms
                def upload_progress(current, total):
                    nonlocal last_pct, last_emit_time
                    if total:
                        pct = int(current * 100 / total)
                        now = time.monotonic()
                        # 节流：百分比未变 且 距上次发射不足 200ms 则跳过
                        if pct == last_pct and (now - last_emit_time) < 0.2:
                            return
                        if pct != last_pct or (now - last_emit_time) >= 0.2:
                            signals.progress.emit(_task_id, pct)
                            last_pct = pct
                            last_emit_time = now

                file_id, msg_id, real_chat_id = await uploader.upload(
                    chat_id, fp, db=self.db, dir_id=dir_id, dir_name=dir_name,
                    client=client, progress_callback=upload_progress,
                )
                # 上传已成功 — 以下全部为本地记录操作，失败不影响 TG 端结果
                cache_dir = get_cache_dir()
                try:
                    thumb, clip = generate_media_cache(fp, cache_dir)
                except Exception:
                    logger.warning(f"[Upload] 媒体缓存生成失败，跳过: {fp}")
                    thumb, clip = None, None
                try:
                    signals.db_operation.emit(_task_id, {
                        "action": "upload_complete",
                        "file_id": file_id,
                        "msg_id": msg_id,
                        "real_chat_id": real_chat_id,
                        "name": _filename,
                        "size": _size,
                        "ext": _ext,
                        "dir_id": dir_id,
                        "local_path": fp,
                        "thumb": thumb,
                        "clip": clip,
                    })
                except Exception:
                    logger.exception(f"[Upload] db_operation 信号发射失败: {fp}")

            task = Task(
                task_id=_task_id,
                task_type="upload",
                coro=upload_coro,
                description=_filename,
                file_size=_size
            )
            self.tm.submit_task(task)

    def _get_telethon_config(self):
        return self.db.users.get_active_credentials()

    def _get_dir_name(self, dir_id):
        """获取目录的显示名称（dir_id=0 为 Root 抽象层，不应作为上传目标）。"""
        if dir_id == 0:
            return tr("Root")
        path = self.db.dirs.get_path_to_directory(dir_id)
        return path[-1][1] if path else tr("Root")

    def complete_upload(self, task_id, context):
        """完成上传记录写入（供 MainWindow 的信号回调委托）。"""
        try:
            file_pk = self.db.files.add_file(
                context["file_id"], context["msg_id"], context["real_chat_id"],
                context["name"], context["name"],
                context["dir_id"], context["size"], context.get("ext", ""),
                local_path=context.get("local_path"),
                thumbnail_path=context.get("thumb") or None,
                cached_video_path=context.get("clip") or None,
                is_sync=0,
            )
            logger.info(f"[Upload] 上传记录已保存: task={task_id}, db_id={file_pk}, name={context.get('name')}")
        except Exception as e:
            logger.error(f"[Upload] 保存上传记录失败: task={task_id}, error={e}")
            self.warning_requested.emit(
                tr("Warning"),
                tr("File uploaded but local record failed: {name}").format(
                    name=context.get("name", "?"))
            )
