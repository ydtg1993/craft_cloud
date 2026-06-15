"""FileManager — 文件/目录 CRUD 协调层。

通过 Qt Signal 与 UI 通信，不直接依赖任何 Qt Widget 类。所有操作不修改本地文件。
"""
from loguru import logger
from PySide6.QtCore import QObject, Signal
from services.sync.strategies import SyncDirectoryStrategy, NormalDirectoryStrategy
from services.telegram_operations import (
    batch_delete_tg_messages,
    batch_edit_tg_captions,
    batch_edit_tg_channel,
    delete_tg_channel,
)
from core.utils import format_file_size
from core.database import DatabaseBusyError
from core.translator import tr


class FileManager(QObject):
    """文件/目录管理服务。

    通过信号与 UI 层通信：
    - info_requested / warning_requested / error_requested → 通知信息
    - confirmation_requested → 请求确认对话框（view 层处理）
    - ui_refresh_needed / dir_model_refresh_needed → 触发 UI 刷新
    """

    info_requested = Signal(str, str)           # title, message
    warning_requested = Signal(str, str)         # title, message
    error_requested = Signal(str, str)           # title, message
    confirmation_requested = Signal(str, str, object)  # title, message, callback
    ui_refresh_needed = Signal()
    dir_model_refresh_needed = Signal()

    def __init__(self, db, config, task_manager, config_manager=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.config = config
        self.task_manager = task_manager
        self.config_manager = config_manager
        self.current_dir_id = 0
        self.sync_strategy = SyncDirectoryStrategy(self)
        self.normal_strategy = NormalDirectoryStrategy(self)

    # ---------- 视图接口 ----------
    def get_current_dir_items(self, dir_id):
        return self.db.files.get_items_in_directory(dir_id)

    def get_file_info(self, local_id):
        return self.db.files.get_file_by_id(local_id)

    def get_dir_info(self, dir_id):
        return self.db.get_directory_info(dir_id)

    def get_breadcrumb_path(self, dir_id):
        return self.db.dirs.get_path_to_directory(dir_id)

    def get_file_count(self):
        """获取文件总数（视图层安全代理）。"""
        try:
            return self.db.get_file_count()
        except Exception as e:
            logger.warning(f"获取文件总数失败: {e}")
            return 0

    def get_file_count_recursive(self, dir_id):
        """获取目录下所有文件递归计数。"""
        return len(self.db.files.get_all_files_recursive(dir_id))

    def get_all_dirs_list(self):
        """返回所有根级目录（旧接口，保留兼容）。"""
        return self.db.dirs.get_directories()

    def get_channel_dirs_list(self, dir_id):
        """获取 dir_id 所属频道下的所有目录（用于迁移下拉框）。

        跨频道不可迁移：只返回同一频道根目录下的子孙目录。
        dir_id=0（Root 抽象层）时返回空列表。
        """
        if dir_id == 0:
            return []
        channel_root = self.db.dirs.get_channel_root_id(dir_id)
        if channel_root == 0:
            return []
        # 包含频道根自身，方便用户移回根目录
        channel_info = self.db.get_directory_info(channel_root)
        root_entry = [(channel_root, channel_info.name, channel_info.is_sync)] if channel_info else []
        descendants = self.db.dirs.get_descendant_dirs(channel_root)
        return root_entry + descendants

    def _get_strategy(self, dir_id):
        return self.sync_strategy if self._is_sync_directory(dir_id) else self.normal_strategy

    # ---------- 业务方法 ----------
    def create_directory(self, name, parent_id=None):
        if parent_id is None:
            parent_id = self.current_dir_id
        if name:
            try:
                logger.info(f"[FileManager] create_directory: getting parent_info for parent_id={parent_id}")
                parent_info = self.db.get_directory_info(parent_id)
                parent_is_sync = parent_info.is_sync if parent_info else 0
                logger.info(f"[FileManager] create_directory: calling add_directory name={name}, parent={parent_id}")
                new_id = self.db.dirs.add_directory(name, parent_id, is_sync=parent_is_sync)
                logger.info(f"[FileManager] 目录已创建: id={new_id}, name={name}, parent={parent_id}")
                self.dir_model_refresh_needed.emit()
                self.ui_refresh_needed.emit()
                self.info_requested.emit(tr("Success"), f"Folder '{name}' created")
                return new_id
            except Exception:
                logger.exception(f"[FileManager] 创建目录失败: name={name}, parent={parent_id}")
                self.error_requested.emit(tr("Error"), tr("Failed to create directory"))
                return None
        return None

    def rename_file(self, local_id, new_name):
        try:
            file_info = self.db.files.get_file_by_id(local_id)
            if file_info and new_name and new_name != (file_info.display_name or file_info.original_name):
                dir_id = file_info.directory_id
                strategy = self._get_strategy(dir_id)
                strategy.rename(local_id, new_name, is_dir=False)
                logger.info(f"[FileManager] 文件已重命名: id={local_id}, {file_info.display_name or file_info.original_name} -> {new_name}")
            elif not file_info:
                logger.warning(f"[FileManager] 重命名失败: 找不到文件 id={local_id}")
            self.ui_refresh_needed.emit()
        except Exception:
            logger.exception(f"[FileManager] 重命名文件失败: id={local_id}, new_name={new_name}")
            self.error_requested.emit(tr("Error"), tr("Failed to rename file"))

    def delete_files(self, file_ids):
        """执行文件删除（view 层已处理确认对话框）。"""
        if not file_ids:
            return
        for fid in file_ids:
            try:
                info = self.db.files.get_file_by_id(fid)
                if info:
                    dir_id = info.directory_id
                    strategy = self._get_strategy(dir_id)
                    strategy.delete(fid, is_dir=False)
                    logger.info(f"[FileManager] 文件已删除: id={fid}, name={info.display_name or info.original_name}")
                else:
                    logger.warning(f"[FileManager] 删除失败: 找不到文件 id={fid}")
            except Exception:
                logger.exception(f"[FileManager] 删除文件失败: id={fid}")
        self.ui_refresh_needed.emit()

    def move_file(self, local_id, target_dir_id):
        try:
            file_info = self.db.files.get_file_by_id(local_id)
            if not file_info:
                logger.warning(f"[FileManager] 移动失败: 找不到文件 id={local_id}")
                return
            self.db.files.move_file(local_id, target_dir_id)
            logger.info(f"[FileManager] 文件已移动: id={local_id}, dir={target_dir_id}")
            self.ui_refresh_needed.emit()
        except Exception:
            logger.exception(f"[FileManager] 移动文件失败: id={local_id}, target_dir={target_dir_id}")
            self.error_requested.emit(tr("Error"), tr("Failed to move file"))

    def rename_directory(self, dir_id, new_name):
        if not new_name:
            return
        try:
            info = self.db.get_directory_info(dir_id)
            if info and info.channel_id == "me" and info.parent_id == 0:
                logger.warning("Saved Messages 是系统目录，不允许重命名")
                return
            self.db.dirs.rename_directory(dir_id, new_name)
            logger.info(f"[FileManager] 目录已重命名: id={dir_id}, new_name={new_name}")
            self.dir_model_refresh_needed.emit()
            self.ui_refresh_needed.emit()
            if info and info.parent_id == 0 and info.channel_id:
                self._batch_edit_tg_channel(info.channel_id, new_name)
                # 同步更新 config 中的 channel_name
                self._sync_config_channel_name(dir_id, new_name)
        except DatabaseBusyError:
            logger.warning(f"[FileManager] 数据库繁忙，重命名目录被拒绝: id={dir_id}")
            self.error_requested.emit(tr("Database Busy"), tr("Database is busy, please try again"))
        except Exception:
            logger.exception(f"[FileManager] 重命名目录失败: id={dir_id}, new_name={new_name}")
            self.error_requested.emit(tr("Error"), tr("Failed to rename directory"))

    def _sync_config_channel_name(self, dir_id, new_name):
        """将目录重命名同步到对应同步文件夹配置的 channel_name，并持久化。"""
        folders = self.config.get("auto_sync_settings", {}).get("folders", {})
        for folder_path, cfg in folders.items():
            if cfg.get("target_dir_id") == dir_id:
                if cfg.get("channel_name") != new_name:
                    cfg["channel_name"] = new_name
                    if self.config_manager:
                        self.config_manager.save()
                    logger.info(f"[FileManager] 同步配置 channel_name: {folder_path} -> {new_name}")
                break

    def delete_directory(self, dir_id):
        """执行目录删除（view 层已处理确认对话框）。"""
        try:
            info = self.db.get_directory_info(dir_id)
            if not info:
                logger.warning(f"[FileManager] 删除目录失败: 找不到目录 id={dir_id}")
                return
            if info.channel_id == "me" and info.parent_id == 0:
                logger.warning("Saved Messages 是系统目录，不允许删除")
                return
            parent_id = info.parent_id
            channel_id = info.channel_id
            files = self.db.files.get_all_files_recursive(dir_id)
            logger.info(f"[FileManager] 删除目录: id={dir_id}, name={info.name}, files={len(files)}")
            if parent_id == 0 and channel_id:
                self.db.dirs.delete_directory_recursive(dir_id)
                self.dir_model_refresh_needed.emit()
                self.ui_refresh_needed.emit()
                self._delete_tg_channel(channel_id)
            else:
                messages = [(f.chat_id, f.message_id) for f in files if f.message_id and f.chat_id]
                self.db.dirs.delete_directory_recursive(dir_id)
                self.dir_model_refresh_needed.emit()
                self.ui_refresh_needed.emit()
                self._batch_delete_tg_messages(messages)
        except DatabaseBusyError:
            logger.warning(f"[FileManager] 数据库繁忙，删除目录被拒绝: id={dir_id}")
            self.error_requested.emit(tr("Database Busy"), tr("Database is busy, please try again"))
        except Exception:
            logger.exception(f"[FileManager] 删除目录失败: id={dir_id}")
            self.error_requested.emit(tr("Error"), tr("Failed to delete directory"))

    # ---------- 异步 TG 操作（委托到 telegram_operations 模块） ----------
    def _batch_delete_tg_messages(self, msg_list):
        batch_delete_tg_messages(msg_list, self.task_manager)

    def _batch_edit_tg_captions(self, edit_list):
        batch_edit_tg_captions(edit_list, self.task_manager)

    def _batch_edit_tg_channel(self, channel_id, new_title):
        batch_edit_tg_channel(channel_id, new_title, self.task_manager)

    def _delete_tg_channel(self, channel_id):
        delete_tg_channel(channel_id, self.task_manager)

    # ---------- 同步目录专用操作（策略内部调用） ----------
    def delete_sync_file_tg_only(self, file_id):
        file_info = self.db.files.get_file_by_id(file_id)
        if not file_info:
            return
        chat_id, message_id = file_info.chat_id, file_info.message_id
        if chat_id and message_id:
            self._batch_delete_tg_messages([(chat_id, message_id)])
        self.db.files.delete_file(file_id)

    def rename_sync_file_tg_only(self, file_id, new_name):
        file_info = self.db.files.get_file_by_id(file_id)
        if not file_info:
            return
        chat_id, message_id = file_info.chat_id, file_info.message_id
        if chat_id and message_id:
            self._batch_edit_tg_captions([(chat_id, message_id, new_name)])
        self.db.files.update_display_name(file_id, new_name)
        if file_info.original_name != new_name:
            self.db.files.update_file_original_name(file_id, file_info.original_name)

    def delete_sync_directory_tg_only(self, dir_id):
        dir_info = self.db.get_directory_info(dir_id)
        if not dir_info:
            return
        channel_id = dir_info.channel_id
        if channel_id:
            self._delete_tg_channel(channel_id)
        self.db.dirs.delete_directory_recursive(dir_id)

    def rename_sync_directory_tg_only(self, dir_id, new_name):
        dir_info = self.db.get_directory_info(dir_id)
        if not dir_info:
            return
        channel_id, parent_id = dir_info.channel_id, dir_info.parent_id
        if parent_id == 0 and channel_id:
            self._batch_edit_tg_channel(channel_id, new_name)
        self.db.dirs.rename_directory(dir_id, new_name)

    # ---------- 辅助 ----------
    def get_properties_text(self, file_info):
        """返回文件属性文本。view 层负责显示。"""
        if not file_info:
            return ""
        return (
            f"Name: {file_info.original_name or file_info.display_name}\n"
            f"Size: {format_file_size(file_info.file_size)}\n"
            f"Type: {file_info.mime_type or 'Unknown'}\n"
            f"Upload time: {file_info.upload_time}\n"
            f"Telegram File ID: {file_info.file_id}\n"
            f"Message ID: {file_info.message_id}\n"
            f"Chat ID: {file_info.chat_id}\n"
            f"Local ID: {file_info.id}"
        )

    def _is_sync_directory(self, dir_id):
        info = self.db.get_directory_info(dir_id)
        return info is not None and info.is_sync == 1
