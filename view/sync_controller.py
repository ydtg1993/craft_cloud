from PySide6.QtCore import QObject, Signal
from services.sync import SyncScheduler

class SyncController(QObject):
    sync_completed = Signal()
    sync_error = Signal(str)
    sync_progress = Signal(str, int, int)
    sync_status = Signal(str, str)

    def __init__(self, config_manager, db, main_window):
        super().__init__()
        self.config_manager = config_manager
        self.main = main_window
        task_mgr = getattr(main_window, 'task_manager', None)
        self.scheduler = SyncScheduler(config_manager, db, task_manager=task_mgr)
        self.scheduler.sync_completed.connect(self._on_sync_completed)
        self.scheduler.sync_error.connect(self._on_sync_error)
        self.scheduler.sync_progress.connect(self.sync_progress.emit)
        self.scheduler.sync_status.connect(self.sync_status.emit)

    def update_settings(self):
        """更新配置并停止当前同步"""
        self.scheduler.restart()

    def start_sync(self):
        """根据配置启动自动同步（仅在需要时调用）"""
        if self.config_manager.config.get("auto_sync_settings", {}).get("enabled", False):
            self.scheduler.start()

    def stop_sync(self):
        """停止所有定时器并取消正在进行的同步任务"""
        self.scheduler.stop()   # 会设置取消标志并停止定时器

    def _on_sync_completed(self, folder_path, count):
        self.sync_completed.emit()

    def _on_sync_error(self, folder_path, error):
        self.sync_error.emit(error)

    def is_running(self):
        return self.scheduler.is_running