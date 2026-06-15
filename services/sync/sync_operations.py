"""同步目录专用操作。

这些方法仅操作 Telegram + 数据库，不操作本地文件系统。
被 SyncDirectoryStrategy 调用。
"""
from services.telegram_operations import (
    batch_delete_tg_messages,
    batch_edit_tg_captions,
    batch_edit_tg_channel,
    delete_tg_channel,
)


def delete_sync_file_tg_only(file_id, db):
    """同步目录：仅删除 TG 消息和数据库记录，保留本地文件。"""
    file_info = db.files.get_file_by_id(file_id)
    if not file_info:
        return None
    chat_id, message_id = file_info.chat_id, file_info.message_id
    if chat_id and message_id:
        return [("delete_msg", chat_id, message_id)]
    db.files.delete_file(file_id)
    return None


def rename_sync_file_tg_only(file_id, new_name, db):
    """同步目录：仅修改 TG caption 和数据库显示名，保留本地文件名。"""
    file_info = db.files.get_file_by_id(file_id)
    if not file_info:
        return None
    chat_id, message_id = file_info.chat_id, file_info.message_id
    if chat_id and message_id:
        result = [("edit_caption", chat_id, message_id, new_name)]
    else:
        result = None
    db.files.update_display_name(file_id, new_name)
    if file_info.original_name != new_name:
        db.files.update_file_original_name(file_id, file_info.original_name)
    return result


def delete_sync_directory_tg_only(dir_id, db):
    """同步目录：仅删除 TG 频道和数据库记录，保留本地文件夹。"""
    dir_info = db.get_directory_info(dir_id)
    if not dir_info:
        return None
    channel_id = dir_info.channel_id
    db.dirs.delete_directory_recursive(dir_id)
    if channel_id:
        return ("delete_channel", channel_id)
    return None


def rename_sync_directory_tg_only(dir_id, new_name, db):
    """同步目录：仅修改 TG 频道标题和数据库记录，保留本地文件夹名。"""
    dir_info = db.get_directory_info(dir_id)
    if not dir_info:
        return None
    channel_id, parent_id = dir_info.channel_id, dir_info.parent_id
    db.dirs.rename_directory(dir_id, new_name)
    if parent_id == 0 and channel_id:
        return ("edit_channel", channel_id, new_name)
    return None
