"""同步任务基类 —— 提取 DirectorySyncTask 和 FileSyncTask 的共享代码。"""
import asyncio
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from telethon import TelegramClient
from telethon.tl.types import PeerChannel
from telethon.tl.functions.channels import EditTitleRequest
from telethon.errors import RPCError
from loguru import logger

from core.db_manager import DBManager
from core.telegram_uploader import TelethonUploader
from core.utils import get_sessions_dir
from core.translator import tr
from model.shared_types import SYNC_FAILED

WORK_DIR = get_sessions_dir()


def _cleanup_sync_session():
    """Clean up thread-local SQLAlchemy scoped_session after sync task.

    QThreadPool reuses threads; without this the next task on this
    thread would inherit a stale session from the previous run.
    """
    try:
        from core.database import get_session_factory
        get_session_factory().remove()
    except Exception:
        pass


class BaseSyncTask:
    """同步任务基类 —— 提供 TG 客户端管理、频道验证/重建、消息操作等共享能力。

    运行在独立线程上，子类需实现 _do_sync(target_dir_id, telethon_cfg, folder_config) 方法。
    """

    class Signals(QObject):
        completed = Signal(int)
        error = Signal(str)
        progress = Signal(int, int)
        cancelled = Signal()
        finished = Signal()

    def __init__(self, folder_path, config_manager, db, stop_event):
        super().__init__()
        self.folder_path = folder_path
        self.config_manager = config_manager
        self.db = db
        self.stop_event = stop_event
        self.signals = self.Signals()
        self.client = None
        self.loop = None

    @property
    def _log_tag(self):
        return self.__class__.__name__

    def cancel(self):
        """设置停止标志并断开 TG 客户端。"""
        self.stop_event.set()
        if self.client:
            try:
                self.client.disconnect()
            except Exception as e:
                from loguru import logger
                logger.warning(f"取消同步时断开客户端失败: {e}")

    # ── Telethon 配置 ──────────────────────────────────────────

    def _get_telethon_config(self):
        """获取 Telethon 配置信息（从 users 表读取当前激活用户凭证）。"""
        return self.db.users.get_active_credentials()

    # ── 客户端生命周期 ────────────────────────────────────────

    def _start_client(self):
        """创建并启动 Telethon Client。"""
        from core.tg_client import ensure_session_wal
        ensure_session_wal()
        cfg = self._get_telethon_config()
        self.client = TelegramClient(
            str(WORK_DIR / "my_account.session"),
            cfg["api_id"],
            cfg["api_hash"],
        )
        self.client.start()

    def _stop_client(self):
        """安全停止 Telethon Client，显式关闭 SQLite session。"""
        if self.client:
            try:
                self.client.disconnect()
            except Exception as e:
                from loguru import logger
                logger.warning(f"停止客户端失败: {e}")
            try:
                if hasattr(self.client, 'session') and self.client.session:
                    self.client.session.close()
            except Exception as e:
                from loguru import logger
                logger.debug(f"session.close 失败: {e}")

    # ── 频道验证与重建 ────────────────────────────────────────

    def _validate_and_rebuild_channel(self, target_dir_id, telethon_cfg):
        """验证频道是否可访问，不可访问则触发重建。

        频道已在配置时创建，这里只做验证 + 按需重建。
        """
        if target_dir_id == 0:
            return target_dir_id

        session_file = WORK_DIR / "my_account.session"
        if not session_file.exists():
            logger.warning(f"[{self._log_tag}] 会话文件不存在，无法验证频道")
            return None

        dir_exists = self.db.directory_exists(target_dir_id)
        old_channel = None
        if dir_exists:
            old_channel = self.db.dirs.get_directory_channel(target_dir_id)

        if not dir_exists:
            # 目录记录丢失（异常情况），触发重建
            logger.warning(f"[{self._log_tag}] 目录 {target_dir_id} 在数据库中不存在，触发重建")
            return self._rebuild_channel(target_dir_id, telethon_cfg)

        if not old_channel or old_channel == "me":
            # 频道尚未创建或指向 Saved Messages，提示需要配置
            logger.warning(f"[{self._log_tag}] 目录 {target_dir_id} 无有效频道 (channel={old_channel})")
            return target_dir_id

        async def _check():
            try:
                await self.client.get_entity(PeerChannel(int(old_channel)))
                return True, None
            except ValueError:
                return False, "PeerIdInvalid"
            except RPCError as e:
                return False, str(e)
            except Exception as e:
                return None, str(e)

        valid, reason = self.loop.run_until_complete(_check())

        if valid is True:
            return target_dir_id
        elif valid is False:
            logger.warning(f"[{self._log_tag}] 频道 {old_channel} 不可访问（{reason}），触发重建")
            return self._rebuild_channel(target_dir_id, telethon_cfg)
        else:
            logger.warning(f"[{self._log_tag}] 频道验证临时失败 ({reason})，放弃本次同步")
            return None

    def _rebuild_channel(self, target_dir_id, telethon_cfg):
        """仅重建 Telegram 频道，保留已有的目录树和文件记录。

        原实现在重建时会级联删除整个目录树，导致所有已同步文件
        记录丢失。新实现只更换旧的 channel_id，目录结构不受影响。
        """
        try:
            folder_cfg = (
                self.config_manager.config.get("auto_sync_settings", {})
                .get("folders", {})
                .get(self.folder_path, {})
            )
            folder_name = folder_cfg.get("channel_name") or Path(self.folder_path).name or tr("Sync Folder")

            # 目录记录仍存在则复用，否则新建
            dir_exists = self.db.directory_exists(target_dir_id)
            if not dir_exists:
                dir_id = self.db.dirs.add_directory(folder_name, parent_id=0, is_sync=1, _bg=True)
                logger.info(f"[{self._log_tag}] 目录记录缺失，已重新创建: id={dir_id}")
            else:
                dir_id = target_dir_id
                # 清除旧 channel_id，强制 ensure_channel 创建新频道
                self.db.dirs.set_directory_channel(dir_id, None, _bg=True)

            uploader = TelethonUploader(telethon_cfg["api_id"], telethon_cfg["api_hash"])

            async def _create_new():
                return await uploader.ensure_channel(
                    self.client, folder_name, dir_id, self.db
                )

            new_channel = self.loop.run_until_complete(_create_new())
            logger.info(f"[{self._log_tag}] 频道已重建: channel={new_channel}, dir_id={dir_id}")

            # 仅当目录是新建的才更新 config
            if dir_id != target_dir_id:
                sync_settings = (
                    self.config_manager.config.get("auto_sync_settings", {}).get("folders", {})
                )
                if self.folder_path in sync_settings:
                    sync_settings[self.folder_path]["target_dir_id"] = dir_id
                self.config_manager.save()

            return dir_id
        except Exception as e:
            logger.error(f"[{self._log_tag}] 重建频道失败: {e}")
            return None

    # ── TG 消息操作 ────────────────────────────────────────────

    def _delete_tg_message(self, chat_id, message_id):
        """删除 TG 消息。"""
        try:
            async def _delete():
                await self.client.delete_messages(chat_id, message_id)

            self.loop.run_until_complete(_delete())
        except Exception as e:
            logger.error(f"[{self._log_tag}] 删除消息失败: {e}")

    def _edit_tg_message_caption(self, chat_id, message_id, new_caption):
        """编辑 TG 消息的 caption。"""
        try:
            async def _edit():
                await self.client.edit_message(chat_id, message_id, text=new_caption)

            self.loop.run_until_complete(_edit())
        except Exception as e:
            logger.error(f"[{self._log_tag}] 编辑 caption 失败: {e}")

    def _edit_tg_channel_title(self, channel_id, new_title):
        """编辑 TG 频道标题。"""
        try:
            async def _edit():
                entity = await self.client.get_input_entity(int(channel_id))
                await self.client(EditTitleRequest(channel=entity, title=new_title))

            self.loop.run_until_complete(_edit())
        except Exception as e:
            logger.error(f"[{self._log_tag}] 修改频道标题失败: {e}")

    # ── 目录名查询 ────────────────────────────────────────────

    def _get_dir_name(self, dir_id):
        """获取目录的显示名称（dir_id=0 为 Root 抽象层）。"""
        if dir_id == 0:
            return tr("Root")
        path = self.db.dirs.get_path_to_directory(dir_id)
        return path[-1][1] if path else tr("Root")

    # ── 模板方法 ──────────────────────────────────────────────

    def run(self):
        """模板方法：设置事件循环 → 启动客户端 → 验证频道 → 调用 _do_sync() → 清理。"""
        if self.stop_event.is_set():
            self.signals.cancelled.emit()
            self.signals.finished.emit()
            return

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            config = self.config_manager.config
            sync_settings = config.get("auto_sync_settings", {})
            folder_config = sync_settings.get("folders", {}).get(self.folder_path, {})

            if not Path(self.folder_path).exists():
                self.signals.error.emit(
                    tr("Folder does not exist") + f": {self.folder_path}"
                )
                return

            telethon_cfg = self._get_telethon_config()
            if not telethon_cfg:
                self.signals.error.emit(tr("Telethon not logged in"))
                return

            self._start_client()

            target_dir_id = folder_config.get("target_dir_id", 0)
            target_dir_id = self._validate_and_rebuild_channel(target_dir_id, telethon_cfg)
            if target_dir_id is None:
                msg = tr("Cannot prepare sync directory, aborting")
                logger.error(f"[{self._log_tag}] 无法准备同步目录: {self.folder_path} -> {msg}")
                self.signals.error.emit(msg)
                return

            # 调用子类实现的同步逻辑
            self._do_sync(target_dir_id, telethon_cfg, folder_config)

        except Exception as e:
            self.db.sync_status.upsert_sync_folder_status(
                self.folder_path, status=SYNC_FAILED, error_message=str(e), _bg=True
            )
            self.signals.error.emit(str(e))
        finally:
            self._stop_client()
            if self.loop:
                self.loop.close()
            # 线程池线程复用前清理 scoped_session
            _cleanup_sync_session()
            self.signals.finished.emit()

    def _do_sync(self, target_dir_id, telethon_cfg, folder_config):
        """子类实现具体同步逻辑。

        Args:
            target_dir_id: 目标目录 ID
            telethon_cfg: Telethon 配置 dict
            folder_config: 文件夹配置 dict
        """
        raise NotImplementedError("子类必须实现 _do_sync()")
