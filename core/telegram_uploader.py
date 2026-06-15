import threading
from pathlib import Path
from telethon import TelegramClient
from telethon.tl.functions.channels import CreateChannelRequest, EditPhotoRequest
from telethon.errors import RPCError
from core.utils import get_sessions_dir, resource_path
from core.translator import tr
from loguru import logger
WORK_DIR = str(get_sessions_dir())

# 按 top_dir_id 串行化 ensure_channel，防止并发上传时创建多个频道
_ensure_channel_locks = {}
_ensure_channel_locks_guard = threading.Lock()


def _get_ensure_channel_lock(dir_id):
    """获取指定目录的频道创建锁，确保同一目录不会并发创建多个频道。"""
    with _ensure_channel_locks_guard:
        if dir_id not in _ensure_channel_locks:
            _ensure_channel_locks[dir_id] = threading.Lock()
        return _ensure_channel_locks[dir_id]


class TelethonUploader:
    def __init__(self, api_id, api_hash):
        self.api_id = api_id
        self.api_hash = api_hash

    async def ensure_channel(self, client, dir_name, dir_id, db):
        # 1. 向上查找到根级父目录
        top_dir_id = dir_id
        top_dir_name = dir_name
        current = dir_id
        while True:
            info = db.get_directory_info(current)
            if not info:
                break
            name = info.name
            parent_id = info.parent_id
            if parent_id == 0:
                top_dir_id = current
                top_dir_name = name
                break
            else:
                current = parent_id

        if top_dir_name == tr("Root"):
            return "me"

        # 2. 无锁快速路径 — 频道已存在且有效
        existing = db.dirs.get_directory_channel(top_dir_id)
        if existing == "me":
            return "me"
        if existing:
            try:
                from telethon.tl.types import PeerChannel
                await client.get_entity(PeerChannel(int(existing)))
                return existing
            except (ValueError, RPCError):
                logger.warning(f"[Upload] 频道 {existing} 无效，将重新创建")
                db.dirs.set_directory_channel(top_dir_id, None, _bg=True)

        # 3. 加锁创建频道 — 防止并发任务重复创建
        lock = _get_ensure_channel_lock(top_dir_id)
        with lock:
            # 锁内再次检查：可能另一个任务刚刚创建完毕
            existing = db.dirs.get_directory_channel(top_dir_id)
            if existing:
                if existing == "me":
                    return "me"
                try:
                    from telethon.tl.types import PeerChannel
                    await client.get_entity(PeerChannel(int(existing)))
                    return existing
                except (ValueError, RPCError):
                    db.dirs.set_directory_channel(top_dir_id, None, _bg=True)

            # 确认不存在 → 创建新频道
            result = await client(CreateChannelRequest(
                title=top_dir_name,
                about=f"Auto-created by CraftCloud for folder '{top_dir_name}'",
                megagroup=False,
                broadcast=True,
            ))
            chat_id = None
            chat_title = top_dir_name
            for chat in result.chats:
                chat_id = chat.id
                chat_title = chat.title
                break
            if chat_id is None:
                raise Exception("无法创建频道：未获取到 chat_id")
            db.dirs.set_directory_channel(top_dir_id, chat_id, _bg=True)
            logger.info(f"[Upload] 已为新目录创建频道: {chat_id} ({chat_title})")

        # 4. 设置头像（锁外执行，非关键路径）
        try:
            avatar_path = resource_path("tc.png")
            if avatar_path.exists():
                from telethon.tl.types import InputChatUploadedPhoto
                uploaded = await client.upload_file(str(avatar_path))
                await client(EditPhotoRequest(
                    channel=await client.get_input_entity(chat_id),
                    photo=InputChatUploadedPhoto(uploaded),
                ))
            else:
                logger.warning(f"[Upload] 头像文件不存在: {avatar_path}")
        except Exception as e:
            logger.warning(f"[Upload] 设置频道头像失败: {e}")
        return chat_id

    async def upload(self, chat_id, file_path, db=None, dir_id=None, dir_name=None,
                     client=None, progress_callback=None):
        if client is None:
            client = TelegramClient(
                str(get_sessions_dir() / "my_account.session"),
                self.api_id,
                self.api_hash,
            )
            async with client:
                return await self._upload_impl(
                    client, chat_id, file_path, db, dir_id, dir_name, progress_callback
                )
        else:
            return await self._upload_impl(
                client, chat_id, file_path, db, dir_id, dir_name, progress_callback
            )

    async def _upload_impl(self, client, chat_id, file_path, db, dir_id, dir_name,
                           progress_callback=None):
        # 仅当 chat_id 为 None 时才需要解析/创建频道
        # "me" 和数字 channel_id 都是有效目标，无需 ensure_channel
        if db and dir_id and dir_name and chat_id is None:
            chat_id = await self.ensure_channel(client, dir_name, dir_id, db)
        if chat_id is None:
            chat_id = "me"

        async def _resolve_entity(cid):
            """将 chat_id 解析为 Telethon entity；解析失败返回 None。"""
            if isinstance(cid, (int, str)) and cid != "me":
                try:
                    return await client.get_input_entity(int(cid))
                except (ValueError, TypeError):
                    return None
            return cid

        async def _do_send(target):
            """发送文件，self-healing：目标无效时清除旧 channel 并重建。"""
            kwargs = {"force_document": True}
            if progress_callback:
                kwargs["progress_callback"] = progress_callback
            try:
                entity = await _resolve_entity(target)
                if entity is None:
                    raise ValueError(f"Cannot resolve entity for {target}")
                return await client.send_file(entity, file_path, **kwargs)
            except (ValueError, RPCError) as e:
                logger.warning(f"[Upload] 频道无效 ({e})，尝试重建")
                if db and dir_id and dir_name and dir_id != 0:
                    db.dirs.set_directory_channel(dir_id, None, _bg=True)
                    new_cid = await self.ensure_channel(client, dir_name, dir_id, db)
                    entity = await _resolve_entity(new_cid)
                    if entity is None:
                        raise
                    return await client.send_file(entity, file_path, **kwargs)
                else:
                    return await client.send_file("me", file_path, **kwargs)

        msg = await _do_send(chat_id)

        file_id = None
        if msg is None:
            raise Exception(tr("Upload failed: No response from Telegram."))
        media = msg.media
        if hasattr(media, 'document') and media.document:
            file_id = media.document.id
        elif hasattr(media, 'photo') and media.photo:
            file_id = media.photo.id
        else:
            raise Exception(tr("Upload failed: No media in the message."))

        if hasattr(msg.peer_id, 'channel_id'):
            real_chat_id = int(f"-100{msg.peer_id.channel_id}")
        elif hasattr(msg.peer_id, 'user_id'):
            real_chat_id = msg.peer_id.user_id
        else:
            real_chat_id = chat_id
        return file_id, msg.id, real_chat_id
