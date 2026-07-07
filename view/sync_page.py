"""SyncPage — 同步文件夹仪表盘。

按配置的同步目录分组，每个目录用 GroupHeaderCardWidget 卡片展示
完整信息（addGroup 分行）：本地路径、TG频道ID、频道名、总文件数、已同步数、已同步大小。
"""
import os
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                                QScrollArea, QFrame)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from qfluentwidgets import (GroupHeaderCardWidget, HeaderCardWidget,
                            TitleLabel, BodyLabel, CaptionLabel,
                            ProgressBar, FluentIcon, PushButton)
from core.utils import format_file_size
from core.translator import tr
from model.shared_types import sync_status_display


STATUS_COLORS = {
    "completed": "#4caf50", "syncing": "#2196f3",
    "waiting": "#ff9800", "pending": "#ff9800",
    "failed": "#f44336", "cancelled": "#9e9e9e", "error": "#f44336",
    0: "#ff9800",   # pending
    1: "#4caf50",   # success
    2: "#f44336",   # failed
}

VALUE_STYLE = "QLabel { font-size: 13px; }"
HINT_STYLE = "QLabel { color: rgba(255,255,255,0.45); font-size: 11px; }"


def _status_color(s):
    if isinstance(s, int):
        return STATUS_COLORS.get(s, "#9e9e9e")
    return STATUS_COLORS.get((s or "").lower(), "#9e9e9e")


def _val(text: str, wrap=False) -> BodyLabel:
    """创建一个右对齐的值标签。"""
    lbl = BodyLabel(text)
    lbl.setStyleSheet(VALUE_STYLE)
    lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if wrap:
        lbl.setWordWrap(True)
    return lbl


# ── 单个同步文件夹卡片 ────────────────────────────────────────────

class SyncFolderCard(GroupHeaderCardWidget):
    """单个同步目录的信息卡片，addGroup 每项一行。"""

    def __init__(self, summary, parent=None):
        color = _status_color(summary.status)
        title = f"{summary.dir_name}  ·  {sync_status_display(summary.status)}"
        # 直接调基类避免 singledispatchmethod 在继承链中的二次分发问题
        HeaderCardWidget.__init__(self, parent)
        self.setTitle(title)

        self._dir_id = summary.dir_id
        self._folder_path = summary.local_path
        self._channel_id = summary.channel_id
        self._synced_files = summary.synced_files
        self._total_files = summary.total_files
        self._dir_name = summary.dir_name

        self.setStyleSheet("""
            GroupHeaderCardWidget {
                border-radius: 8px;
                border: none;
            }
        """)

        # ── 本地路径 ──────────────────────────────────────────
        path_text = summary.local_path or tr("(not configured)")
        open_folder_btn = PushButton(FluentIcon.FOLDER, tr('Open this folder'))
        open_folder_btn.clicked.connect(self._open_local_folder)
        self.addGroup(FluentIcon.FOLDER, tr("Local path"), path_text, open_folder_btn)

        # ── TG频道 ──────────────────────────────────────────
        cid = str(summary.channel_id) if summary.channel_id else "-"
        cname = summary.channel_name or "-"
        open_channel_btn = PushButton(FluentIcon.LINK, tr('Open this channel'))
        open_channel_btn.clicked.connect(self._open_tg_channel)
        self.addGroup(FluentIcon.CLOUD, tr("TG Channel") + ": " + cname, "ID: " + cid,
                      open_channel_btn)

        # ── 进度条 + 底部 ─────────────────────────────────────
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 2, 0, 0)
        bottom_layout.setSpacing(4)

        # 已同步大小
        size_text = format_file_size(summary.synced_size)
        size_lbl = _val(size_text)
        # 总文件数 已同步文件数
        total_lbl = str(summary.total_files)
        synced_lbl = str(summary.synced_files)
        bottom_layout.addWidget(CaptionLabel(tr("Synced files") + ": " + synced_lbl))
        bottom_layout.addWidget(CaptionLabel(tr("Total files") + ": " + total_lbl))

        progress = ProgressBar()
        progress.setFixedHeight(5)
        progress.setRange(0, max(summary.total_files, 1))
        progress.setValue(summary.synced_files)
        progress.setTextVisible(False)
        bottom_layout.addWidget(progress)

        hint_row = QWidget()
        hint_layout = QHBoxLayout(hint_row)
        hint_layout.setContentsMargins(0, 0, 0, 0)
        hint_layout.setSpacing(16)

        pct = (summary.synced_files / max(summary.total_files, 1)) * 100
        pct_label = CaptionLabel(f"{pct:.0f}%")
        pct_label.setStyleSheet(HINT_STYLE)
        hint_layout.addWidget(pct_label)

        if summary.last_sync_time:
            time_label = CaptionLabel(tr("Last sync: ") + summary.last_sync_time)
            time_label.setStyleSheet(HINT_STYLE)
            hint_layout.addWidget(time_label)

        hint_layout.addStretch()
        bottom_layout.addWidget(hint_row)

        self.addGroup(FluentIcon.INFO, tr("Progress"), tr("Synced size") + ":" + size_text , bottom)

        # 可变引用
        self._total_lbl = _val(total_lbl)
        self._synced_lbl = _val(synced_lbl)
        self._size_lbl = size_lbl
        self._progress_bar = progress
        self._pct_label = pct_label

        if summary.error_message:
            self._set_error_style(True)

    @property
    def folder_path(self):
        return self._folder_path

    def update_status(self, status: str, synced_files=None, total_files=None):
        self.setTitle(f"{self._dir_name}  ·  {status}")

        if total_files is not None:
            self._total_files = total_files
            self._total_lbl.setText(str(total_files))
            self._progress_bar.setRange(0, max(total_files, 1))

        if synced_files is not None:
            self._synced_files = synced_files
            self._synced_lbl.setText(str(synced_files))
            self._progress_bar.setValue(synced_files)

        pct = (self._synced_files / max(self._total_files, 1)) * 100
        self._pct_label.setText(f"{pct:.0f}%")

        is_error = (status or "").lower() in ("failed", "error")
        self._set_error_style(is_error)

    def _set_error_style(self, error: bool):
        base = self.styleSheet()
        if error:
            self.setStyleSheet(
                "GroupHeaderCardWidget { border-radius:8px; border:1px solid #f44336; }"
                + base)
        else:
            self.setStyleSheet(
                "GroupHeaderCardWidget { border-radius:8px; border:none; }"
                + base)

    def _open_local_folder(self):
        """在资源管理器中打开本地同步文件夹。"""
        if self._folder_path and os.path.exists(self._folder_path):
            os.startfile(self._folder_path)

    def _open_tg_channel(self):
        """在浏览器中打开对应的 Telegram 频道。"""
        if self._channel_id and self._channel_id != "me":
            # Telegram 频道 ID 协议格式为 -100 + 裸ID
            full_id = f"-100{self._channel_id}"
            QDesktopServices.openUrl(
                QUrl(f"https://web.telegram.org/a/#{full_id}")
            )


# ── SyncPage 主容器 ──────────────────────────────────────────

class SyncPage(QWidget):
    """同步页：卡片列表展示所有同步目录。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SyncPage")
        self._cards = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        layout.addWidget(TitleLabel(self.tr("Sync Dashboard")))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._container = QWidget()
        self._container.setObjectName("syncDashboardContainer")
        self._container.setStyleSheet("#syncDashboardContainer { background: rgba(15, 15, 15, 0.08); }")
        self._card_layout = QVBoxLayout(self._container)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.setSpacing(10)

        self._empty_label = BodyLabel(self.tr("No sync folders configured."))
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet(
            "QLabel { color: rgba(255,255,255,0.35); padding: 40px 0; }")
        self._card_layout.addWidget(self._empty_label)
        self._card_layout.addStretch()

        scroll.setWidget(self._container)
        layout.addWidget(scroll, 1)

    def refresh_all(self, summaries):
        self._cards.clear()
        # 清空布局中的所有 widget 和 spacer
        # takeAt() 已从布局移除，只需 hide + deleteLater，绝不能用 setParent(None)
        while self._card_layout.count():
            item = self._card_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()

        if not summaries:
            self._empty_label = BodyLabel(self.tr("No sync folders configured."))
            self._empty_label.setAlignment(Qt.AlignCenter)
            self._empty_label.setStyleSheet(
                "QLabel { color: rgba(255,255,255,0.35); padding: 40px 0; }")
            self._card_layout.addWidget(self._empty_label)
            self._card_layout.addStretch()
            return

        for s in summaries:
            card = SyncFolderCard(s, self._container)
            self._cards[s.local_path] = card
            self._card_layout.addWidget(card)

        self._card_layout.addStretch()

    def update_folder_status(self, folder_path, status,
                             synced_files=None, total_files=None):
        if folder_path in self._cards:
            self._cards[folder_path].update_status(status, synced_files, total_files)
