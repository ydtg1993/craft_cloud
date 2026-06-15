from PySide6.QtWidgets import QWidget, QHBoxLayout
from PySide6.QtCore import Signal
from qfluentwidgets import BreadcrumbBar, PushButton, FluentIcon

class BreadcrumbWidget(QWidget):
    directory_changed = Signal(int)
    go_up_requested = Signal()
    view_mode_changed = Signal(int)  # 0=table, 1=icon

    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 4, 16, 4)

        self.up_btn = PushButton(FluentIcon.UP, self.tr("Up"))
        self.up_btn.clicked.connect(self.go_up_requested.emit)
        layout.addWidget(self.up_btn)

        self.breadcrumb = BreadcrumbBar()
        self.breadcrumb.currentItemChanged.connect(self._on_breadcrumb_changed)
        layout.addWidget(self.breadcrumb, 1)

        self.table_btn = PushButton(FluentIcon.MENU, "")  # 纯图标按钮需带空文本
        self.table_btn.setToolTip(self.tr("List view"))
        self.table_btn.clicked.connect(lambda: self.view_mode_changed.emit(0))
        layout.addWidget(self.table_btn)

        self.icon_btn = PushButton(FluentIcon.TILES, "")
        self.icon_btn.setToolTip(self.tr("Icon view"))
        self.icon_btn.clicked.connect(lambda: self.view_mode_changed.emit(1))
        layout.addWidget(self.icon_btn)

    def set_path(self, path_parts, current_dir_id):
        """
        path_parts: list of (dir_id, dir_name)
        """
        self.breadcrumb.currentItemChanged.disconnect(self._on_breadcrumb_changed)
        self.breadcrumb.clear()
        for d_id, name in path_parts:
            self.breadcrumb.addItem(str(d_id), name)  # routeKey, text
        # 设置当前项
        if str(current_dir_id) in self.breadcrumb.itemMap:
            self.breadcrumb.setCurrentItem(str(current_dir_id))
        self.breadcrumb.currentItemChanged.connect(self._on_breadcrumb_changed)

    def _on_breadcrumb_changed(self, route_key: str):
        if route_key is not None:
            try:
                self.directory_changed.emit(int(route_key))
            except ValueError:
                pass