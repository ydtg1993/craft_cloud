"""SQLAlchemy ORM models for the CraftCloud database.

All models map 1:1 to existing tables. Schema MUST NOT change.

Namedtuples are defined here for backward compatibility — they were previously
in core/db_manager.py and model/file_repository.py; callers import them from
those modules, which now re-export from here.
"""
from collections import namedtuple
from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, text,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()

# ---------------------------------------------------------------------------
# Namedtuples — preserved for backward compatibility with all callers
# ---------------------------------------------------------------------------

DirectoryRecord = namedtuple('DirectoryRecord', [
    'id', 'name', 'parent_id', 'channel_id', 'is_sync', 'created_time'
])

FileRecord = namedtuple('FileRecord', [
    'id', 'file_id', 'message_id', 'chat_id',
    'original_name', 'display_name', 'directory_id',
    'file_size', 'mime_type', 'is_sync', 'upload_time',
    'local_path', 'file_hash', 'thumbnail_path', 'cached_video_path'
])

DirectoryItem = namedtuple('DirectoryItem', [
    'id', 'name', 'is_dir', 'message_id', 'original_name', 'display_name',
    'file_size', 'upload_time', 'mime_type', 'thumbnail_path', 'is_sync'
])


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------

class Directory(Base):
    __tablename__ = 'directories'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    parent_id = Column(Integer, default=0)
    channel_id = Column(String)
    is_sync = Column(Integer, default=0)
    created_time = Column(Text, server_default=text("CURRENT_TIMESTAMP"))

    def to_record(self) -> DirectoryRecord:
        return DirectoryRecord(
            self.id, self.name, self.parent_id, self.channel_id,
            self.is_sync, self.created_time
        )


class File(Base):
    __tablename__ = 'files'

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(String, nullable=False)
    message_id = Column(Integer)
    chat_id = Column(Integer, nullable=False)
    original_name = Column(String)
    display_name = Column(String)
    directory_id = Column(Integer, default=0)
    file_size = Column(Integer)
    mime_type = Column(String)
    is_sync = Column(Integer, default=0)
    upload_time = Column(Text, server_default=text("CURRENT_TIMESTAMP"))
    local_path = Column(Text)
    file_hash = Column(Text)
    thumbnail_path = Column(Text)
    cached_video_path = Column(Text)

    def to_record(self) -> FileRecord:
        return FileRecord(
            self.id, self.file_id, self.message_id, self.chat_id,
            self.original_name, self.display_name, self.directory_id,
            self.file_size, self.mime_type, self.is_sync, self.upload_time,
            self.local_path, self.file_hash, self.thumbnail_path,
            self.cached_video_path
        )


class AutoSyncStatus(Base):
    __tablename__ = 'auto_sync_status'

    folder_path = Column(String, primary_key=True)
    total_files = Column(Integer, default=0)
    synced_files = Column(Integer, default=0)
    status = Column(Integer, default=0)  # 0=pending, 1=success, 2=failed
    last_sync_time = Column(Text)
    error_message = Column(Text)


class DailyUploadLog(Base):
    __tablename__ = 'daily_upload_log'

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_size = Column(Integer, nullable=False)
    upload_time = Column(Text, server_default=text("CURRENT_TIMESTAMP"))


class TaskHistory(Base):
    """持久化已完成/失败的任务记录。正在进行的任务不入库，仅存内存。"""
    __tablename__ = 'task_history'

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String, nullable=False, index=True)
    task_type = Column(String, nullable=False)          # upload / download / delete_message / rename / etc.
    description = Column(String, default="")            # UI 显示用（文件名等）
    file_size = Column(String, default="")              # 文件大小（显示用字符串）
    status = Column(String, nullable=False)             # completed / failed
    error_msg = Column(Text, default="")                # 失败时的错误信息
    created_time = Column(Text, server_default=text("CURRENT_TIMESTAMP"))

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "description": self.description,
            "file_size": self.file_size,
            "status": self.status,
            "error_msg": self.error_msg,
            "created_time": self.created_time,
        }


class User(Base):
    """用户表 — 支持多用户管理，后续迭代扩展。"""
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    tg_id = Column(BigInteger, nullable=False, unique=True)   # Telegram user ID
    api_id = Column(Integer, nullable=False)                  # Telegram API ID
    api_hash = Column(String, nullable=False)                 # Telegram API hash
    phone = Column(String, default="")                        # 手机号
    username = Column(String, default="")                     # 用户名/昵称
    avatar = Column(Text, default="")                         # 头像路径或URL
    active = Column(Integer, default=0)                       # 是否当前激活用户 (0/1)
    login_at = Column(Text, server_default=text("CURRENT_TIMESTAMP"))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tg_id": self.tg_id,
            "api_id": self.api_id,
            "api_hash": self.api_hash,
            "phone": self.phone,
            "username": self.username,
            "avatar": self.avatar,
            "active": bool(self.active),
            "login_at" : self.login_at,
        }
