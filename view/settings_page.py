import sys
from pathlib import Path
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QWidget, QFileDialog,
                               QListWidgetItem, QApplication, QStackedWidget, QLabel)
from PySide6.QtCore import Qt, QProcess, Signal, QSize, QRect
from PySide6.QtGui import QColor
from qfluentwidgets import (TitleLabel, BodyLabel, CaptionLabel, PushButton, LineEdit,
                            SwitchButton, SpinBox, DoubleSpinBox, Slider, ListWidget, InfoBar,
                            MessageBoxBase, SubtitleLabel, ComboBox, MessageBox,
                            SegmentedWidget, GroupHeaderCardWidget, FluentIcon,
                            ExpandSettingCard, ToolButton)
from qfluentwidgets.components.dialog_box.dialog import Dialog
from core.config_manager import ConfigManager
from core.telegram_uploader import TelethonUploader
from loguru import logger


class SyncFolderConfigDialog(MessageBoxBase):
    """ 同步文件夹配置对话框 """

    def __init__(self, folder_path, config_manager, db, parent=None, current_cfg=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.db = db
        self.folder_path = folder_path
        self.current_cfg = current_cfg or {}
        self.titleLabel = SubtitleLabel(Path(folder_path).name, self)
        self.viewLayout.addWidget(self.titleLabel)
        # 同步文件夹地址
        h1 = QHBoxLayout()
        h1.addWidget(BodyLabel(self.tr("Local folder:")))
        self.sync_folder_display = LineEdit()
        self.sync_folder_display.setText(folder_path)
        self.sync_folder_display.setReadOnly(True)
        h1.addWidget(self.sync_folder_display)
        self.viewLayout.addLayout(h1)
        # 同步频率类型
        h2 = QHBoxLayout()
        h2.addWidget(BodyLabel(self.tr("Interval Type:")))
        self.interval_combo = ComboBox()
        self._interval_keys = ["minutely", "hourly", "daily"]
        for key in self._interval_keys:
            self.interval_combo.addItem(self.tr(key), userData=key)
        current_interval = self.current_cfg.get("interval_type", "hourly")
        idx = self._interval_keys.index(current_interval) if current_interval in self._interval_keys else 1
        self.interval_combo.setCurrentIndex(idx)
        h2.addWidget(self.interval_combo)
        self.viewLayout.addLayout(h2)
        # 频率数值
        h3 = QHBoxLayout()
        h3.addWidget(BodyLabel(self.tr("Interval Value:")))
        self.interval_spin = SpinBox()
        self.interval_spin.setRange(1, 60)
        self.interval_spin.setValue(self.current_cfg.get("interval_value", 60))
        h3.addWidget(self.interval_spin)
        self.viewLayout.addLayout(h3)
        # 频道名（可选，留空则使用本地文件夹名）
        h4 = QHBoxLayout()
        h4.addWidget(BodyLabel(self.tr("Channel Name:")))
        self.channel_name_edit = LineEdit()
        self.channel_name_edit.setText(self.current_cfg.get("channel_name") or Path(folder_path).name)
        self.channel_name_edit.setMaxLength(255)
        h4.addWidget(self.channel_name_edit)
        self.viewLayout.addLayout(h4)
        self.yesButton.setText(self.tr("OK"))
        self.cancelButton.setText(self.tr("Cancel"))
        self.widget.setMinimumWidth(450)

    def get_config(self):
        idx = self.interval_combo.currentIndex()
        interval = self._interval_keys[idx] if 0 <= idx < len(self._interval_keys) else "hourly"
        return {
            "interval_type": interval,
            "interval_value": self.interval_spin.value(),
            "target_dir_id": self.current_cfg.get("target_dir_id", 0),
            "channel_name": self.channel_name_edit.text().strip(),
        }


# ==================== SyncFolderListSettingCard 相关组件 ====================

class SyncFolderItem(QWidget):
    """ 单个同步文件夹条目：路径 + 配置摘要 + 编辑/删除按钮 """

    removed = Signal(QWidget)
    edited = Signal(QWidget)

    def __init__(self, folder_path: str, cfg: dict, parent=None):
        super().__init__(parent=parent)
        self.folder_path = folder_path
        self.folder_cfg = cfg

        self.setFixedHeight(58)
        self.hBoxLayout = QHBoxLayout(self)
        self.hBoxLayout.setContentsMargins(48, 6, 48, 6)
        self.hBoxLayout.setSpacing(12)

        # 左侧：文件夹图标 + 文本信息
        icon_label = QLabel()
        icon_label.setFixedSize(20, 20)
        icon_label.setPixmap(FluentIcon.FOLDER.icon().pixmap(20, 20))

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        text_layout.setContentsMargins(0, 0, 0, 0)

        self.name_label = BodyLabel(cfg.get("channel_name", " - "))
        self.name_label.setObjectName("titleLabel")
        text_layout.addWidget(self.name_label)

        self.summary_label = CaptionLabel(folder_path + " | " +self._build_summary(cfg))
        self.summary_label.setTextColor(QColor(96, 96, 96), QColor(206, 206, 206))
        text_layout.addWidget(self.summary_label)

        self.hBoxLayout.addWidget(icon_label)
        self.hBoxLayout.addLayout(text_layout)
        self.hBoxLayout.addStretch(1)

        # 右侧：编辑 / 删除按钮
        self.edit_btn = ToolButton(FluentIcon.EDIT, self)
        self.edit_btn.setFixedSize(32, 32)
        self.edit_btn.setIconSize(QSize(14, 14))
        self.edit_btn.clicked.connect(lambda: self.edited.emit(self))
        self.hBoxLayout.addWidget(self.edit_btn)

        self.remove_btn = ToolButton(FluentIcon.CLOSE, self)
        self.remove_btn.setFixedSize(32, 32)
        self.remove_btn.setIconSize(QSize(12, 12))
        self.remove_btn.clicked.connect(lambda: self.removed.emit(self))
        self.hBoxLayout.addWidget(self.remove_btn)

    @staticmethod
    def _build_summary(cfg: dict) -> str:
        interval = cfg.get("interval_type", "hourly")
        val = cfg.get("interval_value", 60)
        return f"every {val} {interval}"

    def update_config(self, new_cfg: dict):
        self.folder_cfg = new_cfg
        self.summary_label.setText(self._build_summary(new_cfg))


class SyncFolderListSettingCard(ExpandSettingCard):
    """ 同步文件夹列表卡片（可展开），添加时弹出 SyncFolderConfigDialog """

    folderChanged = Signal()

    def __init__(self, config_manager: ConfigManager, db, task_manager=None,
                 title: str = None, content: str = None, parent=None):
        super().__init__(FluentIcon.FOLDER, title, content, parent)
        self.config_manager = config_manager
        self.config = config_manager.config
        self.db = db
        self.task_manager = task_manager

        self.addFolderButton = PushButton(
            self.tr("Add folder"), self, FluentIcon.FOLDER_ADD
        )

        self._initWidget()

    def _initWidget(self):
        self.addWidget(self.addFolderButton)

        self.viewLayout.setSpacing(0)
        self.viewLayout.setAlignment(Qt.AlignTop)
        self.viewLayout.setContentsMargins(0, 0, 0, 0)

        # 加载已有文件夹
        folders = self.config.get("auto_sync_settings", {}).get("folders", {})
        for path, cfg in folders.items():
            self._addFolderItem(path, cfg)

        self.addFolderButton.clicked.connect(self._onAddFolder)

    # ---- 添加文件夹 ----

    def _onAddFolder(self):
        folder = QFileDialog.getExistingDirectory(
            self.window(), self.tr("Select Folder")
        )
        if not folder:
            return

        folders = self.config.get("auto_sync_settings", {}).get("folders", {})
        if folder in folders:
            return

        dlg = SyncFolderConfigDialog(folder, self.config_manager, self.db, self.window())
        if dlg.exec():
            cfg = dlg.get_config()
            self._ensure_auto_sync_config()
            # 确定频道名：自定义名 > 本地文件夹名
            channel_name = cfg.get("channel_name") or Path(folder).name
            # 确保 config 中写入的是有效频道名（而非空字符串）
            cfg["channel_name"] = channel_name
            # 1. 立即创建 Directory 记录
            dir_id = self.db.dirs.add_directory(channel_name, parent_id=0, is_sync=1)
            cfg["target_dir_id"] = dir_id
            # 先保存 config（含 target_dir_id），UI 可以先显示
            self.config["auto_sync_settings"]["folders"][folder] = cfg
            self.config_manager.save()
            self._addFolderItem(folder, cfg)
            self.folderChanged.emit()
            # 2. 异步创建 TG Channel
            self._create_channel_for_folder(folder, channel_name, dir_id)

    def _ensure_auto_sync_config(self):
        """确保 auto_sync_settings 和 folders 键存在。"""
        if "auto_sync_settings" not in self.config:
            self.config["auto_sync_settings"] = {}
        if "folders" not in self.config["auto_sync_settings"]:
            self.config["auto_sync_settings"]["folders"] = {}

    def _create_channel_for_folder(self, folder_path, channel_name, dir_id):
        """通过 TaskManager 在 TG 上创建频道并更新 DB 记录。"""
        if self.task_manager is None:
            logger.warning(f"[SettingsPage] TaskManager 不可用，跳过频道创建: {folder_path}")
            return

        creds = self.db.users.get_active_credentials()
        if not creds:
            logger.warning(f"[SettingsPage] 无活跃用户凭证，跳过频道创建: {folder_path}")
            return

        db = self.db
        folder_name = channel_name  # 闭包捕获

        async def _create(client):
            uploader = TelethonUploader(creds["api_id"], creds["api_hash"])
            return await uploader.ensure_channel(client, folder_name, dir_id, db)

        def on_result(channel_id):
            logger.info(f"[SettingsPage] 频道已创建: {folder_path} -> channel={channel_id}")

        def on_error(err):
            logger.error(f"[SettingsPage] 频道创建失败: {folder_path} -> {err}")
            InfoBar.error(
                self.tr("Channel creation failed"),
                f"{Path(folder_path).name}: {err}",
                parent=self.window(),
            )

        self.task_manager.run_on_client(_create, on_result, on_error)

    def _addFolderItem(self, folder_path: str, cfg: dict):
        item = SyncFolderItem(folder_path, cfg, self.view)
        item.removed.connect(self._onRemoveItem)
        item.edited.connect(self._onEditItem)
        self.viewLayout.addWidget(item)
        item.show()
        self._adjustViewSize()

    # ---- 编辑文件夹 ----

    def _onEditItem(self, item: SyncFolderItem):
        current_cfg = (
            self.config.get("auto_sync_settings", {})
            .get("folders", {})
            .get(item.folder_path, {})
        )
        dlg = SyncFolderConfigDialog(
            item.folder_path, self.config_manager, self.db, self.window(), current_cfg
        )
        if dlg.exec():
            new_cfg = dlg.get_config()
            # 确保 channel_name 不为空：留空则回退为本地文件夹名
            if not new_cfg.get("channel_name"):
                new_cfg["channel_name"] = Path(item.folder_path).name
            self.config["auto_sync_settings"]["folders"][item.folder_path] = new_cfg
            self.config_manager.save()
            item.update_config(new_cfg)
            # 频道名变更 → 同步更新 DB 和 TG 频道标题
            self._sync_channel_name(item.folder_path, current_cfg, new_cfg)
            self.folderChanged.emit()

    @staticmethod
    def _effective_name(folder_path: str, cfg: dict) -> str:
        """获取实际的频道名：自定义名 > 本地文件夹名。"""
        return cfg.get("channel_name", "") or Path(folder_path).name

    def _sync_channel_name(self, folder_path: str, old_cfg: dict, new_cfg: dict):
        """频道名变更时，同步更新 DB Directory.name 和 TG 频道标题。"""
        old_name = self._effective_name(folder_path, old_cfg)
        new_name = self._effective_name(folder_path, new_cfg)
        if new_name == old_name:
            return

        dir_id = new_cfg.get("target_dir_id", 0)
        if not dir_id or not self.db:
            return

        # 1. 更新 DB Directory 名称
        self.db.dirs.rename_directory(dir_id, new_name)
        logger.info(f"[SettingsPage] 目录已重命名: id={dir_id}, name={new_name}")

        # 2. 异步更新 TG 频道标题
        if self.task_manager is None:
            return
        channel_id = self.db.dirs.get_directory_channel(dir_id)
        if not channel_id or channel_id == "me":
            return

        db = self.db

        async def _rename(client):
            from telethon.tl.functions.channels import EditTitleRequest
            from telethon.tl.types import PeerChannel
            entity = await client.get_input_entity(PeerChannel(int(channel_id)))
            await client(EditTitleRequest(channel=entity, title=new_name))

        def on_result(_):
            logger.info(f"[SettingsPage] TG 频道已重命名: {channel_id} -> {new_name}")

        def on_error(err):
            logger.error(f"[SettingsPage] TG 频道重命名失败: {channel_id} -> {err}")

        self.task_manager.run_on_client(_rename, on_result, on_error)

    # ---- 删除文件夹 ----

    def _onRemoveItem(self, item: SyncFolderItem):
        name = Path(item.folder_path).name
        # 第一步：确认删除配置
        title = self.tr("Confirm deletion")
        content = (
            self.tr('Remove sync configuration for "') + name
            + self.tr('"?\n\nThis will NOT delete your local files.')
        )
        dlg = Dialog(title, content, self.window())
        dlg.yesSignal.connect(lambda: self._confirmChannelDeletion(item))
        dlg.exec()

    def _confirmChannelDeletion(self, item: SyncFolderItem):
        """询问用户是否同时删除 TG 频道。"""
        cfg = (
            self.config.get("auto_sync_settings", {})
            .get("folders", {})
            .get(item.folder_path, {})
        )
        dir_id = cfg.get("target_dir_id", 0)
        # 检查是否有有效的频道可以删除
        has_channel = False
        if dir_id and self.db:
            channel_id = self.db.dirs.get_directory_channel(dir_id)
            has_channel = bool(channel_id and channel_id != "me")

        if not has_channel:
            # 没有频道，直接删除配置
            self._removeFolder(item, delete_channel=False)
            return

        name = Path(item.folder_path).name
        title = self.tr("Delete Telegram channel?")
        content = (
            self.tr('Also delete the Telegram channel for "') + name
            + self.tr('"?\n\nFiles already uploaded to this channel will become inaccessible.')
        )
        dlg = Dialog(title, content, self.window())
        dlg.yesSignal.connect(lambda: self._removeFolder(item, delete_channel=True))
        dlg.cancelSignal.connect(lambda: self._removeFolder(item, delete_channel=False))
        dlg.exec()

    def _removeFolder(self, item: SyncFolderItem, delete_channel: bool = False):
        """删除同步文件夹配置，可选删除 TG 频道和数据库记录。"""
        cfg = (
            self.config.get("auto_sync_settings", {})
            .get("folders", {})
            .get(item.folder_path, {})
        )
        dir_id = cfg.get("target_dir_id", 0)

        # 1. 从配置中移除
        folders = self.config.get("auto_sync_settings", {}).get("folders", {})
        if item.folder_path in folders:
            del folders[item.folder_path]
            self.config_manager.save()

        # 2. 清理同步状态
        if self.db:
            self.db.sync_status.delete_sync_folder_status(item.folder_path)

        # 3. 可选：删除 TG 频道和数据库目录记录
        if delete_channel and dir_id and self.db and self.task_manager:
            self._delete_channel_and_dir(dir_id, Path(item.folder_path).name)

        # 4. 移除 UI
        self.viewLayout.removeWidget(item)
        item.deleteLater()
        self._adjustViewSize()
        self.folderChanged.emit()

    def _delete_channel_and_dir(self, dir_id: int, folder_name: str):
        """异步删除 TG 频道和本地目录记录。"""
        creds = self.db.users.get_active_credentials()
        if not creds:
            logger.warning(f"[SettingsPage] 无活跃用户凭证，仅删除本地记录: dir_id={dir_id}")
            self.db.dirs.delete_directory_recursive(dir_id)
            return

        db = self.db

        async def _delete(client):
            from telethon.tl.functions.channels import DeleteChannelRequest
            channel_id = db.dirs.get_directory_channel(dir_id)
            if channel_id and channel_id != "me":
                try:
                    from telethon.tl.types import PeerChannel
                    entity = await client.get_input_entity(PeerChannel(int(channel_id)))
                    await client(DeleteChannelRequest(channel=entity))
                    logger.info(f"[SettingsPage] TG 频道已删除: {channel_id}")
                except Exception as e:
                    logger.warning(f"[SettingsPage] 删除 TG 频道失败: {e}")
            # 无论 TG 删除成功与否，都清理本地数据库
            db.dirs.delete_directory_recursive(dir_id)

        def on_result(_):
            logger.info(f"[SettingsPage] 同步文件夹已完全删除: {folder_name}")
            InfoBar.success(
                self.tr("Deleted"),
                self.tr('Sync folder "{}" and its channel have been deleted.').format(folder_name),
                parent=self.window(),
            )

        def on_error(err):
            logger.error(f"[SettingsPage] 删除频道失败: {err}")
            # 即使 TG 操作失败，也清理本地数据
            try:
                db.dirs.delete_directory_recursive(dir_id)
            except Exception:
                pass
            InfoBar.warning(
                self.tr("Partially deleted"),
                self.tr('Channel deletion failed, but local config has been removed.'),
                parent=self.window(),
            )

        self.task_manager.run_on_client(_delete, on_result, on_error)

    def reload(self):
        """重新加载文件夹列表（外部调用）"""
        # 清空现有条目（只 hide + deleteLater，不 setParent(None)）
        self.viewLayout.setEnabled(False)
        for i in reversed(range(self.viewLayout.count())):
            w = self.viewLayout.itemAt(i).widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        self.viewLayout.setEnabled(True)
        # 重新加载
        folders = self.config.get("auto_sync_settings", {}).get("folders", {})
        for path, cfg in folders.items():
            self._addFolderItem(path, cfg)
        self._adjustViewSize()


# ==================== SettingsPage ====================

class SettingsPage(QWidget):
    """设置页：SegmentedWidget 切换模块 + GroupHeaderCardWidget 组织配置项"""

    def __init__(self, config_manager: ConfigManager, db, task_manager=None, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsPage")
        self.config_manager = config_manager
        self.config = config_manager.config
        self.db = db
        self.task_manager = task_manager

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 24, 36, 24)
        layout.setSpacing(16)

        # ---- 页面标题 ----
        layout.addWidget(TitleLabel(self.tr("Advanced Settings")))

        # ---- 顶部分段切换器：SegmentedWidget ----
        self.segmented = SegmentedWidget()
        self.segmented.addItem("basic", self.tr("Basic"))
        self.segmented.addItem("upload_limit", self.tr("Upload Limit"))
        self.segmented.addItem("auto_sync", self.tr("Auto Sync"))
        self.segmented.currentItemChanged.connect(self._on_page_changed)
        layout.addWidget(self.segmented)

        # ---- 页面堆栈：三个模块 ----
        self.stack = QStackedWidget()
        self.stack.addWidget(self._create_basic_page())
        self.stack.addWidget(self._create_upload_limit_page())
        self.stack.addWidget(self._create_auto_sync_page())
        layout.addWidget(self.stack, stretch=1)

        # ---- 保存按钮 ----
        save_btn = PushButton(self.tr("Save"))
        save_btn.setIcon(FluentIcon.SAVE)
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn, alignment=Qt.AlignRight)

        # 默认选中第一项
        self.segmented.setCurrentItem("basic")

    # ==================== 页面切换 ====================

    def _on_page_changed(self, route_key: str):
        index_map = {"basic": 0, "upload_limit": 1, "auto_sync": 2}
        self.stack.setCurrentIndex(index_map.get(route_key, 0))

    # ==================== Basic 页面 ====================

    def _create_basic_page(self) -> QWidget:
        card = GroupHeaderCardWidget(self.tr("Basic"), self)

        # 上传重试次数
        retry_widget = QWidget()
        retry_layout = QHBoxLayout(retry_widget)
        retry_layout.setContentsMargins(0, 0, 0, 0)
        self.retry_spin = SpinBox()
        self.retry_spin.setRange(0, 10)
        self.retry_spin.setValue(self.config.get("upload_retry_times", 3))
        retry_layout.addWidget(self.retry_spin)
        retry_layout.addStretch()
        card.addGroup(
            FluentIcon.SEND,
            self.tr("Upload Retry Times"),
            self.tr("Number of times to retry a failed upload"),
            retry_widget,
        )

        # 最大并行上传数
        concurrent_widget = QWidget()
        concurrent_layout = QHBoxLayout(concurrent_widget)
        concurrent_layout.setContentsMargins(0, 0, 0, 0)
        self.concurrent_spin = SpinBox()
        self.concurrent_spin.setRange(1, 10)
        self.concurrent_spin.setValue(self.config.get("max_concurrent_uploads", 3))
        concurrent_layout.addWidget(self.concurrent_spin)
        concurrent_layout.addStretch()
        card.addGroup(
            FluentIcon.SEND_FILL,
            self.tr("Max Concurrent Uploads"),
            self.tr("Simultaneous upload operations (requires app restart)"),
            concurrent_widget,
        )

        # 默认下载路径
        dl_widget = QWidget()
        dl_layout = QHBoxLayout(dl_widget)
        dl_layout.setContentsMargins(0, 0, 0, 0)
        self.dl_path_edit = LineEdit()
        self.dl_path_edit.setText(self.config.get("download_path", ""))
        self.dl_path_edit.setMinimumWidth(260)
        dl_layout.addWidget(self.dl_path_edit)
        browse_btn = PushButton(self.tr("Browse"))
        browse_btn.clicked.connect(self._select_download_path)
        dl_layout.addWidget(browse_btn)
        card.addGroup(
            FluentIcon.DOWNLOAD,
            self.tr("Default Download Path"),
            self.tr("Directory where downloaded files are saved"),
            dl_widget,
        )

        # 语言
        lang_widget = QWidget()
        lang_layout = QHBoxLayout(lang_widget)
        lang_layout.setContentsMargins(0, 0, 0, 0)
        self.language_combo = ComboBox()
        self._lang_data = [
            ("zh", "Chinese"),
            ("en", "English"),
            ("fr", "French"),
            ("de", "German"),
            ("ru", "Russian"),
            ("ko", "Korean"),
        ]
        for code, name in self._lang_data:
            self.language_combo.addItem(self.tr(name), userData=code)
        current_lang = self.config.get("language", "en")
        for i, (code, _) in enumerate(self._lang_data):
            if code == current_lang:
                self.language_combo.setCurrentIndex(i)
                break
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        lang_layout.addWidget(self.language_combo)
        lang_layout.addStretch()
        card.addGroup(
            FluentIcon.LANGUAGE,
            self.tr("Language"),
            self.tr("Application display language"),
            lang_widget,
        )

        return card

    # ==================== Upload Limit 页面 ====================

    def _create_upload_limit_page(self) -> QWidget:
        card = GroupHeaderCardWidget(self.tr("Upload Limit"), self)

        # 启用每日限制
        en_widget = QWidget()
        en_layout = QHBoxLayout(en_widget)
        en_layout.setContentsMargins(0, 0, 0, 0)
        self.limit_enabled = SwitchButton()
        self.limit_enabled.setChecked(
            self.config.get("upload_limit_settings", {}).get("enabled", False)
        )
        en_layout.addWidget(self.limit_enabled)
        en_layout.addStretch()
        card.addGroup(
            FluentIcon.INFO,
            self.tr("Enable Daily Limit"),
            self.tr("Restrict total upload volume per day"),
            en_widget,
        )

        # 每日最大容量 (GB)
        max_size_widget = QWidget()
        max_size_layout = QHBoxLayout(max_size_widget)
        max_size_layout.setContentsMargins(0, 0, 0, 0)
        self.max_size_spin = DoubleSpinBox()
        self.max_size_spin.setRange(0.1, 1000)
        self.max_size_spin.setValue(
            self.config.get("upload_limit_settings", {}).get("max_daily_size_gb", 10)
        )
        max_size_layout.addWidget(self.max_size_spin)
        max_size_layout.addStretch()
        card.addGroup(
            FluentIcon.CLOUD,
            self.tr("Max Size (GB)"),
            self.tr("Maximum total upload size per day"),
            max_size_widget,
        )

        # 每日最大文件数
        max_files_widget = QWidget()
        max_files_layout = QHBoxLayout(max_files_widget)
        max_files_layout.setContentsMargins(0, 0, 0, 0)
        self.max_files_spin = SpinBox()
        self.max_files_spin.setRange(1, 10000)
        self.max_files_spin.setValue(
            self.config.get("upload_limit_settings", {}).get("max_daily_files", 100)
        )
        max_files_layout.addWidget(self.max_files_spin)
        max_files_layout.addStretch()
        card.addGroup(
            FluentIcon.FOLDER,
            self.tr("Max Files"),
            self.tr("Maximum number of files per day"),
            max_files_widget,
        )

        # 单文件最大大小
        single_widget = QWidget()
        single_layout = QHBoxLayout(single_widget)
        single_layout.setContentsMargins(0, 0, 0, 0)
        self.single_file_slider = Slider(Qt.Horizontal)
        self.single_file_slider.setRange(1, 1536)
        self.single_file_slider.setMinimumWidth(200)
        max_single_gb = self.config.get("upload_limit_settings", {}).get(
            "max_single_file_size_gb", 1.5
        )
        self.single_file_slider.setValue(int(max_single_gb * 1024))
        self.single_file_value_label = BodyLabel(f"{max_single_gb:.2f} GB")
        self.single_file_slider.valueChanged.connect(
            lambda v: self.single_file_value_label.setText(f"{v / 1024.0:.2f} GB")
        )
        single_layout.addWidget(self.single_file_slider)
        single_layout.addWidget(self.single_file_value_label)
        single_layout.addStretch()
        card.addGroup(
            FluentIcon.SAVE_AS,
            self.tr("Max Single File Size"),
            self.tr("Maximum size of a single uploaded file"),
            single_widget,
        )

        return card

    # ==================== Auto Sync 页面 ====================

    def _create_auto_sync_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        # 启用自动同步（GroupHeaderCardWidget 卡片）
        card = GroupHeaderCardWidget(self.tr("Auto Sync"), self)
        sync_en_widget = QWidget()
        sync_en_layout = QHBoxLayout(sync_en_widget)
        sync_en_layout.setContentsMargins(0, 0, 0, 0)
        self.sync_enabled = SwitchButton()
        self.sync_enabled.setChecked(
            self.config.get("auto_sync_settings", {}).get("enabled", False)
        )
        sync_en_layout.addWidget(self.sync_enabled)
        sync_en_layout.addStretch()
        card.addGroup(
            FluentIcon.SYNC,
            self.tr("Enable Auto Sync"),
            self.tr("Automatically synchronize watched folders to Telegram"),
            sync_en_widget,
        )
        layout.addWidget(card)

        # Watched Folders（SyncFolderListSettingCard 可展开卡片，默认展开）
        self.folder_list_card = SyncFolderListSettingCard(
            self.config_manager,
            self.db,
            self.task_manager,
            self.tr("Watched Folders"),
            self.tr("Folders monitored for automatic synchronization"),
            self,
        )
        self.folder_list_card.setExpand(True)
        layout.addWidget(self.folder_list_card)

        layout.addStretch()
        return page

    # ==================== 下载路径 ====================

    def _select_download_path(self):
        path = QFileDialog.getExistingDirectory(self, self.tr("Select Download Directory"))
        if path:
            self.dl_path_edit.setText(path)

    # ==================== 语言切换 ====================

    def _on_language_changed(self, index):
        new_lang = self.language_combo.itemData(index)
        if not new_lang or not isinstance(new_lang, str):
            return
        old_lang = self.config.get("language", "zh")
        if new_lang == old_lang:
            return
        self.config["language"] = new_lang
        self.config_manager.save()
        msg_box = MessageBox(
            self.tr("Restart Required"),
            self.tr("Language changed. Restart now?"),
            self,
        )
        if msg_box.exec():
            self._restart_app()

    @staticmethod
    def _restart_app():
        QProcess.startDetached(sys.executable, sys.argv)
        QApplication.quit()

    # ==================== 保存 ====================

    def _save(self):
        self.config["upload_retry_times"] = self.retry_spin.value()
        old_concurrent = self.config.get("max_concurrent_uploads", 1)
        new_concurrent = self.concurrent_spin.value()
        self.config["max_concurrent_uploads"] = new_concurrent
        self.config["download_path"] = self.dl_path_edit.text()
        self.config["upload_limit_settings"] = {
            "enabled": self.limit_enabled.isChecked(),
            "max_daily_size_gb": self.max_size_spin.value(),
            "max_daily_files": self.max_files_spin.value(),
            "max_single_file_size_gb": self.single_file_slider.value() / 1024.0,
            "reset_hour": 0,
        }
        if "auto_sync_settings" not in self.config:
            self.config["auto_sync_settings"] = {}
        self.config["auto_sync_settings"]["enabled"] = self.sync_enabled.isChecked()
        lang = self.language_combo.itemData(self.language_combo.currentIndex())
        self.config["language"] = lang if lang else "zh"
        self.config_manager.save()
        InfoBar.success(
            self.tr("Success"), self.tr("Settings saved"), parent=self.window()
        )
        if new_concurrent != old_concurrent:
            msg_box = MessageBox(
                self.tr("Restart Required"),
                self.tr("Max concurrent uploads changed. Restart now?"),
                self,
            )
            if msg_box.exec():
                self._restart_app()
