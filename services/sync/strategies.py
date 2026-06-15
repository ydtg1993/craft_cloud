"""同步操作策略模式。

位于 services/sync/ 而非 core/，因为策略依赖 FileManager 和 Telegram 操作，
属于业务层而非基础设施层。
"""
from abc import ABC, abstractmethod


class SyncOperationStrategy(ABC):
    """同步操作策略基类"""

    @abstractmethod
    def delete(self, item_id, is_dir=False):
        pass

    @abstractmethod
    def rename(self, item_id, new_name, is_dir=False):
        pass

    @abstractmethod
    def move(self, item_id, target_dir_id, is_dir=False):
        pass


class SyncDirectoryStrategy(SyncOperationStrategy):
    """同步目录策略：只操作TG和数据库，不操作本地"""

    def __init__(self, file_manager):
        self.file_manager = file_manager

    def delete(self, item_id, is_dir=False):
        if is_dir:
            self.file_manager.delete_sync_directory_tg_only(item_id)
        else:
            self.file_manager.delete_sync_file_tg_only(item_id)

    def rename(self, item_id, new_name, is_dir=False):
        if is_dir:
            self.file_manager.rename_sync_directory_tg_only(item_id, new_name)
        else:
            self.file_manager.rename_sync_file_tg_only(item_id, new_name)

    def move(self, item_id, target_dir_id, is_dir=False):
        if is_dir:
            self.file_manager.db.dirs.move_directory(item_id, target_dir_id)
        else:
            self.file_manager.db.files.move_file(item_id, target_dir_id)


class NormalDirectoryStrategy(SyncOperationStrategy):
    def __init__(self, file_manager):
        self.file_manager = file_manager

    def delete(self, item_id, is_dir=False):
        if is_dir:
            dir_info = self.file_manager.db.get_directory_info(item_id)
            if not dir_info:
                return
            files = self.file_manager.db.files.get_all_files_recursive(item_id)
            messages_to_delete = [(f.chat_id, f.message_id) for f in files if f.message_id and f.chat_id]
            self.file_manager.db.dirs.delete_directory_recursive(item_id)
            self.file_manager.dir_model_refresh_needed.emit()
            self.file_manager.ui_refresh_needed.emit()
            self.file_manager._batch_delete_tg_messages(messages_to_delete)
        else:
            file_info = self.file_manager.db.files.get_file_by_id(item_id)
            if not file_info:
                return
            chat_id = file_info.chat_id
            message_id = file_info.message_id
            if chat_id and message_id:
                self.file_manager._batch_delete_tg_messages([(chat_id, message_id)])
            self.file_manager.db.files.delete_file(item_id)

    def rename(self, item_id, new_name, is_dir=False):
        if is_dir:
            dir_info = self.file_manager.db.get_directory_info(item_id)
            if not dir_info:
                return
            parent_id = dir_info.parent_id
            channel_id = dir_info.channel_id
            self.file_manager.db.dirs.rename_directory(item_id, new_name)
            self.file_manager.dir_model_refresh_needed.emit()
            self.file_manager.ui_refresh_needed.emit()
            if parent_id == 0 and channel_id:
                self.file_manager._batch_edit_tg_channel(channel_id, new_name)
        else:
            file_info = self.file_manager.db.files.get_file_by_id(item_id)
            if not file_info:
                return
            chat_id = file_info.chat_id
            message_id = file_info.message_id
            if chat_id and message_id:
                self.file_manager._batch_edit_tg_captions([(chat_id, message_id, new_name)])
            self.file_manager.db.files.update_display_name(item_id, new_name)
            original_name = file_info.original_name
            if original_name != new_name:
                self.file_manager.db.files.update_file_original_name(item_id, original_name)

    def move(self, item_id, target_dir_id, is_dir=False):
        if is_dir:
            self.file_manager.db.dirs.move_directory(item_id, target_dir_id)
            self.file_manager.dir_model_refresh_needed.emit()
            self.file_manager.ui_refresh_needed.emit()
        else:
            self.file_manager.db.files.move_file(item_id, target_dir_id)
