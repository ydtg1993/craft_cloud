from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
from qfluentwidgets import TableView
from qfluentwidgets.components.widgets.table_view import TableItemDelegate
from view.drag_service import DragDataService
from view.highlight_delegate import draw_bottom_gradient_bar


class FolderTableHighlightDelegate(TableItemDelegate):
    """在 TableItemDelegate 基础上为文件夹行绘制拖拽高亮渐变条。"""

    def __init__(self, table_view, parent=None):
        super().__init__(table_view)
        self.table_view = table_view

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if (self.table_view.highlighted_row == index.row() and index.isValid()):
            model = self.table_view.model()
            if hasattr(model, 'get_item'):
                item = model.get_item(index.row())
                if item and item.is_dir == 1:
                    draw_bottom_gradient_bar(painter, option.rect, QColor(90, 122, 255))


class FileTableView(TableView):
    """文件列表表格 — 继承 qfluentwidgets TableView，获得主题自适应、hover/选中态、交替行色等。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.verticalHeader().setVisible(False)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.move_file_callback = None
        self.highlighted_row = -1
        self._drag_start_pos = None
        # 替换为自定义 delegate（保留 TableItemDelegate 全部主题逻辑 + 拖拽渐变）
        self.setItemDelegate(FolderTableHighlightDelegate(self))
        # 在 CardWidget 内部，不显示自身边框
        self.setBorderVisible(False)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self._drag_start_pos is not None:
            if (event.pos() - self._drag_start_pos).manhattanLength() >= QApplication.startDragDistance():
                index = self.indexAt(self._drag_start_pos)
                if index.isValid():
                    model = self.model()
                    if hasattr(model, 'get_item'):
                        item = model.get_item(index.row())
                        if item and item.is_dir == 0:
                            self._start_multidrag()
                            self._drag_start_pos = None
                            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)

    def _start_multidrag(self):
        indexes = self.selectionModel().selectedRows()
        file_ids = []
        model = self.model()
        if not hasattr(model, 'get_item'):
            return
        for idx in indexes:
            item = model.get_item(idx.row())
            if item and item.is_dir == 0:
                file_ids.append(item.id)
        if not file_ids:
            return

        mime = DragDataService.encode_file_ids(file_ids)
        drag = QDrag(self)
        drag.setMimeData(mime)
        first_idx = indexes[0]
        icon = first_idx.data(Qt.DecorationRole)
        if icon and hasattr(icon, 'pixmap'):
            drag.setPixmap(icon.pixmap(48, 48))
        else:
            drag.setPixmap(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon).pixmap(48, 48))
        drag.exec(Qt.MoveAction)

    def startDrag(self, supportedActions):
        self._start_multidrag()

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
            target_index = self.indexAt(event.pos())
            if not target_index.isValid():
                return
            model = self.model()
            if not hasattr(model, 'get_item'):
                return
            item = model.get_item(target_index.row())
            if not item or item.is_dir != 1:
                return
            target_dir_id = item.id
            file_ids = DragDataService.decode_file_ids(event.mimeData())
            if self.move_file_callback:
                for fid in file_ids:
                    self.move_file_callback(fid, target_dir_id)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def _update_highlight(self, pos):
        if self.highlighted_row >= 0:
            old_row = self.highlighted_row
            self.highlighted_row = -1
            self.viewport().update(self.visualRect(self.model().index(old_row, 0)))

        index = self.indexAt(pos)
        if index.isValid():
            model = self.model()
            if hasattr(model, 'get_item'):
                item = model.get_item(index.row())
                if item and item.is_dir == 1:
                    self.highlighted_row = index.row()
                    self.viewport().update(self.visualRect(index))

    def _clear_highlight(self):
        if self.highlighted_row >= 0:
            old_row = self.highlighted_row
            self.highlighted_row = -1
            self.viewport().update(self.visualRect(self.model().index(old_row, 0)))
