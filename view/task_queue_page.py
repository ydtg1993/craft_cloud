from PySide6.QtWidgets import QWidget, QVBoxLayout, QHeaderView, QTableWidgetItem
from PySide6.QtCore import Qt
from qfluentwidgets import TitleLabel, TableWidget
from loguru import logger


class TaskQueuePage(QWidget):
    """传输队列页：展示上传和下载任务。"""

    def __init__(self, parent=None, db=None):
        super().__init__(parent)
        self.setObjectName("TaskQueuePage")
        self._db = db

        layout = QVBoxLayout(self)
        layout.addWidget(TitleLabel(self.tr("Task Queue")))

        self.task_table = TableWidget()
        self.task_table.setColumnCount(5)
        self.task_table.setHorizontalHeaderLabels([
            self.tr("Filename"), self.tr("Type"), self.tr("Size"),
            self.tr("Status"), self.tr("Created Time")
        ])
        self.task_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.task_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.task_table.setColumnWidth(1, 120)
        self.task_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.task_table.setColumnWidth(2, 120)
        self.task_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.task_table.setColumnWidth(3, 180)
        self.task_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.task_table.setColumnWidth(4, 160)
        self.task_table.verticalHeader().setVisible(False)
        layout.addWidget(self.task_table)

        # 存储任务ID与行号的映射
        self.task_map = {}

        # 从数据库加载历史记录
        self._load_history()

    # ── 历史记录加载 ────────────────────────────────────────────────

    def _load_history(self):
        """从数据库加载最近的任务历史记录到表格中。"""
        if self._db is None:
            return
        try:
            records = self._db.tasks.get_recent_tasks(limit=100)
            for r in records:  # 按创建时间倒序，最新的在最上面
                self._add_history_row(
                    task_id=r["task_id"],
                    filename=r["description"],
                    task_type=r["task_type"],
                    size_str=r["file_size"],
                    status=r["status"],
                    error_msg=r["error_msg"],
                    created_time=r["created_time"],
                )
            if records:
                logger.info(f"[TaskQueuePage] 已加载 {len(records)} 条历史记录")
        except Exception as e:
            logger.warning(f"[TaskQueuePage] 加载历史记录失败: {e}")

    def _add_history_row(self, task_id, filename, task_type, size_str,
                         status, error_msg="", created_time=""):
        """添加一条历史记录行（用于初始化时从DB加载）。"""
        row = self.task_table.rowCount()
        self.task_table.insertRow(row)

        item_name = QTableWidgetItem(filename)
        item_name.setData(Qt.UserRole, task_id)
        self.task_table.setItem(row, 0, item_name)

        self.task_table.setItem(row, 1, QTableWidgetItem(task_type))
        self.task_table.setItem(row, 2, QTableWidgetItem(size_str))

        # 状态
        if status == "completed":
            display_status = self.tr("Completed")
        elif status == "failed":
            display_status = self.tr("Failed")
            if error_msg:
                display_status = f"{display_status}: {error_msg[:50]}"
        else:
            display_status = status
        self.task_table.setItem(row, 3, QTableWidgetItem(display_status))

        # 创建时间
        self.task_table.setItem(row, 4, QTableWidgetItem(created_time or "-"))

        self.task_map[task_id] = row

    # ── 实时任务更新 ────────────────────────────────────────────────

    def add_task(self, task_id, filename, task_type, size_str):
        """添加新任务到队列顶部（运行时调用，最新的在最上面）。"""
        if task_id in self.task_map:
            return
        # 插入到 row 0，最新任务在最上面
        self.task_table.insertRow(0)
        item_name = QTableWidgetItem(filename)
        item_name.setData(Qt.UserRole, task_id)
        self.task_table.setItem(0, 0, item_name)
        self.task_table.setItem(0, 1, QTableWidgetItem(task_type))
        self.task_table.setItem(0, 2, QTableWidgetItem(size_str))
        self.task_table.setItem(0, 3, QTableWidgetItem(self.tr("Pending")))
        self.task_table.setItem(0, 4, QTableWidgetItem(self.tr("Pending...")))
        # 修正所有已有行的映射（因为 insertRow(0) 把所有行往下推了一行）
        for tid, r in self.task_map.items():
            self.task_map[tid] = r + 1
        self.task_map[task_id] = 0

    def update_task_progress(self, task_id, percent):
        """更新任务进度（显示在状态列中）。"""
        if task_id not in self.task_map:
            return
        row = self.task_map[task_id]
        type_text = self.task_table.item(row, 1).text()
        if type_text.lower() == "download":
            self.task_table.item(row, 3).setText(
                f"{self.tr('Downloading')} {percent}%")
        else:
            self.task_table.item(row, 3).setText(
                f"{self.tr('Uploading')} {percent}%")

    def active_task_count(self) -> int:
        """返回当前活跃任务数（状态不是 Completed/Failed 的任务）。

        活跃任务的特征：状态列文本不为「完成」或「失败*」。
        """
        count = 0
        completed = self.tr("Completed")
        failed = self.tr("Failed")
        for task_id, row in list(self.task_map.items()):
            if row >= self.task_table.rowCount():
                continue
            item = self.task_table.item(row, 3)  # Status 列
            if not item:
                continue
            text = item.text()
            if text not in (completed, failed) and not text.startswith(failed):
                count += 1
        return count

    def update_task_status(self, task_id, status):
        """更新任务状态（完成、失败等）。"""
        if task_id not in self.task_map:
            return
        row = self.task_map[task_id]
        # 翻译状态文本
        if status == "完成":
            display = self.tr("Completed")
        elif status and status.startswith("失败"):
            display = self.tr("Failed") + status[2:]  # keep error detail
        else:
            display = status
        self.task_table.item(row, 3).setText(display)
        # 完成时更新时间戳
        from core.utils import beijing_now_str
        self.task_table.item(row, 4).setText(beijing_now_str())