"""同步调度器 —— 管理定时器，按配置的间隔触发目录同步任务。

同步任务运行在独立线程上，不与其他操作共享线程池。

托盘行为：
    用户最小化到托盘时（closeEvent），SyncScheduler.start() 被调用。
    此时不会立即触发同步——而是等待所有上传/下载任务完成后，
    再启动按配置间隔的倒计时 QTimer。

倒计时持久化：
    中途恢复窗口（stop）会保存每个文件夹的剩余时间。
    再次最小化（start）时从剩余时间续跑，而非重置为完整间隔。
    例如：5分钟间隔 → 3分钟后唤起 → 下次最小化只需等2分钟。

    剩余时间 < 2秒时直接触发同步（避免无意义的小延迟）。

非阻塞保证：
    _trigger_sync() 由 QTimer.timeout 在主线程触发，但所有阻塞操作
    （等待 worker 空闲、断开/重连共享客户端、执行同步任务）均跑在
    独立的后台线程中。主线程仅在 _trigger_sync 中设置标志位和发射信号，
    确保 UI 不会因同步准备而冻结。
"""
import threading
import time as _time_module
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from loguru import logger

from core.translator import tr
from services.sync.directory_sync_task import DirectorySyncTask

# 轮询 TgWorker 空闲状态的间隔（ms）
_IDLE_POLL_MS = 500
# 剩余时间小于此值直接触发（ms）
_MIN_REMAINING_TRIGGER_MS = 2000
# 重试延迟（秒）
_RETRY_DELAY_SEC = 30
# 等待 worker 空闲的最大轮询次数（每次 0.1s，共 30s）
_MAX_IDLE_POLLS = 300


class SyncScheduler(QObject):
    """自动同步调度器。

    管理每个同步文件夹的 QTimer，按配置的间隔创建 DirectorySyncTask
    并在独立线程中执行。所有阻塞 I/O 和网络操作均在后台线程完成。
    """

    sync_triggered = Signal(str)
    sync_completed = Signal(str, int)
    sync_error = Signal(str, str)
    sync_progress = Signal(str, int, int)
    sync_status = Signal(str, str)

    def __init__(self, config_manager, db, task_manager=None):
        super().__init__()
        self.config_manager = config_manager
        self.db = db
        self._task_manager = task_manager
        self.timers = {}
        self.is_running = False
        self._sync_running = False
        self._stop_event = threading.Event()
        self._current_task = None
        self._current_thread = None
        self._sync_lock_timeout = 600
        self._client_was_disconnected = False
        # 等待 worker 空闲的轮询定时器
        self._idle_poll_timer: QTimer | None = None
        self._folders_to_start: dict[str, dict] = {}
        # 倒计时持久化：跨 minimize/restore 保持剩余时间
        self._folder_remaining_ms: dict[str, int] = {}
        self._folder_started_at: dict[str, float] = {}
        self._folder_interval_ms: dict[str, int] = {}

    def start(self):
        """启动所有已启用的文件夹同步定时器。

        行为：
        1. 如果 TgWorker 有空闲（无上传/下载），直接启动倒计时 QTimer
        2. 如果有活跃任务，启动轮询等待任务完成后再启动倒计时
        3. 启动后不会立即触发同步 — QTimer 按配置间隔在后台计时
        """
        if self.is_running:
            return
        config = self.config_manager.config
        sync_settings = config.get("auto_sync_settings", {})
        if not sync_settings.get("enabled", False):
            return

        folders = sync_settings.get("folders", {})
        if not folders:
            return

        self.is_running = True
        self._stop_event.clear()
        self._sync_running = False

        # 检查 TgWorker 是否空闲
        if self._task_manager is not None and not self._task_manager.is_worker_idle():
            # 有活跃任务 → 缓存配置，启动轮询等待空闲
            self._folders_to_start = dict(folders)
            logger.info(
                f"[SyncScheduler] TgWorker 有活跃任务，"
                f"等待空闲后启动 {len(folders)} 个同步定时器"
            )
            self._start_idle_polling()
            return

        # Worker 空闲 → 直接启动定时器（按配置间隔倒计时）
        self._start_all_timers(folders)

    def _start_all_timers(self, folders: dict):
        """启动所有文件夹的 QTimer 倒计时。

        优先使用上次 stop() 保存的剩余时间（跨 minimize/restore 续跑）。
        """
        for folder_path, settings in folders.items():
            remaining = self._folder_remaining_ms.pop(folder_path, None)
            self._setup_timer_for_folder(folder_path, settings, initial_ms=remaining)
        # 清除未匹配的残留记录（配置已删除的文件夹）
        self._folder_remaining_ms.clear()
        logger.info(f"[SyncScheduler] 已启动 {len(self.timers)} 个同步定时器")

    # ── Worker 空闲等待 ───────────────────────────────────────────

    def _start_idle_polling(self):
        """启动轮询定时器，持续检查 TgWorker 是否空闲。"""
        if self._idle_poll_timer is not None:
            self._idle_poll_timer.stop()
        self._idle_poll_timer = QTimer()
        self._idle_poll_timer.setSingleShot(False)
        self._idle_poll_timer.timeout.connect(self._check_idle_and_start)
        self._idle_poll_timer.start(_IDLE_POLL_MS)

    def _check_idle_and_start(self):
        """轮询检查：TgWorker 空闲后启动定时器。"""
        # 如果调度器已停止（用户恢复了窗口），取消等待
        if not self.is_running:
            self._stop_idle_polling()
            return

        if self._task_manager is None or self._task_manager.is_worker_idle():
            self._stop_idle_polling()
            logger.info(
                "[SyncScheduler] TgWorker 已空闲，启动同步定时器"
                f"（{len(self._folders_to_start)} 个文件夹）"
            )
            self._start_all_timers(self._folders_to_start)
            self._folders_to_start.clear()

    def _stop_idle_polling(self):
        """停止轮询定时器。"""
        if self._idle_poll_timer is not None:
            self._idle_poll_timer.stop()
            self._idle_poll_timer = None

    def stop(self):
        """停止所有定时器，并通知正在进行的同步任务尽快停止。

        在停止前保存每个文件夹的剩余倒计时时间，
        下次 start() 时从剩余时间续跑而非重置。
        """
        # 1. 停止空闲轮询（如果正在等待 worker）
        self._stop_idle_polling()
        self._folders_to_start.clear()
        # 2. 保存每个定时器的剩余时间
        self._save_remaining_times()
        # 3. 立即停止所有同步定时器，防止发起新任务
        for timer in self.timers.values():
            timer.stop()
        self.timers.clear()
        # 4. 设置停止标志，通知正在运行的 DirectorySyncTask 尽快退出
        self._stop_event.set()
        # 5. 标记调度器不再运行
        self.is_running = False

    def _save_remaining_times(self):
        """保存每个定时器的剩余倒计时（stop 前调用）。"""
        now = _time_module.monotonic()
        for folder_path in list(self.timers.keys()):
            started = self._folder_started_at.get(folder_path)
            interval = self._folder_interval_ms.get(folder_path)
            if started is not None and interval:
                elapsed_ms = int((now - started) * 1000)
                remaining = max(0, interval - elapsed_ms)
                if remaining > 0:
                    self._folder_remaining_ms[folder_path] = remaining
                    logger.debug(
                        f"[SyncScheduler] 保存剩余时间: {folder_path!r} "
                        f"= {remaining / 1000:.0f}s / {interval / 1000:.0f}s"
                    )
                else:
                    # 倒计时已归零，清除记录
                    self._folder_remaining_ms.pop(folder_path, None)

    def restart(self):
        """重启同步引擎（如有任何文件夹启用）。"""
        if self.is_running:
            self.stop()
        self.start()

    def _setup_timer_for_folder(self, folder_path, settings, initial_ms=None):
        """为一个文件夹设置 QTimer。

        Args:
            initial_ms: 首次触发的延迟（ms）。None 表示使用配置的完整间隔。
                       用于跨 minimize/restore 续跑倒计时。
        """
        if folder_path in self.timers:
            self.timers[folder_path].stop()
        timer = QTimer()
        interval_type = settings.get("interval_type", "hourly")
        interval_value = settings.get("interval_value", 1)
        if interval_type == "minutely":
            interval_ms = interval_value * 60 * 1000
        elif interval_type == "hourly":
            interval_ms = interval_value * 60 * 60 * 1000
        elif interval_type == "daily":
            interval_ms = interval_value * 24 * 60 * 60 * 1000
        else:
            interval_ms = 60 * 60 * 1000

        # 确定首次触发时间
        if initial_ms is not None and initial_ms <= _MIN_REMAINING_TRIGGER_MS:
            # 剩余时间不足 → 直接触发（但不在 start() 中同步等待）
            logger.info(
                f"[SyncScheduler] 剩余时间仅 {initial_ms / 1000:.1f}s，"
                f"直接触发首次同步: {folder_path!r}"
            )
            use_ms = interval_ms  # timer 用完整间隔，下面立即触发
            QTimer.singleShot(100, lambda fp=folder_path: self._trigger_sync(fp))
        elif initial_ms is not None:
            use_ms = initial_ms  # 用保存的剩余时间
            logger.info(
                f"[SyncScheduler] 续跑倒计时: {folder_path!r} "
                f"= {use_ms / 1000:.0f}s（配置间隔 {interval_ms / 1000:.0f}s）"
            )
        else:
            use_ms = interval_ms  # 全新启动，用完整间隔

        self._folder_interval_ms[folder_path] = interval_ms
        self._folder_started_at[folder_path] = _time_module.monotonic()
        timer.timeout.connect(lambda fp=folder_path: self._on_timer_fired(fp))
        timer.start(use_ms)
        self.timers[folder_path] = timer

    def _on_timer_fired(self, folder_path):
        """QTimer 到期回调：重置开始时间并触发同步。"""
        # 重置开始时间 — 倒计时从此刻重新算
        self._folder_started_at[folder_path] = _time_module.monotonic()
        self._trigger_sync(folder_path)

    # ═══════════════════════════════════════════════════════════════
    # 同步触发 — 非阻塞设计
    #
    # _trigger_sync() 由 QTimer.timeout 在主线程触发，仅做两件事：
    #   1. 检查并发（_sync_running 标志）
    #   2. 启动后台线程 _prep_and_run_sync()
    #
    # _prep_and_run_sync() 在后台线程中执行所有阻塞操作：
    #   等待 worker 空闲 → 断开共享客户端 → 执行同步 → 重连
    #
    # 关键：主线程不会在任何地方被 time.sleep 或 future.result 阻塞。
    # ═══════════════════════════════════════════════════════════════

    def _trigger_sync(self, folder_path):
        """非阻塞同步入口（主线程调用）。

        仅做并发检查 + 启动后台准备线程。
        所有阻塞操作（等待、断开、同步、重连）均在后台线程完成。
        """
        if self._sync_running:
            return
        self._sync_running = True
        self._stop_event.clear()

        if not Path(folder_path).exists():
            self.sync_error.emit(folder_path, tr("Folder does not exist"))
            self._sync_running = False
            return

        # 发射 "同步中" 状态（在主线程，UI 可安全更新）
        self.sync_status.emit(folder_path, tr("Syncing"))

        # 所有阻塞操作移到后台线程执行
        prep_thread = threading.Thread(
            target=self._prep_and_run_sync,
            args=(folder_path,),
            daemon=True,
            name=f"sync-{Path(folder_path).name}",
        )
        self._current_thread = prep_thread
        prep_thread.start()

    def _prep_and_run_sync(self, folder_path):
        """后台线程：等待 worker 空闲 → 断开共享客户端 → 执行同步 → 重连。

        这个函数跑在独立线程中，可以安全地使用 time.sleep 和
        future.result() 而不会阻塞 UI。
        """
        import time as _time
        client_disconnected = False

        # ── Phase 1: 等待 worker 空闲（不打断用户的上传/下载） ──
        if self._task_manager is not None:
            waited = 0
            while not self._task_manager.is_worker_idle() and waited < _MAX_IDLE_POLLS:
                if self._stop_event.is_set():
                    self._sync_running = False
                    return
                _time.sleep(0.1)
                waited += 1

            if not self._task_manager.is_worker_idle():
                # 仍有上传/下载在进行，延后重试
                logger.info(
                    f"[SyncScheduler] TgWorker 仍有活跃任务（已等 {waited * 0.1:.0f}s），"
                    f"{_RETRY_DELAY_SEC}s 后重试"
                )
                _time.sleep(_RETRY_DELAY_SEC)
                if not self._stop_event.is_set():
                    self._prep_and_run_sync(folder_path)
                else:
                    self._sync_running = False
                return

            # ── Phase 2: 断开共享客户端，为同步让出 session 文件 ──
            client_disconnected = self._task_manager.disconnect_worker_for_sync(timeout=15.0)
            if not client_disconnected:
                logger.warning(
                    "[SyncScheduler] 无法断开共享客户端，"
                    f"{_RETRY_DELAY_SEC}s 后重试"
                )
                _time.sleep(_RETRY_DELAY_SEC)
                if not self._stop_event.is_set():
                    self._prep_and_run_sync(folder_path)
                else:
                    self._sync_running = False
                return

        # ── Phase 3: 创建并执行同步任务（在本后台线程内同步运行） ──
        self._client_was_disconnected = client_disconnected
        task = DirectorySyncTask(folder_path, self.config_manager, self.db, self._stop_event)
        task.signals.progress.connect(
            lambda d, t: self.sync_progress.emit(folder_path, d, t),
            Qt.QueuedConnection,
        )
        task.signals.completed.connect(
            lambda count: self._on_sync_done(folder_path, count),
            Qt.QueuedConnection,
        )
        task.signals.error.connect(
            lambda err: (
                logger.error(f"[SyncScheduler] 任务错误: {folder_path} -> {err}"),
                self.sync_status.emit(folder_path, f"{tr('Failed')}: {err}"),
            ),
            Qt.QueuedConnection,
        )
        task.signals.cancelled.connect(
            lambda: (
                logger.warning(f"[SyncScheduler] 任务被取消: {folder_path}"),
                self.sync_status.emit(folder_path, tr("Cancelled")),
                self.sync_completed.emit(folder_path, 0),
            ),
            Qt.QueuedConnection,
        )
        # finished 信号仅做账本清理（reconnect 在 task.run() 之后内联执行）
        task.signals.finished.connect(self._on_task_done, Qt.QueuedConnection)
        self._current_task = task

        # 在本线程同步执行同步逻辑（阻塞本线程，不影响 UI）
        task.run()

        # ── Phase 4: 恢复共享客户端（后台线程，不阻塞 UI） ──
        if client_disconnected and self._task_manager is not None:
            if not self._task_manager.reconnect_worker_after_sync(timeout=15.0):
                logger.warning(
                    "[SyncScheduler] 无法重连共享客户端，"
                    "后续 UI 操作的 TG 请求可能失败"
                )

    def _on_task_done(self):
        """同步任务结束后的账本清理（通过 finished 信号回调）。

        注意：reconnect 已在 _prep_and_run_sync 的 Phase 4 中完成，
        此方法仅重置标志位，不再执行阻塞操作。
        """
        self._current_task = None
        self._sync_running = False

    def _on_sync_done(self, folder_path, count):
        """单次同步成功完成。"""
        self.sync_status.emit(folder_path, tr("Completed"))
        self.sync_completed.emit(folder_path, count)

    def update_folder_schedule(self, folder_path, settings):
        """更新单个文件夹的定时配置。配置变更时清除旧的剩余时间。"""
        self._folder_remaining_ms.pop(folder_path, None)
        self._setup_timer_for_folder(folder_path, settings)
        self.restart()
