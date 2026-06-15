from PySide6.QtWidgets import (
    QStackedWidget, QWidget, QVBoxLayout, QListWidgetItem,
    QApplication, QStyle, QHeaderView
)
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtCore import Signal, Qt, QSize, QRect, QPoint
from qfluentwidgets import FluentIcon, RoundMenu, Action
from view.file_table import FileTableView
from view.file_icon import FileIconView
from view.file_table_model import FileTableModel
from view.icon_manager import IconManager
from view.custom_dialogs import RenameDialog, NewFolderDialog, PropertiesDialog, MoveFileDialog
from model.shared_types import IconViewItemData
from pathlib import Path


class FileViewStack(QWidget):
    item_activated = Signal(int, bool)
    file_operation_requested = Signal(str, object)

    def __init__(self, file_manager, main_window):
        super().__init__()
        self.fm = file_manager
        self.main = main_window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        self.file_model = FileTableModel()
        self.table_view = FileTableView()
        self.table_view.setModel(self.file_model)
        self.table_view.doubleClicked.connect(self._on_table_double_clicked)
        self.table_view.move_file_callback = self._on_file_moved
        self.icon_view = FileIconView()
        self.icon_view.doubleClicked.connect(self._on_icon_double_clicked)
        self.icon_view.move_file_callback = self._on_file_moved
        self.stack.addWidget(self.table_view)
        self.stack.addWidget(self.icon_view)
        layout.addWidget(self.stack)
        self._setup_table_columns()
        self.table_view.customContextMenuRequested.connect(self._show_table_context_menu)
        self.icon_view.customContextMenuRequested.connect(self._show_icon_context_menu)

    def _setup_table_columns(self):
        self.table_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        self.table_view.setColumnWidth(1, 80)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table_view.setColumnWidth(2, 130)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table_view.setColumnWidth(3, 100)
        self.table_view.setTextElideMode(Qt.ElideRight)

    def load_items(self, items):
        self.file_model.load_items(items)
        self.icon_view.clear()
        folder_icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        target_size = QSize(64, 64)

        def make_icon(icon, sz, tint=None):
            pixmap = icon.pixmap(sz, QIcon.Normal, QIcon.Off)
            if pixmap.isNull():
                pixmap = QPixmap(sz)
                pixmap.fill(Qt.transparent)
                painter = QPainter(pixmap)
                icon.paint(painter, QRect(QPoint(0, 0), sz), Qt.AlignCenter)
                painter.end()
            elif pixmap.size() != sz:
                pixmap = pixmap.scaled(
                    sz,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
            if tint is not None:
                tinted = QPixmap(pixmap.size())
                tinted.fill(Qt.transparent)
                painter = QPainter(tinted)
                painter.setRenderHint(QPainter.Antialiasing)
                painter.setRenderHint(QPainter.SmoothPixmapTransform)
                painter.drawPixmap(0, 0, pixmap)
                painter.setCompositionMode(QPainter.CompositionMode_SourceAtop)
                overlay = QColor(tint)
                overlay.setAlpha(95)
                painter.fillRect(tinted.rect(), overlay)
                painter.end()
                pixmap = tinted
            return QIcon(pixmap)

        for item in items:
            name = item.name if item.is_dir else (item.display_name or item.original_name)
            if item.is_dir:
                icon = make_icon(folder_icon, target_size)
            else:
                thumb_path = item.thumbnail_path
                if thumb_path and Path(thumb_path).exists():
                    pixmap = QPixmap(thumb_path)
                    if not pixmap.isNull():
                        icon = make_icon(QIcon(pixmap), target_size)
                    else:
                        raw_icon = IconManager.get_icon(name)
                        icon = make_icon(raw_icon, target_size)
                else:
                    raw_icon = IconManager.get_icon(name)
                    icon = make_icon(raw_icon, target_size)
            list_item = QListWidgetItem(icon, name)
            dir_info = self.fm.get_dir_info(item.id) if item.is_dir else None
            is_sync_root = 1 if (item.is_dir and dir_info and dir_info.is_sync == 1 and dir_info.parent_id == 0) else 0
            list_item.setData(Qt.UserRole, IconViewItemData(item.id, item.is_dir, is_sync_root))
            self.icon_view.addItem(list_item)

    def switch_view(self, mode):
        self.stack.setCurrentIndex(mode)

    def apply_sort(self, sort_text):
        """根据下拉菜单选择对当前文件列表排序。"""
        items = self.file_model._items[:]
        if not items:
            return

        # 默认 — 不排序
        if sort_text.startswith("Def") or sort_text.startswith("默认") or not sort_text:
            self.load_items(items)
            return

        text = sort_text
        key = None
        reverse = False

        if any(text.startswith(p) for p in ("Name", "名称")):
            key = lambda x: (x.name if x.is_dir else (x.display_name or x.original_name)).lower()
            reverse = "Z-A" in text
        elif any(text.startswith(p) for p in ("Newest", "Oldest", "最新", "最旧",
                                                "创建时间", "日期", "Date")):
            key = lambda x: x.upload_time or ""
            reverse = "Newest" in text or "最新" in text
        elif any(text.startswith(p) for p in ("Largest", "Smallest", "最大", "最小",
                                                "Size", "文件大小", "大小")):
            key = lambda x: x.file_size if not x.is_dir else 0
            reverse = "Largest" in text or "最大" in text

        if key:
            items.sort(key=key, reverse=reverse)
        self.load_items(items)

    def _on_table_double_clicked(self, index):
        item = self.file_model.get_item(index.row())
        if item:
            self.item_activated.emit(item.id, item.is_dir == 1)

    def _on_icon_double_clicked(self, idx):
        item = self.icon_view.currentItem()
        if item:
            data = item.data(Qt.UserRole)
            if data:
                self.item_activated.emit(data.id, data.is_dir == 1)

    def _on_file_moved(self, file_id, target_dir_id):
        self.file_operation_requested.emit("move", (file_id, target_dir_id))

    # ---------- 弹窗逻辑抽取 ----------
    def _do_rename_directory(self, dir_id, old_name):
        dir_info = self.fm.get_dir_info(dir_id)
        if dir_info and dir_info.channel_id == "me" and dir_info.parent_id == 0:
            return  # Saved Messages is a system directory
        dlg = RenameDialog(old_name, self.window())
        if dlg.exec():
            new_name = dlg.name_edit.text().strip()
            if new_name and new_name != old_name:
                self.main.file_manager.rename_directory(dir_id, new_name)

    def _do_rename_file(self, file_id, old_name):
        dlg = RenameDialog(old_name, self.window())
        if dlg.exec():
            new_name = dlg.name_edit.text().strip()
            if new_name and new_name != old_name:
                self.main.file_manager.rename_file(file_id, new_name)

    def _do_create_directory(self):
        dlg = NewFolderDialog(self.window())
        if dlg.exec():
            folder_name = dlg.name_edit.text().strip()
            if folder_name:
                self.main._do_create_directory(folder_name)

    def _do_show_properties(self, file_info):
        dlg = PropertiesDialog(file_info, self.window())
        dlg.exec()

    def _move_files_dialog(self, file_ids):
        # 只列出同频道下的目录（跨频道不可迁移）
        current_dir = self.main.current_dir_id
        dirs = self.fm.get_channel_dirs_list(current_dir)
        if not dirs:
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.warning(
                self.tr("Warning"),
                self.tr("No target directories available in the current channel."),
                position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        items = [f"{name} (ID: {d_id})" for d_id, name, _ in dirs]
        dlg = MoveFileDialog(items, len(file_ids), self.window())
        if dlg.exec():
            target = dlg.dir_combo.currentText()
            target_dir_id = int(target.split("(ID: ")[-1].rstrip(")"))
            for fid in file_ids:
                self.fm.move_file(fid, target_dir_id)
            self.main._refresh_current_directory()

    # ---------- 右键菜单 (替换为 RoundMenu) ----------
    def _show_table_context_menu(self, pos):
        menu = RoundMenu(parent=self)
        idx = self.table_view.indexAt(pos)
        if not idx.isValid():
            # Root 抽象层只允许新建文件夹，不允许上传
            if self.main.current_dir_id != 0:
                a1 = Action(FluentIcon.UP, self.tr("Upload Files"))
                a1.triggered.connect(self.main._do_upload_files)
                menu.addAction(a1)
                a2 = Action(FluentIcon.FOLDER, self.tr("Upload Folder"))
                a2.triggered.connect(self.main._do_upload_folder)
                menu.addAction(a2)
            a3 = Action(FluentIcon.FOLDER_ADD, self.tr("New Folder"))
            a3.triggered.connect(self._do_create_directory)
            menu.addAction(a3)
            menu.exec(self.table_view.viewport().mapToGlobal(pos))
            return
        item = self.file_model.get_item(idx.row())
        if not item:
            return
        if item.is_dir == 1:
            dir_info = self.fm.get_dir_info(item.id)
            is_sync_dir = dir_info and dir_info.is_sync == 1
            is_saved_messages = bool(dir_info and dir_info.channel_id == "me" and dir_info.parent_id == 0)
            _dir_id = item.id
            _dir_name = item.name
            a1 = Action(FluentIcon.DOWN, self.tr("Download folder"))
            a1.triggered.connect(lambda _checked=False, d=_dir_id: self.main._handle_folder_download(d))
            menu.addAction(a1)
            if not is_saved_messages:
                a2 = Action(FluentIcon.EDIT, self.tr("Rename"))
                a2.triggered.connect(lambda _checked=False, d=_dir_id, n=_dir_name: self._do_rename_directory(d, n))
                menu.addAction(a2)
            if is_saved_messages:
                pass  # No delete for Saved Messages
            elif is_sync_dir:
                a3 = Action(FluentIcon.DELETE, self.tr("Delete (TG only)"))
                a3.triggered.connect(lambda _checked=False, d=_dir_id, n=_dir_name: self.main._on_delete_sync_root(d, n))
                menu.addAction(a3)
            else:
                a3 = Action(FluentIcon.DELETE, self.tr("Delete"))
                a3.triggered.connect(lambda _checked=False, d=_dir_id, n=_dir_name: self.main._handle_dir_delete(d, n))
                menu.addAction(a3)
            menu.exec(self.table_view.viewport().mapToGlobal(pos))
            return
        file_info = self.fm.get_file_info(item.id)
        if file_info:
            dir_id = file_info.directory_id
            dir_info = self.fm.get_dir_info(dir_id)
            is_in_sync_dir = dir_info and dir_info.is_sync == 1
            selected_ids = self._selected_file_ids_table()
            file_ids = selected_ids if item.id in selected_ids else [item.id]
            if file_ids:
                if is_in_sync_dir:
                    if len(file_ids) == 1:
                        info = self.fm.get_file_info(file_ids[0])
                        if info:
                            _info = info
                            a1 = Action(FluentIcon.DOWN, self.tr("Download"))
                            a1.triggered.connect(lambda _checked=False, inf=_info: self.main._handle_file_download(inf))
                            menu.addAction(a1)
                            a2 = Action(FluentIcon.INFO, self.tr("Properties"))
                            a2.triggered.connect(lambda _checked=False, inf=_info: self._do_show_properties(inf))
                            menu.addAction(a2)
                    else:
                        a1 = Action(FluentIcon.DOWN, self.tr("Batch Download"))
                        a1.triggered.connect(lambda _checked=False, fids=file_ids: self._batch_download(fids))
                        menu.addAction(a1)
                else:
                    if len(file_ids) == 1:
                        info = self.fm.get_file_info(file_ids[0])
                        if info:
                            _info = info
                            _fids = file_ids
                            a1 = Action(FluentIcon.DOWN, self.tr("Download"))
                            a1.triggered.connect(lambda _checked=False, inf=_info: self.main._handle_file_download(inf))
                            menu.addAction(a1)
                            a2 = Action(FluentIcon.EDIT, self.tr("Rename"))
                            a2.triggered.connect(lambda _checked=False, f=_info.id, nm=_info.original_name or _info.display_name: self._do_rename_file(f, nm))
                            menu.addAction(a2)
                            a3 = Action(FluentIcon.SEND, self.tr("Move to..."))
                            a3.triggered.connect(lambda _checked=False, fids=_fids: self._move_files_dialog(fids))
                            menu.addAction(a3)
                            a4 = Action(FluentIcon.DELETE, self.tr("Delete"))
                            a4.triggered.connect(lambda _checked=False, fids=_fids: self.main._handle_file_delete(fids))
                            menu.addAction(a4)
                            a5 = Action(FluentIcon.INFO, self.tr("Properties"))
                            a5.triggered.connect(lambda _checked=False, inf=_info: self._do_show_properties(inf))
                            menu.addAction(a5)
                    else:
                        _fids = file_ids
                        a1 = Action(FluentIcon.DOWN, self.tr("Batch Download"))
                        a1.triggered.connect(lambda _checked=False, fids=_fids: self._batch_download(fids))
                        menu.addAction(a1)
                        a2 = Action(FluentIcon.SEND, self.tr("Batch Move to..."))
                        a2.triggered.connect(lambda _checked=False, fids=_fids: self._move_files_dialog(fids))
                        menu.addAction(a2)
                        a3 = Action(FluentIcon.DELETE, self.tr("Batch Delete"))
                        a3.triggered.connect(lambda _checked=False, fids=_fids: self.main._handle_file_delete(fids))
                        menu.addAction(a3)
                menu.exec(self.table_view.viewport().mapToGlobal(pos))

    def _show_icon_context_menu(self, pos):
        menu = RoundMenu(parent=self)
        item = self.icon_view.itemAt(pos)
        if item is None:
            # Root 抽象层只允许新建文件夹，不允许上传
            if self.main.current_dir_id != 0:
                a1 = Action(FluentIcon.UP, self.tr("Upload Files"))
                a1.triggered.connect(self.main._do_upload_files)
                menu.addAction(a1)
                a2 = Action(FluentIcon.FOLDER, self.tr("Upload Folder"))
                a2.triggered.connect(self.main._do_upload_folder)
                menu.addAction(a2)
            a3 = Action(FluentIcon.FOLDER_ADD, self.tr("New Folder"))
            a3.triggered.connect(self._do_create_directory)
            menu.addAction(a3)
            menu.exec(self.icon_view.viewport().mapToGlobal(pos))
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        item_id = data.id
        is_dir = data.is_dir
        is_sync = data.is_sync_root
        if is_dir == 1:
            dir_info = self.fm.get_dir_info(item_id)
            is_sync_dir = is_sync == 1
            is_saved_messages = bool(dir_info and dir_info.channel_id == "me" and dir_info.parent_id == 0)
            _dir_id = item_id
            _dir_name = item.text()
            a1 = Action(FluentIcon.DOWN, self.tr("Download folder"))
            a1.triggered.connect(lambda _checked=False, d=_dir_id: self.main._handle_folder_download(d))
            menu.addAction(a1)
            if not is_saved_messages:
                a2 = Action(FluentIcon.EDIT, self.tr("Rename"))
                a2.triggered.connect(lambda _checked=False, d=_dir_id, n=_dir_name: self._do_rename_directory(d, n))
                menu.addAction(a2)
            if is_saved_messages:
                pass  # No delete for Saved Messages
            else:
                a3 = Action(FluentIcon.DELETE, self.tr("Delete"))
                a3.triggered.connect(lambda _checked=False, d=_dir_id, n=_dir_name: self.main._handle_dir_delete(d, n))
                menu.addAction(a3)
            menu.exec(self.icon_view.viewport().mapToGlobal(pos))
            return
        selected_ids = self._selected_file_ids_icon()
        file_ids = selected_ids if item_id in selected_ids else [item_id]
        if file_ids:
            if len(file_ids) == 1:
                info = self.fm.get_file_info(file_ids[0])
                if info:
                    _info = info
                    _fids = file_ids
                    a1 = Action(FluentIcon.DOWN, self.tr("Download"))
                    a1.triggered.connect(lambda _checked=False, inf=_info: self.main._handle_file_download(inf))
                    menu.addAction(a1)
                    a2 = Action(FluentIcon.EDIT, self.tr("Rename"))
                    a2.triggered.connect(lambda _checked=False, f=_info.id, nm=_info.original_name or _info.display_name: self._do_rename_file(f, nm))
                    menu.addAction(a2)
                    a3 = Action(FluentIcon.SEND, self.tr("Move to..."))
                    a3.triggered.connect(lambda _checked=False, fids=_fids: self._move_files_dialog(fids))
                    menu.addAction(a3)
                    a4 = Action(FluentIcon.DELETE, self.tr("Delete"))
                    a4.triggered.connect(lambda _checked=False, fids=_fids: self.main._handle_file_delete(fids))
                    menu.addAction(a4)
                    a5 = Action(FluentIcon.INFO, self.tr("Properties"))
                    a5.triggered.connect(lambda _checked=False, inf=_info: self._do_show_properties(inf))
                    menu.addAction(a5)
            else:
                _fids = file_ids
                a1 = Action(FluentIcon.DOWN, self.tr("Batch Download"))
                a1.triggered.connect(lambda _checked=False, fids=_fids: self._batch_download(fids))
                menu.addAction(a1)
                a2 = Action(FluentIcon.SEND, self.tr("Batch Move to..."))
                a2.triggered.connect(lambda _checked=False, fids=_fids: self._move_files_dialog(fids))
                menu.addAction(a2)
                a3 = Action(FluentIcon.DELETE, self.tr("Batch Delete"))
                a3.triggered.connect(lambda _checked=False, fids=_fids: self.main._handle_file_delete(fids))
                menu.addAction(a3)
            menu.exec(self.icon_view.viewport().mapToGlobal(pos))

    def _selected_file_ids_table(self):
        ids = []
        for idx in self.table_view.selectionModel().selectedRows():
            item = self.file_model.get_item(idx.row())
            if item and item.is_dir == 0:
                ids.append(item.id)
        return ids

    def _selected_file_ids_icon(self):
        ids = []
        for it in self.icon_view.selectedItems():
            d = it.data(Qt.UserRole)
            if d and d.is_dir == 0:
                ids.append(d.id)
        return ids

    def _batch_download(self, file_ids):
        for fid in file_ids:
            info = self.fm.get_file_info(fid)
            if info:
                self.main._handle_file_download(info)