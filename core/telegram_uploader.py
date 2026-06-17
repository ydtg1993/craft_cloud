import asyncio
import threading
import time
from pathlib import Path
from telethon import TelegramClient
from telethon.tl.functions.channels import CreateChannelRequest, EditPhotoRequest
from telethon.tl.types import DocumentAttributeFilename
from telethon.errors import RPCError
from core.utils import get_sessions_dir, resource_path
from core.translator import tr
from loguru import logger
WORK_DIR = str(get_sessions_dir())

# 按 top_dir_id 串行化 ensure_channel，防止并发上传时创建多个频道
_ensure_channel_locks = {}
_ensure_channel_locks_guard = threading.Lock()

# InputPeer 实体缓存：避免每次上传都发起 get_input_entity 网络请求
# key: channel_id (int), value: InputPeer (或 "me")
_entity_cache = {}
_entity_cache_lock = threading.Lock()


def _get_ensure_channel_lock(dir_id):
    """获取指定目录的频道创建锁，确保同一目录不会并发创建多个频道。"""
    with _ensure_channel_locks_guard:
        if dir_id not in _ensure_channel_locks:
            _ensure_channel_locks[dir_id] = threading.Lock()
        return _ensure_channel_locks[dir_id]


def _invalidate_entity_cache(channel_id):
    """清除指定 channel_id 的实体缓存（频道重建/失效时调用）。"""
    with _entity_cache_lock:
        key = int(channel_id) if not isinstance(channel_id, int) else channel_id
        _entity_cache.pop(key, None)
        logger.debug(f"[EntityCache] 已清除 channel={key} 的缓存")


def _clear_entity_cache():
    """清除全部实体缓存（session 变更时调用）。"""
    with _entity_cache_lock:
        count = len(_entity_cache)
        _entity_cache.clear()
        if count:
            logger.debug(f"[EntityCache] 已清除全部 {count} 条缓存")


def throttled_progress_callback(callback, min_interval=0.2):
    """工厂函数：返回一个时间节流的进度回调包装器。

    节流策略：
    - 百分比首次变化 → 立即调用
    - 百分比未变化 → 至少间隔 min_interval 秒后才调用
    - 百分比变化 + 距上次调用 >= min_interval → 立即调用

    这避免了 send_file 的高频 chunk 回调阻塞事件循环，
    同时保证 UI 进度条仍有流畅的更新频率。

    Args:
        callback: 原始 progress_callback(current, total)
        min_interval: 最小调用间隔（秒），默认 200ms

    Returns:
        包装后的 progress_callback(current, total)
    """
    state = {"last_pct": -1, "last_time": 0.0}

    def wrapper(current, total):
        if not total:
            return
        pct = int(current * 100 / total)
        now = time.monotonic()
        elapsed = now - state["last_time"]

        # 节流检查：百分比未变且间隔不足则跳过
        if pct == state["last_pct"] and elapsed < min_interval:
            return

        # 满足任一条件则发射：百分比变化 OR 间隔足够
        if pct != state["last_pct"] or elapsed >= min_interval:
            callback(current, total)
            state["last_pct"] = pct
            state["last_time"] = now

    return wrapper


class TelethonUploader:
    def __init__(self, api_id, api_hash):
        self.api_id = api_id
        self.api_hash = api_hash

    async def ensure_channel(self, client, dir_name, dir_id, db):
        # 1. 向上查找到根级父目录（异步执行 DB 查询，避免阻塞事件循环）
        top_dir_id = dir_id
        top_dir_name = dir_name
        current = dir_id
        loop = asyncio.get_event_loop()
        while True:
            info = await loop.run_in_executor(None, db.get_directory_info, current)
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
                # 优先使用 entity 缓存验证频道有效性
                cache_key = int(existing)
                with _entity_cache_lock:
                    cached = _entity_cache.get(cache_key)
                if cached is not None:
                    return existing
                from telethon.tl.types import PeerChannel
                await client.get_entity(PeerChannel(cache_key))
                return existing
            except (ValueError, RPCError):
                logger.warning(f"[Upload] 频道 {existing} 无效，将重新创建")
                _invalidate_entity_cache(existing)
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
                    cache_key = int(existing)
                    with _entity_cache_lock:
                        cached = _entity_cache.get(cache_key)
                    if cached is not None:
                        return existing
                    from telethon.tl.types import PeerChannel
                    await client.get_entity(PeerChannel(cache_key))
                    return existing
                except (ValueError, RPCError):
                    _invalidate_entity_cache(existing)
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
            """将 chat_id 解析为 Telethon entity；解析失败返回 None。

            使用模块级 _entity_cache 避免每次上传都发起 get_input_entity
            网络请求。缓存 key 为 channel_id (int) 或其字符串表示。"""
            if not isinstance(cid, (int, str)) or cid == "me":
                return cid

            cache_key = int(cid) if not isinstance(cid, int) else cid
            with _entity_cache_lock:
                cached = _entity_cache.get(cache_key)
            if cached is not None:
                return cached

            try:
                entity = await client.get_input_entity(int(cid))
            except (ValueError, TypeError):
                return None

            if entity is not None:
                with _entity_cache_lock:
                    _entity_cache[cache_key] = entity
            return entity

        async def _do_send(target):
            """发送文件，self-healing：目标无效时清除旧 channel 并重建。

            优化点：
            - 指定 DocumentAttributeFilename 跳过 MIME 类型自动检测
            - thumb=None 避免自动生成缩略图
            - 使用 entity 缓存减少 get_input_entity 网络调用
            """
            kwargs = {
                "force_document": True,
                "thumb": None,
                "attributes": [DocumentAttributeFilename(Path(file_path).name)],
            }
            if progress_callback:
                kwargs["progress_callback"] = progress_callback
            try:
                entity = await _resolve_entity(target)
                if entity is None:
                    raise ValueError(f"Cannot resolve entity for {target}")
                return await client.send_file(entity, file_path, **kwargs)
            except (ValueError, RPCError) as e:
                logger.warning(f"[Upload] 频道无效 ({e})，尝试重建")
                # 清除失效的 entity 缓存
                if isinstance(target, (int, str)) and target != "me":
                    _invalidate_entity_cache(target)
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
