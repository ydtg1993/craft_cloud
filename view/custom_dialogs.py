from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QListWidgetItem, QGridLayout
from PySide6.QtCore import QDate, Qt
from qfluentwidgets import (MessageBoxBase, SubtitleLabel, BodyLabel,
                            PushButton, DateEdit, ListWidget, LineEdit, ComboBox)
from model.shared_types import SearchItemData


class DateSearchDialog(MessageBoxBase):
    """ 日期范围搜索对话框 """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(self.tr("Search by Date"), self)
        self.start_edit = DateEdit(self)
        self.start_edit.setDate(QDate.currentDate().addDays(-7))
        self.end_edit = DateEdit(self)
        self.end_edit.setDate(QDate.currentDate())
        self.viewLayout.addWidget(self.titleLabel)
        h_layout = QHBoxLayout()
        h_layout.addWidget(BodyLabel(self.tr("Start Date:")))
        h_layout.addWidget(self.start_edit)
        h_layout.addWidget(BodyLabel(self.tr("End Date:")))
        h_layout.addWidget(self.end_edit)
        self.viewLayout.addLayout(h_layout)
        self.yesButton.setText(self.tr("OK"))
        self.cancelButton.setText(self.tr("Cancel"))
        self.widget.setMinimumWidth(350)


class SearchResultDialog(MessageBoxBase):
    """ 搜索结果展示对话框 """

    def __init__(self, results, search_type, navigate_callback, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(
            self.tr("{search_type} Search Results - {count} files").format(search_type=search_type, count=len(results)), self
        )
        self.list_widget = ListWidget(self)
        self.list_widget.setFixedHeight(300)
        self.list_widget.setFixedWidth(500)
        for res in results:
            item = QListWidgetItem(f"{res['name']} - {res['full_path']}")
            item.setData(Qt.UserRole, SearchItemData(res['id'], res['directory_id']))
            self.list_widget.addItem(item)
        self.list_widget.itemDoubleClicked.connect(
            lambda item: (navigate_callback(item.data(Qt.UserRole).dir_id), self.accept())
        )
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.list_widget)
        self.yesButton.hide()
        self.cancelButton.setText(self.tr("Close"))
        self.widget.setMinimumWidth(550)


class AccountDialog(MessageBoxBase):
    """ 账户信息对话框 """

    def __init__(self, config, logout_callback, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(self.tr("Account"), self)

        # 从 users 表读取当前活跃用户信息
        user_info = self._load_active_user_info()

        widget = QWidget(self)
        v_layout = QVBoxLayout(widget)
        v_layout.addWidget(BodyLabel(f"{self.tr('Username')}: {user_info.get('username', 'N/A')}"))
        v_layout.addWidget(BodyLabel(f"{self.tr('Phone')}: {user_info.get('phone', 'N/A')}"))
        v_layout.addWidget(BodyLabel(f"{self.tr('Telegram ID')}: {user_info.get('tg_id', 'N/A')}"))
        v_layout.addWidget(BodyLabel(f"{self.tr('Api Id')}: {user_info.get('api_id', 'N/A')}"))
        v_layout.addWidget(BodyLabel(f"{self.tr('Api Hash')}: {user_info.get('api_hash', 'N/A')}"))
        logout_btn = PushButton(self.tr("Logout"))
        logout_btn.clicked.connect(lambda: (logout_callback(), self.accept()))
        v_layout.addWidget(logout_btn)
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(widget)
        self.yesButton.hide()
        self.widget.setMinimumWidth(350)
        self.cancelButton.setText(self.tr("Close"))

    @staticmethod
    def _load_active_user_info() -> dict:
        try:
            from core.db_manager import DBManager
            db = DBManager()
            user = db.users.get_active_user()
            if user:
                return user
        except Exception:
            pass
        return {}


class RenameDialog(MessageBoxBase):
    """ 改名对话框 (文件/文件夹) """

    def __init__(self, old_name, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(self.tr("Rename"), self)
        self.name_edit = LineEdit(self)
        self.name_edit.setText(old_name)
        self.name_edit.selectAll()
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.name_edit)
        self.yesButton.setText(self.tr("OK"))
        self.cancelButton.setText(self.tr("Cancel"))
        self.widget.setMinimumWidth(350)


class NewFolderDialog(MessageBoxBase):
    """ 新建文件夹对话框 """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(self.tr("New Folder"), self)
        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText(self.tr("New folder placeholder"))
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.name_edit)
        self.yesButton.setText(self.tr("OK"))
        self.cancelButton.setText(self.tr("Cancel"))
        self.widget.setMinimumWidth(350)


class PropertiesDialog(MessageBoxBase):
    """ 属性查看对话框 """

    def __init__(self, file_info, parent=None):
        super().__init__(parent)
        name = file_info.display_name or file_info.original_name
        self.titleLabel = SubtitleLabel(f"{self.tr('Properties')} - {name}", self)
        widget = QWidget(self)
        layout = QGridLayout(widget)
        layout.setVerticalSpacing(12)
        row = 0
        layout.addWidget(BodyLabel(self.tr("ID:")), row, 0)
        layout.addWidget(BodyLabel(str(file_info.id)), row, 1)
        row += 1
        layout.addWidget(BodyLabel(f"{self.tr('Name')}:"), row, 0)
        layout.addWidget(BodyLabel(name), row, 1)
        row += 1
        layout.addWidget(BodyLabel(f"{self.tr('Size')}:"), row, 0)
        size_bytes = getattr(file_info, 'file_size', 0) or 0
        if size_bytes > 1048576:
            size_str = f"{size_bytes / 1048576:.2f} MB"
        elif size_bytes > 1024:
            size_str = f"{size_bytes / 1024:.2f} KB"
        else:
            size_str = f"{size_bytes} Bytes"
        layout.addWidget(BodyLabel(size_str), row, 1)
        row += 1
        layout.addWidget(BodyLabel(f"{self.tr('Upload Time')}:"), row, 0)
        upload_time = getattr(file_info, 'upload_time', None)
        layout.addWidget(BodyLabel(upload_time or "-"), row, 1)
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(widget)
        self.yesButton.hide()
        self.cancelButton.setText(self.tr("Close"))
        self.widget.setMinimumWidth(400)


class MoveFileDialog(MessageBoxBase):
    """ 文件迁移对话框 """

    def __init__(self, dir_items, file_count, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(self.tr("Move to..."), self)
        self.dir_combo = ComboBox(self)
        self.dir_combo.addItems(dir_items)
        self.dir_combo.setCurrentIndex(0)
        self.dir_combo.setMaxVisibleItems(5)
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(BodyLabel(self.tr("Select target folder for {count} file(s):").format(count=file_count)))
        self.viewLayout.addWidget(self.dir_combo)
        self.yesButton.setText(self.tr("OK"))
        self.cancelButton.setText(self.tr("Cancel"))
        self.widget.setMinimumWidth(350)