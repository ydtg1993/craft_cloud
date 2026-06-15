from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
from view.drag_service import DragDataService
from view.highlight_delegate import draw_bottom_gradient_bar
from model.shared_types import IconViewItemData

class IconHighlightDelegate(QStyledItemDelegate):
    def __init__(self, icon_view, parent=None):
        super().__init__(parent)
        self.icon_view = icon_view
    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        item = self.icon_view.itemFromIndex(index)
        if item and item.data(Qt.UserRole + 100):
            data = item.data(Qt.UserRole)   # IconViewItemData
            if data and data.is_dir == 1:
                draw_bottom_gradient_bar(painter, option.rect, QColor(90, 122, 255))

class FileIconView(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.move_file_callback = None
        self._highlight_item = None
        self.setItemDelegate(IconHighlightDelegate(self))

        # ---------- 图标视图显示优化 ----------
        self.setViewMode(QListView.IconMode)
        self.setIconSize(QSize(80, 80))          # 统一所有图标大小
        self.setGridSize(QSize(120, 110))        # 网格宽度120，高度110（80图标 + 25文字 + 5间距）
        self.setResizeMode(QListView.Adjust)
        self.setSpacing(12)
        self.setWordWrap(False)                  # 🔧 不换行
        self.setTextElideMode(Qt.ElideRight)     # 🔧 长文件名右侧显示省略号
        font = QFont()
        font.setPointSize(9)
        self.setFont(font)

    # ----- 以下拖放逻辑完全不变（原代码）-----
    def startDrag(self, supportedActions):
        selected_items = self.selectedItems()
        file_ids = []
        for item in selected_items:
            data = item.data(Qt.UserRole)   # IconViewItemData
            if data and data.is_dir == 0:
                file_ids.append(data.id)
        if not file_ids:
            return
        mime = DragDataService.encode_file_ids(file_ids)
        drag = QDrag(self)
        drag.setMimeData(mime)
        if selected_items:
            drag.setPixmap(selected_items[0].icon().pixmap(48, 48))
        drag.exec(Qt.MoveAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(DragDataService.MIME_TYPE):
            event.acceptProposedAction()
            self._update_highlight(event.pos())
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(DragDataService.MIME_TYPE):
            event.acceptProposedAction()
            self._update_highlight(event.pos())
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self._clear_highlight()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._clear_highlight()
        if event.mimeData().hasFormat(DragDataService.MIME_TYPE):
            item = self.itemAt(event.pos())
            if not item:
                return
            data = item.data(Qt.UserRole)   # IconViewItemData
            if not data or data.is_dir != 1:
                return
            target_dir_id = data.id
            file_ids = DragDataService.decode_file_ids(event.mimeData())
            if self.move_file_callback:
                for fid in file_ids:
                    self.move_file_callback(fid, target_dir_id)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def _update_highlight(self, pos):
        self._clear_highlight()
        item = self.itemAt(pos)
        if item:
            data = item.data(Qt.UserRole)   # IconViewItemData
            if data and data.is_dir == 1:
                self._highlight_item = item
                item.setData(Qt.UserRole + 100, True)
                self.viewport().update(self.visualItemRect(item))

    def _clear_highlight(self):
        if self._highlight_item:
            self._highlight_item.setData(Qt.UserRole + 100, False)
            self.viewport().update(self.visualItemRect(self._highlight_item))
            self._highlight_item = None