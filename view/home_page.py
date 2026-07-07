"""HomePage — 文件浏览主页面。

布局结构（三层卡片）：
  - 顶部工具栏卡片（80px）：搜索/筛选（上层）、视图切换/排序（下层），右对齐
  - 内容卡片：自定义 header（面包屑）+ FileViewStack（内部 ScrollArea），自动撑满
  - 底部状态栏卡片（25px）：当日云盘用量统计
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame
from PySide6.QtGui import QColor, QPalette
from qfluentwidgets import (FluentIcon, BreadcrumbBar, CardWidget, Theme,
                            ToolButton, LineEdit, ComboBox, qconfig)
from qfluentwidgets import theme as qfw_theme
from view.file_view_stack import FileViewStack


def _card() -> CardWidget:
    """创建统一样式的圆角卡片。"""
    card = CardWidget()
    return card


class HomePage(QWidget):
    """主页：文件浏览与操作"""

    def __init__(self, file_manager, parent=None):
        super().__init__(parent)
        self.setObjectName("HomePage")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(6)

        # ================================================================
        # 1. 顶部工具栏卡片 (单行)
        # ================================================================
        toolbar_card = _card()
        toolbar_card_layout = QHBoxLayout(toolbar_card)
        toolbar_card_layout.setContentsMargins(12, 6, 12, 6)

        # -- 靠左：视图切换 + 排序下拉 --
        self.list_btn = ToolButton(FluentIcon.MENU)
        self.list_btn.setToolTip(self.tr("List view"))
        self.list_btn.checkable = True
        self.list_btn.setChecked(True)
        toolbar_card_layout.addWidget(self.list_btn)

        self.icon_btn = ToolButton(FluentIcon.TILES)
        self.icon_btn.setToolTip(self.tr("Icon view"))
        self.icon_btn.checkable = True
        toolbar_card_layout.addWidget(self.icon_btn)

        self.sort_combo = ComboBox()
        self.sort_combo.setFixedWidth(130)
        self.sort_combo.addItems([
            self.tr("Default Sort"),
            self.tr("Name A-Z"),
            self.tr("Name Z-A"),
            self.tr("Newest first"),
            self.tr("Oldest first"),
            self.tr("Largest first"),
            self.tr("Smallest first"),
        ])
        self.sort_combo.setCurrentIndex(0)
        toolbar_card_layout.addWidget(self.sort_combo)

        # -- 靠右：搜索 + 日期筛选 --
        toolbar_card_layout.addStretch()

        self.search_input = LineEdit()
        self.search_input.setPlaceholderText(self.tr("Search files..."))
        self.search_input.setFixedWidth(200)
        toolbar_card_layout.addWidget(self.search_input)

        self.search_btn = ToolButton(FluentIcon.SEARCH)
        self.search_btn.setToolTip(self.tr("Search"))
        toolbar_card_layout.addWidget(self.search_btn)

        self.date_btn = ToolButton(FluentIcon.CALENDAR)
        self.date_btn.setToolTip(self.tr("Search by Date"))
        toolbar_card_layout.addWidget(self.date_btn)

        main_layout.addWidget(toolbar_card)
        self._toolbar_card = toolbar_card

        # ================================================================
        # 2. 内容卡片：自定义 header(面包屑) + ScrollArea(FileViewStack)
        # ================================================================
        content_card = CardWidget()
        self._content_card = content_card
        card_layout = QVBoxLayout(content_card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # header：面包屑
        header = QWidget()
        header.setFixedHeight(36)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 0, 12, 0)
        self.breadcrumb = BreadcrumbBar()
        header_layout.addWidget(self.breadcrumb, 1)
        card_layout.addWidget(header)

        # body：FileViewStack（内部各视图自带 QFluentWidgets ScrollArea）
        self.file_view = FileViewStack(file_manager, parent)
        self.file_view.stack.setStyleSheet("border: none;")
        self.file_view.table_view.setFrameShape(QFrame.Shape.NoFrame)
        self.file_view.icon_view.setFrameShape(QFrame.Shape.NoFrame)
        card_layout.addWidget(self.file_view, 1)

        main_layout.addWidget(content_card, 1)

        # ================================================================
        # 3. 底部状态栏卡片 (固定 25px)
        # ================================================================
        status_card = CardWidget()
        status_card_layout = QVBoxLayout(status_card)
        status_card_layout.setContentsMargins(12, 0, 12, 0)
        status_bar = QWidget()
        status_bar.setFixedHeight(25)
        status_bar.setObjectName("statusBar")
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(16)

        self.status_label_upload = QLabel(self.tr("Upload") + ": -- GB")
        self.status_label_upload.setObjectName("statusUpload")
        status_layout.addWidget(self.status_label_upload)

        self.status_label_download = QLabel(self.tr("Download") + ": -- GB")
        self.status_label_download.setObjectName("statusDownload")
        status_layout.addWidget(self.status_label_download)

        self.status_label_today_size = QLabel(self.tr("Today's Size")+": -- / --")
        self.status_label_today_size.setObjectName("statusTodaySize")
        status_layout.addWidget(self.status_label_today_size)

        self.status_label_today_count = QLabel(self.tr("Today's Count") + ": -- / --")
        self.status_label_today_count.setObjectName("statusTodayCount")
        status_layout.addWidget(self.status_label_today_count)
        status_layout.addStretch()
        status_card_layout.addWidget(status_bar)
        main_layout.addWidget(status_card)
        self._status_card = status_card

        # 初始化主题适配
        self._refresh_view_theme()
        self._apply_status_style()

        # 监听主题变更
        qconfig.themeChanged.connect(self._on_theme_changed)

    def _refresh_view_theme(self):
        """更新 icon view 和容器控件的主题样式。table view 由 qfluentwidgets TableView 自行管理。"""
        is_dark = qfw_theme() == Theme.DARK
        text_color = "#FFFFFF" if is_dark else "#000000"
        highlight_bg = "rgba(255, 255, 255, 0.15)" if is_dark else "rgba(0, 0, 0, 0.08)"

        qss = f"""
            QStackedWidget {{
                border: none;
                outline: none;
                background-color: transparent;
            }}
            QListWidget {{
                border: none;
                outline: none;
                background-color: transparent;
                color: {text_color};
            }}
            QListWidget::item {{
                background-color: transparent;
                color: {text_color};
            }}
            QListWidget::item:selected {{
                background-color: {highlight_bg};
                color: {text_color};
            }}
        """
        self.file_view.setStyleSheet(qss)

        # ── icon_view palette 兜底 ──
        highlight_color = QColor(255, 255, 255, 38) if is_dark else QColor(0, 0, 0, 20)
        text_qcolor = QColor(255, 255, 255) if is_dark else QColor(0, 0, 0)

        iv = self.file_view.icon_view
        p2 = iv.palette()
        p2.setColor(QPalette.Base, Qt.transparent)
        p2.setColor(QPalette.Text, text_qcolor)
        p2.setColor(QPalette.Highlight, highlight_color)
        p2.setColor(QPalette.HighlightedText, text_qcolor)
        iv.setPalette(p2)
        iv.viewport().setStyleSheet(f"background: transparent; color: {text_color};")

    def _on_theme_changed(self):
        """主题切换时更新所有卡片和内部视图的主题颜色。"""
        # 所有 CardWidget：直接设色并重绘
        for card in (self._toolbar_card, self._content_card, self._status_card):
            card.backgroundColorAni.stop()
            card.setBackgroundColor(card._normalBackgroundColor())
            card.update()

        # 文件列表视图：palette + 状态栏
        self._refresh_view_theme()
        self._apply_status_style()

    def _apply_status_style(self):
        """根据当前主题刷新状态栏标签颜色。"""
        is_dark = qfw_theme() == Theme.DARK
        color = QColor(255, 255, 255, 140) if is_dark else QColor(0, 0, 0, 140)
        status_style = (
            "QLabel {"
            "  font-size: 11px;"
            f"  color: {color.name(QColor.NameFormat.HexArgb)};"
            "  padding: 0 4px;"
            "}"
        )
        for lbl in (self.status_label_upload, self.status_label_download,
                     self.status_label_today_size, self.status_label_today_count):
            lbl.setStyleSheet(status_style)

    # ── 公开方法 ──────────────────────────────────────────────

    def update_stats(self, *, upload_gb: float = 0.0, download_gb: float = 0.0,
                     today_size_bytes: float = 0.0, size_limit_gb: float | None = None,
                     today_file_count: int = 0, count_limit: int | None = None):
        """更新底部状态栏的云盘用量 + 当日上传限制数据。

        Args:
            upload_gb / download_gb: 累计上传统计量（GB）
            today_size_bytes: 当日已上传字节数
            size_limit_gb: 当日大小上限（GB），None 表示未启用 → 显示 ∞
            today_file_count: 当日已上传文件数
            count_limit: 当日数量上限，None 表示未启用 → 显示 ∞
        """
        self.status_label_upload.setText(
            self.tr("Upload") + ": {:.2f} GB".format(upload_gb))
        self.status_label_download.setText(
            self.tr("Download") + ": {:.2f} GB".format(download_gb))

        # ── 当日上传 大小 ──
        today_gb = today_size_bytes / (1024 ** 3)
        if size_limit_gb is not None:
            self.status_label_today_size.setText(
                self.tr("Today's Size") + ": {:.2f} / {:.2f} GB".format(today_gb, size_limit_gb))
        else:
            self.status_label_today_size.setText(
                self.tr("Today's Size") + ": {:.2f} / ∞ GB".format(today_gb))

        # ── 当日上传 数量 ──
        if count_limit is not None:
            self.status_label_today_count.setText(
                self.tr("Today's Count") + ": {} / {}".format(today_file_count, count_limit))
        else:
            self.status_label_today_count.setText(
                self.tr("Today's Count") + ": {} / ∞".format(today_file_count))
