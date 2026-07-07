"""TaskManager — routes all TG tasks to a single shared Telethon worker.

Uses TgWorkerThread: one thread, one event loop, one TelegramClient.
All operation types (upload/download/rename-delete/preview) share the
same client, eliminating session file contention entirely.

Concurrency is controlled per operation type via asyncio.Semaphore
inside TgWorkerThread.
"""
from PySide6.QtCore import QObject, Signal
from core.task_types import Task
from core.tg_worker import TgWorkerThread
from loguru import logger


class TaskManager(QObject):
    """Routes tasks to a single shared TgWorkerThread.

    The worker owns the only TelegramClient instance. All tasks
    execute as asyncio coroutines on the shared client, with
    per-operation-type semaphore limits.

    Completed/failed tasks are persisted to DB via TaskRepository.
    In-progress tasks live only in memory.
    """

    task_added = Signal(str, str, str, str, int)   # → UI: task_id, description, task_type, file_size_str, raw_file_size
    task_progress = Signal(str, int)           # → UI: task_id, percent
    task_finished = Signal(str, str)           # → UI: task_id, status
    db_signal = Signal(str, dict)              # → MainWindow: DB operations
    active_task_count_changed = Signal(int)    # → UI: InfoBadge
    session_expired = Signal(str)              # → MainWindow: session 失效，触发登出

    def __init__(self, api_id, api_hash, config_manager, db=None, parent=None):
        super().__init__(parent)
        self._config = config_manager.config
        self._db = db  # DBManager（可选，用于持久化任务记录）

        # ── In-memory task info cache（submit 时存入，finish/error 时取出写入 DB）──
        self._task_info: dict[str, dict] = {}

        # ── 自己维护的 pending 计数（upload + download），不受 semaphore 影响 ──
        self._pending_count = 0

        # ── Single shared worker ────────────────────────────────────
        self._worker = TgWorkerThread(api_id, api_hash, self._config)

        # ── Bridge worker signals → TaskManager signals ─────────────
        self._worker.task_added.connect(self._on_worker_task_added)
        self._worker.task_progress.connect(self.task_progress.emit)
        self._worker.task_finished.connect(self._on_worker_task_finished)
        self._worker.task_error.connect(self._on_worker_task_error)
        self._worker.db_operation.connect(self.db_signal.emit)
        self._worker.session_expired.connect(self.session_expired.emit)

    # ── Lifecycle ──────────────────────────────────────────────────

    def start(self):
        """Start the shared worker thread."""
        self._worker.start()
        logger.info("[TaskManager] TgWorker 已启动")

    def stop(self):
        """Stop the shared worker thread."""
        self._worker.stop()
        logger.info("[TaskManager] TgWorker 已停止")

    def is_worker_idle(self) -> bool:
        """Check if the shared worker has no active TG operations."""
        return self._worker.is_idle()

    def disconnect_worker_for_sync(self, timeout: float = 10.0) -> bool:
        """Temporarily disconnect the shared client for sync (blocks)."""
        return self._worker.disconnect_for_sync(timeout=timeout)

    def reconnect_worker_after_sync(self, timeout: float = 10.0) -> bool:
        """Reconnect the shared client after sync completes (blocks)."""
        return self._worker.reconnect_after_sync(timeout=timeout)

    # ── Public API ─────────────────────────────────────────────────

    def submit_task(self, task: Task):
        """Route a task to the shared worker and cache info for later persistence."""
        task_type = task.task_type

        # 只记录上传/下载任务到内存缓存（删除/重命名等不展示在队列中）
        if task_type in ("upload", "download"):
            raw_size = task.file_size if task.file_size else 0
            self._task_info[task.task_id] = {
                "description": task.description,
                "task_type": task_type,
                "file_size": self._format_size(raw_size) if raw_size else "-",
                "raw_file_size": raw_size,
            }
            self._pending_count += 1
            self.active_task_count_changed.emit(self._pending_count)

        if task_type == "upload":
            self._worker.submit_upload(task)
        elif task_type == "download":
            self._worker.submit_download(task)
        else:
            # delete_messages, edit_captions, delete_channel, edit_channel
            self._worker.submit_rename_delete(task)

    # ── Internal: worker signal handlers with DB persistence ────────

    def _on_worker_task_added(self, task_id, description, task_type):
        """Forward task_added to UI（仅上传/下载）。"""
        if task_type in ("upload", "download"):
            info = self._task_info.get(task_id, {})
            file_size = info.get("file_size", "-")
            raw_size = info.get("raw_file_size", 0)
            self.task_added.emit(task_id, description, task_type, file_size, raw_size)

    def _on_worker_task_finished(self, task_id, status):
        """Task completed — persist to DB, decrement counter, forward to UI.

        Note: when a task errors, the worker emits BOTH task_error AND
        task_finished("失败: ..."). We skip persistence here for error
        statuses to avoid double-writes — _on_worker_task_error handles it.
        """
        if task_id not in self._task_info:
            return  # 非上传/下载任务，跳过
        self._decr_pending(task_id)
        if not status.startswith("失败"):
            self._persist_task(task_id, status)
        self.task_finished.emit(task_id, status)

    def _on_worker_task_error(self, task_id, error_msg):
        """Task failed — persist to DB with error, then log."""
        if task_id not in self._task_info:
            return  # 非上传/下载任务，仅记录日志
        logger.error(f"[TaskManager] 任务错误: {task_id}: {error_msg}")
        self._decr_pending(task_id)
        self._persist_task(task_id, "failed", error_msg)
        self.task_finished.emit(task_id, f"失败: {error_msg}")

    def _decr_pending(self, task_id: str):
        """Decrement pending count if this task was tracked (upload/download only)."""
        if task_id in self._task_info:
            self._pending_count = max(0, self._pending_count - 1)
            self.active_task_count_changed.emit(self._pending_count)

    def _persist_task(self, task_id: str, status: str, error_msg: str = ""):
        """Write a completed/failed task record to the database (upload/download only)."""
        if self._db is None:
            return
        info = self._task_info.pop(task_id, {})
        task_type = info.get("task_type", "")
        # 只持久化上传/下载任务，删除/重命名等操作不记录
        if task_type not in ("upload", "download"):
            return
        try:
            self._db.tasks.add_task(
                task_id=task_id,
                task_type=info.get("task_type", ""),
                description=info.get("description", ""),
                file_size=info.get("file_size", "-"),
                status="completed" if status == "完成" else status,
                error_msg=error_msg,
            )
        except Exception as e:
            logger.warning(f"[TaskManager] 任务记录写入 DB 失败: {e}")

    @staticmethod
    def _format_size(size_bytes) -> str:
        """Format byte size to human-readable string."""
        from core.utils import format_file_size
        if size_bytes is None:
            return "-"
        try:
            return format_file_size(int(size_bytes))
        except (ValueError, TypeError):
            return "-"

    def run_on_client(self, coro_factory, on_result, on_error):
        """Run an arbitrary coroutine on the shared Telethon client.

        For one-off operations (e.g., preview download) that need the
        TelegramClient but don't fit the Task model.

        Args:
            coro_factory: async def factory(client) -> result
            on_result: callable(result)
            on_error: callable(error_str)
        """
        self._worker.run_on_client(coro_factory, on_result, on_error)
