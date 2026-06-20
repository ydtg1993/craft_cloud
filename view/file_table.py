from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
from view.drag_service import DragDataService
from view.highlight_delegate import draw_bottom_gradient_bar

class FolderTableHighlightDelegate(QStyledItemDelegate):
    def __init__(self, table_view, parent=None):
        super().__init__(parent)
        self.table_view = table_view

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if (self.table_view.highlighted_row == index.row() and index.isValid()):
            model = self.table_view.model()
            if hasattr(model, 'get_item'):
                item = model.get_item(index.row())
                if item and item.is_dir == 1:
                    draw_bottom_gradient_bar(painter, option.rect, QColor(90, 122, 255))

class FileTableView(QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.verticalHeader().setVisible(False)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.move_file_callback = None
        self.highlighted_row = -1          # 当前高亮的行号，-1 表示无高亮
        self._drag_start_pos = None
        self.setItemDelegate(FolderTableHighlightDelegate(self))
        # 让 viewport 自填充背景，防止打包后 QFluentWidgets 主题下
        # 框选矩形（rubber band）移动时旧位置不能正确擦除导致残影
        self.viewport().setAutoFillBackground(True)

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
        """根据鼠标位置更新高亮行"""
        # 清除旧高亮
        if self.highlighted_row >= 0:
            old_row = self.highlighted_row
            self.highlighted_row = -1
            # 刷新旧行的显示
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
        """清除高亮"""
        if self.highlighted_row >= 0:
            old_row = self.highlighted_row
            self.highlighted_row = -1
            self.viewport().update(self.visualRect(self.model().index(old_row, 0)))