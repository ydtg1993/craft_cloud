from dataclasses import dataclass, field
from typing import Callable, Any, Optional
from PySide6.QtCore import QObject, Signal

class TaskSignals(QObject):
    progress = Signal(str, int)          # task_id, percent (for download/upload)
    finished = Signal(str)               # task_id
    error = Signal(str, str)             # task_id, error_message
    db_operation = Signal(str, dict)     # task_id, context (to be processed in main thread)

@dataclass
class Task:
    task_id: str
    task_type: str          # "upload", "download", "delete_message", "delete_channel", "rename"
    coro: Callable          # 异步协程，接收 client 和 task_signals 作为参数
    context: dict = field(default_factory=dict)   # 传给协程的 **kwargs
    description: str = ""   # UI 显示用
    file_size: int = 0      # 文件大小（bytes），仅用于持久化，不传给协程
    max_retries: int = 0