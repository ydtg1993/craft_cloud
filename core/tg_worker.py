"""TgWorkerThread — single shared Telethon client for all TG operations.

Replaces the multi-thread, multi-client architecture with ONE thread,
ONE event loop, and ONE TelegramClient. All operations (upload, download,
rename/delete, preview) share this client and are scheduled as asyncio
tasks with operation-type-specific Semaphores.

This completely eliminates session file (my_account.session) contention
because only one SQLite connection is ever opened to the session file.
"""
import asyncio
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from telethon import TelegramClient
from telethon.errors import UnauthorizedError
from loguru import logger

from core.task_types import Task, TaskSignals
from core.utils import get_sessions_dir


class TgWorkerThread(QObject):
    """Single shared Telethon worker thread.

    Owns one TelegramClient in one asyncio event loop. All TG operations
    are submitted from any thread via `asyncio.run_coroutine_threadsafe()`.

    Concurrency is controlled per operation type via asyncio.Semaphore:
    - upload:        max_concurrent_uploads (default 1)
    - download:      max_concurrent_downloads (default 1)
    - rename_delete: 1 (serialized)
    - preview:       unlimited (quick, one-at-a-time in practice)
    """

    # ── Signals (cross-thread safe via queued connections) ─────────
    task_added = Signal(str, str, str)        # task_id, description, task_type
    task_progress = Signal(str, int)           # task_id, percent
    task_finished = Signal(str, str)           # task_id, status
    task_error = Signal(str, str)              # task_id, error_message
    db_operation = Signal(str, dict)           # task_id, context (→ main thread)
    active_count_changed = Signal(int)         # total active tasks
    session_expired = Signal(str)              # reason (→ main thread: trigger logout)

    def __init__(self, api_id, api_hash, config, parent=None):
        super().__init__(parent)
        self._api_id = api_id
        self._api_hash = api_hash
        self._config = config

        # Created in event loop thread
        self._client: TelegramClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._running = False

        # Semaphores — created in event loop thread
        self._upload_sem = None
        self._download_sem = None
        self._rd_sem = None  # rename/delete

        # Active task counters
        self._active = {"upload": 0, "download": 0, "rename_delete": 0, "preview": 0}
        self._count_lock = threading.Lock()

    # ── Lifecycle ──────────────────────────────────────────────────

    def start(self):
        """Start the worker thread and connect the Telethon client."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="tg-worker"
        )
        self._thread.start()
        logger.info("[TgWorker] 线程已启动")

    def stop(self, timeout=5.0):
        """Stop the event loop, disconnect client, and join thread."""
        if not self._running:
            return
        self._running = False
        if self._loop is not None:
            try:
                asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
            except RuntimeError:
                pass  # loop already closed
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning("[TgWorker] 线程未能在超时内退出")
        logger.info("[TgWorker] 线程已停止")

    # ── Thread main ────────────────────────────────────────────────

    def _run_loop(self):
        """Entry point for the worker thread."""
        if sys.platform == "win32":
            try:
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            except RuntimeError:
                pass

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        # Create semaphores (must happen inside the event loop thread)
        max_up = self._config.get("max_concurrent_uploads", 1)
        max_dl = self._config.get("max_concurrent_downloads", 1)
        self._upload_sem = asyncio.Semaphore(max_up)
        self._download_sem = asyncio.Semaphore(max_dl)
        self._rd_sem = asyncio.Semaphore(1)

        try:
            self._loop.run_until_complete(self._connect_client())
            logger.info("[TgWorker] TelegramClient 已连接，开始处理任务")
            self._loop.run_forever()
        except UnauthorizedError:
            logger.warning("[TgWorker] Session 已失效（connect 阶段检测到）")
            self.session_expired.emit("会话已在其他设备上被清除，请重新登录")
        except Exception as e:
            logger.exception(f"[TgWorker] Event loop 异常: {e}")
            # 非认证错误：如果仍在运行状态，可能是临时网络问题，报错给 UI
            if self._running:
                self.session_expired.emit(f"连接异常: {e}")
        finally:
            self._running = False
            self._client = None
            self._loop.run_until_complete(self._cleanup())
            self._loop.close()
            # Clean up thread-local DB session
            try:
                from core.database import get_session_factory
                get_session_factory().remove()
            except Exception:
                pass

    async def _connect_client(self):
        """Create and connect the single shared Telethon client.

        连接后立即调用 get_me() 验证 session 有效性，避免过期 session
        在用户操作时才暴露（表现为"一用就登出"）。

        验证通过后启动两个后台 watchdog：
        1. _watch_disconnect — 监控 client.disconnected Future
        2. _watchdog_health — 定期调用 get_me() 检测 session 是否仍然有效
        """
        from core.tg_client import ensure_session_wal
        ensure_session_wal()

        session_path = str(get_sessions_dir() / "my_account.session")
        self._client = TelegramClient(
            session_path, self._api_id, self._api_hash
        )
        await self._client.connect()

        # 立即验证 session 有效性（connect() 只打开文件，不做 API 调用）
        me = await self._client.get_me()
        logger.info(
            f"[TgWorker] Client connected and verified, "
            f"user=@{getattr(me, 'username', '?')}, session={session_path}"
        )

        # 启动两个后台 watchdog task
        self._disconnect_watcher = self._loop.create_task(
            self._watch_disconnect(), name="tg-watch-disconnect"
        )
        self._health_watcher = self._loop.create_task(
            self._watchdog_health(), name="tg-watch-health"
        )

    async def _watch_disconnect(self):
        """监控 client.disconnected — 当 Telethon 内部检测到 session
        失效后会调用 disconnect()，此 Future 随之 resolve。

        是检测 session 失效的主要路径。
        """
        try:
            await self._client.disconnected
        except Exception:
            return  # 正常关闭时可能出现异常，忽略

        if not self._running:
            return  # 主动调用 stop() 导致的断开，无需处理

        # 检查 Telethon 内部记录的错误类型
        error = getattr(self._client, '_updates_error', None)
        if error is not None and isinstance(error, UnauthorizedError):
            logger.warning(
                f"[TgWorker] Session 失效（_watch_disconnect 检测到 "
                f"{type(error).__name__}），触发登出"
            )
            self._running = False
            self.session_expired.emit("会话已在其他设备上被清除，请重新登录")
            self._loop.stop()
        else:
            err_name = type(error).__name__ if error else "unknown"
            logger.info(f"[TgWorker] 客户端断开（非认证错误: {err_name}），尝试重连")
            # 非认证错误（如网络闪断）：尝试重连
            if self._running:
                await asyncio.sleep(2)
                try:
                    await self._reconnect_client()
                    # watchdog 任务已在 _reconnect_client() 中重新创建，无需重复注册
                except Exception as e:
                    logger.error(f"[TgWorker] 重连失败: {e}")
                    if self._running:
                        self._running = False
                        self.session_expired.emit(f"重连失败: {e}")
                        self._loop.stop()

    async def _watchdog_health(self):
        """定期心跳检测：每 60 秒调用 get_me() 验证 session 仍然有效。

        是检测 session 失效的补充路径 — 当 _update_loop 在后台
        捕获了 UnauthorizedError 但尚未调用 disconnect() 时，或
        telethon 内部静默处理了错误时，心跳会在最多 60s 内发现。
        """
        while self._running and self._client is not None:
            try:
                await asyncio.sleep(60)
                if not self._running or self._client is None:
                    break
                # 简单的 API 调用，验证 session 是否有效
                await self._client.get_me()
            except UnauthorizedError:
                logger.warning("[TgWorker] Session 失效（_watchdog_health 检测到），触发登出")
                self._running = False
                self.session_expired.emit("会话已在其他设备上被清除，请重新登录")
                self._loop.stop()
                break
            except asyncio.CancelledError:
                break
            except Exception:
                # 临时错误（网络超时等），下次心跳重试
                continue

    async def _shutdown(self):
        """Graceful shutdown: disconnect client, then stop loop."""
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception as e:
                logger.debug(f"[TgWorker] disconnect 失败: {e}")
        # Cancel all remaining asyncio tasks
        current = asyncio.current_task()
        for t in asyncio.all_tasks(self._loop):
            if t is not current:
                t.cancel()
        # Wait briefly for cancellation to propagate
        await asyncio.sleep(0.1)
        self._loop.stop()

    async def _cleanup(self):
        """Drain remaining tasks before closing the event loop."""
        current = asyncio.current_task()
        # Phase 1: passive wait
        for _ in range(50):
            pending = [t for t in asyncio.all_tasks(self._loop)
                       if t is not current and not t.done()]
            if not pending:
                return
            await asyncio.sleep(0.02)
        # Phase 2: cancel stubborn tasks
        pending = [t for t in asyncio.all_tasks(self._loop)
                   if t is not current and not t.done()]
        if pending:
            logger.debug(f"[TgWorker] 取消 {len(pending)} 个残留任务")
            for t in pending:
                t.cancel()
            try:
                await asyncio.wait(pending, timeout=1.0)
            except Exception:
                pass

    # ── Public API: task submission (thread-safe) ──────────────────

    def submit_upload(self, task: Task):
        """Submit an upload task (from any thread)."""
        if not self._running:
            logger.warning("[TgWorker] 未运行，upload 任务被丢弃")
            return
        self.task_added.emit(task.task_id, task.description, task.task_type)
        asyncio.run_coroutine_threadsafe(
            self._run_task(task, "upload", self._upload_sem), self._loop
        )

    def submit_download(self, task: Task):
        """Submit a download task (from any thread)."""
        if not self._running:
            logger.warning("[TgWorker] 未运行，download 任务被丢弃")
            return
        self.task_added.emit(task.task_id, task.description, task.task_type)
        asyncio.run_coroutine_threadsafe(
            self._run_task(task, "download", self._download_sem), self._loop
        )

    def submit_rename_delete(self, task: Task):
        """Submit a rename/delete task (from any thread)."""
        if not self._running:
            logger.warning("[TgWorker] 未运行，rename_delete 任务被丢弃")
            return
        self.task_added.emit(task.task_id, task.description, task.task_type)
        asyncio.run_coroutine_threadsafe(
            self._run_task(task, "rename_delete", self._rd_sem), self._loop
        )

    def run_on_client(self, coro_factory, on_result, on_error):
        """Run an arbitrary coroutine on the shared client (from any thread).

        Args:
            coro_factory: async def factory(client) -> result
            on_result: callable(result) — called in event loop thread
            on_error: callable(error_str) — called in event loop thread

        Used by preview downloads and other one-off operations that
        need the TelegramClient but don't fit the Task model.
        """
        if not self._running:
            on_error("Worker not running")
            return

        async def _wrapper():
            self._inc_active("preview")
            try:
                result = await coro_factory(self._client)
                on_result(result)
            except GeneratorExit:
                raise
            except UnauthorizedError:
                logger.warning("[TgWorker] Session 失效（run_on_client），触发登出")
                self.session_expired.emit("会话已失效，请重新登录")
                on_error("会话已失效，请重新登录")
            except Exception as e:
                on_error(str(e))
            finally:
                self._dec_active("preview")

        asyncio.run_coroutine_threadsafe(_wrapper(), self._loop)

    # ── Session coordination with sync tasks ────────────────────────

    def is_idle(self) -> bool:
        """Check if no TG operations are currently active."""
        with self._count_lock:
            return sum(self._active.values()) == 0

    def disconnect_for_sync(self, timeout: float = 10.0) -> bool:
        """Temporarily disconnect the shared client so a sync task can use
        the session file exclusively. Blocks until disconnect completes.

        Returns True on success, False on timeout/failure.
        """
        if not self._running or self._loop is None:
            return True  # nothing to disconnect
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._disconnect_client(), self._loop
            )
            future.result(timeout=timeout)
            logger.debug("[TgWorker] 共享客户端已断开（为同步任务让路）")
            return True
        except Exception as e:
            logger.warning(f"[TgWorker] 断开客户端失败: {e}")
            return False

    def reconnect_after_sync(self, timeout: float = 10.0) -> bool:
        """Reconnect the shared client after a sync task has finished.

        Returns True on success, False on timeout/failure.
        """
        if not self._running or self._loop is None:
            return False
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._reconnect_client(), self._loop
            )
            future.result(timeout=timeout)
            logger.debug("[TgWorker] 共享客户端已重新连接（同步任务完成）")
            return True
        except Exception as e:
            logger.warning(f"[TgWorker] 重连客户端失败: {e}")
            return False

    async def _disconnect_client(self):
        """Async: disconnect the shared Telethon client and close its session.

        Explicitly closes the SQLite session so the file is fully released
        before a sync task opens its own client on the same session file.

        Also cancels _watch_disconnect and _watchdog_health background tasks
        to prevent them from auto-reconnecting while the sync task owns the
        session file (which would cause "database is locked" and a spurious
        session_expired signal).
        """
        # 1. 取消后台 watchdog 任务，防止它们在断开后自动重连
        for attr in ('_disconnect_watcher', '_health_watcher'):
            task = getattr(self, attr, None)
            if task is not None and not task.done():
                task.cancel()
            setattr(self, attr, None)

        # 2. 断开客户端并释放 session 文件
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception as e:
                logger.debug(f"[TgWorker] disconnect 细节: {e}")
            try:
                if hasattr(self._client, 'session') and self._client.session:
                    self._client.session.close()
            except Exception as e:
                logger.debug(f"[TgWorker] session.close 细节: {e}")
            self._client = None

    async def _reconnect_client(self):
        """Async: recreate and reconnect the shared Telethon client.

        重连后调用 get_me() 验证 session 仍然有效。
        同时重新启动 _watch_disconnect 和 _watchdog_health 后台任务。
        """
        from core.tg_client import ensure_session_wal
        from core.utils import get_sessions_dir
        ensure_session_wal()
        session_path = str(get_sessions_dir() / "my_account.session")
        self._client = TelegramClient(
            session_path, self._api_id, self._api_hash
        )
        await self._client.connect()
        # 验证重连后的 session 有效性
        await self._client.get_me()
        logger.debug("[TgWorker] Client reconnected and verified")

        # 重新启动后台 watchdog 任务
        self._disconnect_watcher = self._loop.create_task(
            self._watch_disconnect(), name="tg-watch-disconnect"
        )
        self._health_watcher = self._loop.create_task(
            self._watchdog_health(), name="tg-watch-health"
        )

    # ── Internal: task runner ──────────────────────────────────────

    async def _run_task(self, task: Task, op_key: str, sem: asyncio.Semaphore):
        """Execute a Task on the shared client, with semaphore + retry."""
        async with sem:
            self._inc_active(op_key)
            signals = self._make_signals(task.task_id)
            ctx = task.context if isinstance(task.context, dict) else {}
            retries = 0
            max_retries = task.max_retries or 3

            while self._running:
                try:
                    await task.coro(self._client, signals, **ctx)
                    signals.finished.emit(task.task_id)
                    break
                except GeneratorExit:
                    raise
                except UnauthorizedError:
                    # Session 已被清除/撤销，不可恢复，触发全局登出
                    logger.warning(f"[TgWorker] Session 失效，触发登出（任务: {task.task_id}）")
                    self.session_expired.emit("会话已失效，请重新登录")
                    signals.error.emit(task.task_id, "会话已失效，请重新登录")
                    break
                except Exception as e:
                    retries += 1
                    error_str = str(e).lower()
                    # Retry on transient errors (session lock, network)
                    if retries <= max_retries and (
                        "database is locked" in error_str
                        or "timeout" in error_str
                        or "connection" in error_str
                    ):
                        import random
                        delay = random.uniform(1.0, 4.0)
                        logger.warning(
                            f"[TgWorker] {op_key} 任务 {task.task_id} 失败，"
                            f"{delay:.1f}s 后重试 ({retries}/{max_retries}): {e}"
                        )
                        await asyncio.sleep(delay)
                        continue
                    # Final failure
                    err_msg = f"{e} (重试{max_retries}次后失败)"
                    signals.error.emit(task.task_id, err_msg)
                    break

            self._dec_active(op_key)

    # ── Signal helpers ─────────────────────────────────────────────

    def _make_signals(self, task_id: str) -> TaskSignals:
        """Create a TaskSignals object bridged to this worker's Qt signals."""
        sigs = TaskSignals()

        def _progress(tid, pct):
            if tid == task_id:
                self.task_progress.emit(tid, pct)

        def _finished(tid):
            if tid == task_id:
                self.task_finished.emit(tid, "完成")

        def _error(tid, err):
            if tid == task_id:
                self.task_error.emit(tid, err)
                self.task_finished.emit(tid, f"失败: {err}")

        def _db_op(tid, ctx):
            if tid == task_id:
                self.db_operation.emit(tid, ctx)

        sigs.progress.connect(_progress)
        sigs.finished.connect(_finished)
        sigs.error.connect(_error)
        sigs.db_operation.connect(_db_op)

        return sigs

    def _inc_active(self, key: str):
        with self._count_lock:
            self._active[key] += 1
            total = sum(self._active.values())
            self.active_count_changed.emit(total)

    def _dec_active(self, key: str):
        with self._count_lock:
            self._active[key] = max(0, self._active[key] - 1)
            total = sum(self._active.values())
            self.active_count_changed.emit(total)
