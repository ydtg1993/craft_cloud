"""DownloadManager — 下载业务逻辑。

通过 Qt Signal 与 UI 通信，不直接使用 QFileDialog。
"""
from pathlib import Path
from PySide6.QtCore import QObject
from core.task_types import Task
from core.translator import tr


async def _get_msg(client, chat_id, message_id):
    """获取消息，兼容旧数据中的裸频道 ID 格式。

    旧数据中 files.chat_id 存储的是 msg.peer_id.channel_id（裸 ID），
    Telethon 需要完整 peer 格式（-100{裸ID}）。先用原值查，失败则补全。
    """
    result = await client.get_messages(chat_id, ids=message_id)
    msg = result[0] if isinstance(result, list) else result
    if msg and msg.media:
        return msg

    # 正数可能是旧数据的裸频道 ID → 尝试完整 peer 格式
    if isinstance(chat_id, int) and chat_id > 0:
        full_peer = int(f"-100{chat_id}")
        result = await client.get_messages(full_peer, ids=message_id)
        msg = result[0] if isinstance(result, list) else result
        if msg and msg.media:
            return msg

    return None


class DownloadManager(QObject):

    def __init__(self, config_manager, db, task_manager, parent=None):
        super().__init__(parent)
        self.config = config_manager.config
        self.db = db
        self.tm = task_manager

    def start_download(self, file_info, save_path):
        """save_path 由 view 层通过 QFileDialog 获取后传入。"""
        if not file_info or not save_path:
            return
        message_id = file_info.message_id
        chat_id = file_info.chat_id

        async def download_coro(client, signals):
            msg = await _get_msg(client, chat_id, message_id)
            if not msg:
                raise Exception(tr("No downloadable media in the message."))

            last = -1
            def progress(current, total):
                nonlocal last
                if total:
                    p = int(current * 100 / total)
                    if p != last:
                        signals.progress.emit(task_id, p)
                        last = p

            await client.download_media(msg, file=save_path, progress_callback=progress)

        task_id = f"dl_{id(file_info)}"
        filename = Path(save_path).name

        task = Task(
            task_id=task_id,
            task_type="download",
            coro=download_coro,
            description=filename,
            file_size=getattr(file_info, "file_size", 0) or 0
        )
        self.tm.submit_task(task)

    def start_folder_download(self, dir_id, root_save_dir):
        """root_save_dir 由 view 层通过 QFileDialog 获取后传入。"""
        files = self.db.files.get_all_files_recursive(dir_id)
        if not files or not root_save_dir:
            return
        for file_rec in files:
            path_parts = self.db.dirs.get_path_to_directory(file_rec.directory_id)
            local_rel_dir = self._build_relative_path(path_parts, dir_id)
            local_dir = str(Path(root_save_dir) / local_rel_dir)
            Path(local_dir).mkdir(parents=True, exist_ok=True)
            local_path = str(Path(local_dir) / (file_rec.display_name or file_rec.original_name))

            async def download_coro(client, signals, mid=file_rec.message_id,
                                    cid=file_rec.chat_id, lp=local_path):
                msg = await _get_msg(client, cid, mid)
                if not msg:
                    raise Exception(tr("No downloadable media in the message."))

                last = -1
                def progress(current, total):
                    nonlocal last
                    if total:
                        p = int(current * 100 / total)
                        if p != last:
                            signals.progress.emit(task_id, p)
                            last = p

                await client.download_media(msg, file=lp, progress_callback=progress)

            task_id = f"dl_{file_rec.id}_{file_rec.message_id}"
            filename = file_rec.display_name or file_rec.original_name
            task = Task(
                task_id=task_id,
                task_type="download",
                coro=download_coro,
                description=filename,
                file_size=getattr(file_rec, "file_size", 0) or 0
            )
            self.tm.submit_task(task)

    def _build_relative_path(self, path_parts, root_dir_id):
        if not path_parts:
            return ""
        parts = []
        found_root = False
        for d_id, name in path_parts:
            if d_id == root_dir_id:
                found_root = True
                continue
            if found_root:
                parts.append(name)
        return str(Path(parts[0]).joinpath(*parts[1:])) if parts else ""
