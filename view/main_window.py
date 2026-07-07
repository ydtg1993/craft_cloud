from pathlib import Path
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QFileDialog, QMessageBox
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QIcon, QCursor
from qfluentwidgets import (FluentWindow, NavigationItemPosition, FluentIcon,
                            InfoBar, InfoBarPosition, RoundMenu, Action, MessageBox,
                            InfoBadge, InfoBadgePosition)
from loguru import logger
from core.config_manager import ConfigManager
from core.db_manager import DBManager
from core.task_manager import TaskManager

from services.file_manager import FileManager
from services.upload_manager import UploadManager
from services.download_manager import DownloadManager
from services.search_manager import SearchManager, SearchErrorType
from view.sync_controller import SyncController
from view.home_page import HomePage
from view.sync_page import SyncPage
from view.settings_page import SettingsPage
from view.custom_dialogs import DateSearchDialog, SearchResultDialog, AccountDialog, NewFolderDialog
from core.utils import resource_path, get_sessions_dir
from core.translator import tr
from view.task_queue_page import TaskQueuePage
from view.about_page import AboutPage

app_icon = QIcon(str(resource_path("cc.ico")))


class MainWindow(FluentWindow):
    logout_requested = Signal()
    # 跨线程 InfoBar：worker 线程通过此信号将 UI 操作 marshall 到主线程
    _show_info_bar = Signal(str, str, str)  # bar_type, title, message

    def __init__(self, config_manager: ConfigManager):
        super().__init__()
        self.config_manager = config_manager
        self.config = config_manager.config
        self.db = DBManager()
        self.current_dir_id = 0
        self._current_preview = None
        self._total_downloaded_bytes = 0
        self._dl_task_sizes: dict[str, int] = {}  # task_id → file_size bytes

        # 连接跨线程 InfoBar 信号
        self._show_info_bar.connect(self._on_show_info_bar)

        # ---- 初始化 TaskManager（统一调度所有 TG 操作） ----
        creds = self.db.users.get_active_credentials()
        api_id = creds["api_id"] if creds else None
        api_hash = creds["api_hash"] if creds else None
        self.task_manager = TaskManager(api_id, api_hash, config_manager, db=self.db, parent=self)
        self.task_manager.db_signal.connect(self._handle_db_operation)
        self.task_manager.session_expired.connect(self._on_session_expired)
        self.task_manager.start()  # 启动所有 worker 线程

        # ---- 初始化管理器（服务层不再依赖 MainWindow） ----
        self.file_manager = FileManager(self.db, self.config, self.task_manager, config_manager)
        self.file_count = self.file_manager.get_file_count()
        self.file_manager.current_dir_id = 0
        self.upload_mgr = UploadManager(config_manager, self.db, self.task_manager)
        self.download_mgr = DownloadManager(config_manager, self.db, self.task_manager)
        self.search_mgr = SearchManager(self.db)
        self.sync_ctrl = SyncController(config_manager, self.db, self)

        # ---- 页面 ----
        self.home_page = HomePage(self.file_manager, self)
        self.sync_page = SyncPage(self)
        self.task_queue_page = TaskQueuePage(self, db=self.db)
        self.settings_page = SettingsPage(config_manager, self.db, self.task_manager, self)
        self.about_page = AboutPage(self)

        self.initNavigation()
        self.initWindow()

        self._connect_signals()
        self._connect_service_signals()
        self._navigate_to(0)
        view_mode_str = self.config.get("view_mode", "list")
        self.home_page.file_view.switch_view(0 if view_mode_str == "list" else 1)
        self._refresh_sync_page()
        self._refresh_home_stats()

        # 设置页中同步文件夹列表变更时，刷新 SyncPage 仪表盘
        if hasattr(self.settings_page, 'folder_list_card'):
            self.settings_page.folder_list_card.folderChanged.connect(
                self._refresh_sync_page
            )

    # --------------------------------------------------------------------------
    #  服务层信号连接（替代旧版直接 UI 调用）
    # --------------------------------------------------------------------------
    def _connect_service_signals(self):
        """连接来自 services 层的信号到 UI 响应。"""
        # FileManager
        self.file_manager.info_requested.connect(
            lambda title, msg: InfoBar.success(title, msg,
                position=InfoBarPosition.BOTTOM_RIGHT, parent=self,duration=3000))
        self.file_manager.warning_requested.connect(
            lambda title, msg: QMessageBox.warning(self, title, msg))
        self.file_manager.error_requested.connect(
            lambda title, msg: InfoBar.error(title, msg,
                position=InfoBarPosition.BOTTOM_RIGHT, parent=self,duration=3000))
        self.file_manager.confirmation_requested.connect(self._handle_service_confirmation)
        self.file_manager.ui_refresh_needed.connect(self._refresh_current_directory)

        # UploadManager
        self.upload_mgr.warning_requested.connect(
            lambda title, msg: InfoBar.warning(title, msg,
                position=InfoBarPosition.BOTTOM_RIGHT, parent=self,duration=3000))

        # SearchManager
        self.search_mgr.search_completed.connect(self._on_search_completed)

        # TaskManager — 追踪下载量用于底部状态栏
        self.task_manager.task_added.connect(self._on_task_added_for_stats)
        self.task_manager.task_finished.connect(self._on_task_finished_for_stats)

    def _handle_service_confirmation(self, title, message, callback):
        """处理来自 service 层的确认请求。"""
        w = MessageBox(title, message, self)
        if w.exec():
            callback()

    def _on_search_completed(self, results, error_msg):
        """处理搜索结果。"""
        if error_msg == SearchErrorType.EMPTY_KEYWORD.value:
            InfoBar.warning(
                tr("Warning"), tr("Please enter a keyword"),
                position=InfoBarPosition.TOP, parent=self)
        elif not results:
            InfoBar.info(
                tr("No results"), tr("No files found"),
                position=InfoBarPosition.TOP, parent=self)
        else:
            self._show_search_results_flyout(results, tr("Search results"))

    # --------------------------------------------------------------------------
    #  数据库操作处理器（主线程安全）
    # --------------------------------------------------------------------------
    def _handle_db_operation(self, task_id, context):
        action = context.get("action")
        if action == "upload_complete":
            dir_id = context.get("dir_id", 0)
            self.upload_mgr.complete_upload(task_id, context)

            if self.current_dir_id == dir_id:
                self._refresh_current_directory()
            self._refresh_home_stats()

    # --------------------------------------------------------------------------
    #  导航与窗口设置
    # --------------------------------------------------------------------------
    def initNavigation(self):
        self.addSubInterface(self.home_page, FluentIcon.DOCUMENT, tr("Directories"))
        self._task_queue_nav = self.addSubInterface(
            self.task_queue_page, FluentIcon.DICTIONARY, tr("Task Queue"))
        self._task_queue_badge = InfoBadge.attension(
            "0", self, target=self._task_queue_nav, position=InfoBadgePosition.NAVIGATION_ITEM)
        self._task_queue_badge.hide()
        self.addSubInterface(self.sync_page, FluentIcon.SYNC, tr("Auto Sync"))
        self.addSubInterface(self.settings_page, FluentIcon.SETTING, tr("Settings"))
        self.addSubInterface(
            self.about_page, FluentIcon.INFO, tr("About"),
            position=NavigationItemPosition.BOTTOM)
        self.account_btn = self.navigationInterface.addItem(
            routeKey='account',
            icon=FluentIcon.PEOPLE,
            text=tr("Account"),
            onClick=self._show_account_flyout,
            position=NavigationItemPosition.BOTTOM
        )

    def initWindow(self):
        self.resize(1024, 768)
        self.setWindowTitle(tr("CraftCloud"))
        self.setWindowIcon(app_icon)
        self.navigationInterface.setExpandWidth(160)
        # 禁用 Mica 毛玻璃效果，防止拖拽窗口时抖动
        self.setMicaEffectEnabled(False)
        self.tray_icon = self._setup_tray_icon()

    def _connect_signals(self):

        self.home_page.breadcrumb.currentItemChanged.connect(self._on_breadcrumb_changed)
        self.home_page.search_btn.clicked.connect(
            lambda: self.search_mgr.search_by_filename(
                self.home_page.search_input.text(), self.file_count))
        self.home_page.search_input.returnPressed.connect(
            lambda: self.search_mgr.search_by_filename(
                self.home_page.search_input.text(), self.file_count))
        self.home_page.date_btn.clicked.connect(self._show_date_flyout)
        self.home_page.list_btn.clicked.connect(lambda: self._change_view_mode(0))
        self.home_page.icon_btn.clicked.connect(lambda: self._change_view_mode(1))
        self.home_page.sort_combo.currentTextChanged.connect(
            self.home_page.file_view.apply_sort)
        self.home_page.file_view.item_activated.connect(self._on_item_activated)
        self.home_page.file_view.file_operation_requested.connect(self._dispatch_file_operation)
        self.sync_ctrl.sync_status.connect(self._on_sync_status)
        self.sync_ctrl.sync_progress.connect(self._on_sync_progress)
        self.sync_ctrl.sync_completed.connect(self._on_sync_completed)

        self.task_manager.task_added.connect(self._on_task_added)
        self.task_manager.task_progress.connect(self.task_queue_page.update_task_progress)
        self.task_manager.task_finished.connect(self._on_task_finished_for_queue)

    def _on_task_added(self, task_id, description, task_type, file_size="-"):
        self.task_queue_page.add_task(task_id, description, task_type, file_size)
        self._update_badge_count()

    def _on_task_finished_for_queue(self, task_id, status):
        self.task_queue_page.update_task_status(task_id, status)
        self._update_badge_count()

    def _update_badge_count(self):
        """根据 TaskQueuePage 中活跃任务数更新导航菜单角标。"""
        count = self.task_queue_page.active_task_count()
        if count <= 0:
            self._task_queue_badge.hide()
        else:
            text = "99+" if count > 99 else str(count)
            self._task_queue_badge.setText(text)
            self._task_queue_badge.adjustSize()
            self._task_queue_badge.show()

    def _change_view_mode(self, mode):
        self.home_page.file_view.switch_view(mode)
        self.home_page.list_btn.setChecked(mode == 0)
        self.home_page.icon_btn.setChecked(mode == 1)
        self.config_manager.set_view_mode("list" if mode == 0 else "icon")

    def _on_breadcrumb_changed(self, key):
        if key is not None:
            try:
                self._navigate_to(int(key))
            except (ValueError, TypeError) as e:
                logger.debug(f"面包屑导航失败 key={key}: {e}")

    # ---- 上传/下载的 QFileDialog 处理（view 层职责） ----
    def _do_upload_files(self):
        if self.current_dir_id == 0:
            InfoBar.warning(
                tr("Warning"), tr("Root is an abstraction layer. Please select a folder to upload."),
                position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        paths, _ = QFileDialog.getOpenFileNames(self, tr("Select Files"))
        if paths:
            self.upload_mgr.start_upload(paths, self.current_dir_id)

    def _do_upload_folder(self):
        if self.current_dir_id == 0:
            InfoBar.warning(
                tr("Warning"), tr("Root is an abstraction layer. Please select a folder to upload."),
                position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        folder = QFileDialog.getExistingDirectory(self, tr("Select Folder"))
        if folder:
            all_files = []
            for file_path in Path(folder).rglob('*'):
                if file_path.is_file():
                    all_files.append(str(file_path))
            if all_files:
                self.upload_mgr.start_upload(all_files, self.current_dir_id)

    def _do_create_directory(self, folder_name=None):
        if not folder_name:
            dlg = NewFolderDialog(self)
            if dlg.exec():
                folder_name = dlg.name_edit.text().strip()
            else:
                return
        if folder_name:
            logger.info(f"[MainWindow] _do_create_directory: start folder_name={folder_name}, current_dir_id={self.current_dir_id}")
            # 检查当前目录下是否已存在同名文件夹
            if self._is_duplicate_dir_name(folder_name):
                InfoBar.warning(
                    tr("Duplicate Folder"),
                    tr('A folder named "{name}" already exists in the current directory. '
                       'Please use a different name.').format(name=folder_name),
                    position=InfoBarPosition.BOTTOM_RIGHT, parent=self,duration=3000
                )
                return
            self.file_manager.current_dir_id = self.current_dir_id
            logger.info(f"[MainWindow] _do_create_directory: calling create_directory")
            dir_id = self.file_manager.create_directory(folder_name)
            logger.info(f"[MainWindow] _do_create_directory: create_directory returned dir_id={dir_id}")
            # 为根级普通文件夹创建 TG 频道（非 Saved Messages / 非同步文件夹）
            if dir_id and self.current_dir_id == 0 and folder_name != "Saved Messages":
                logger.info(f"[MainWindow] _do_create_directory: scheduling channel creation")
                self._create_channel_for_new_directory(folder_name, dir_id)
            logger.info(f"[MainWindow] _do_create_directory: done")

    def _create_channel_for_new_directory(self, folder_name, dir_id):
        """为新建的根级目录在 TG 上创建对应频道。

        与 SettingsPage._create_channel_for_folder 逻辑一致：
        通过 TaskManager.run_on_client 在共享 TelethonClient 上
        调用 ensure_channel，异步完成频道创建并更新 DB 记录。
        """
        creds = self.db.users.get_active_credentials()
        if not creds:
            logger.warning(f"[MainWindow] 无活跃凭证，跳过频道创建: {folder_name}")
            return

        from core.telegram_uploader import TelethonUploader

        db = self.db
        # 在主线程预计算 i18n 字符串
        err_title = tr("Channel creation failed")

        async def _create(client):
            uploader = TelethonUploader(creds["api_id"], creds["api_hash"])
            return await uploader.ensure_channel(client, folder_name, dir_id, db)

        def on_result(channel_id):
            logger.info(f"[MainWindow] 频道已创建: {folder_name} -> channel={channel_id}")

        def on_error(err):
            logger.error(f"[MainWindow] 频道创建失败: {folder_name} -> {err}")
            self._show_info_bar.emit("error", err_title, f"{folder_name}: {err}")

        self.task_manager.run_on_client(_create, on_result, on_error)

    def _is_duplicate_dir_name(self, name):
        """检查当前目录下是否已存在同名文件夹。"""
        items = self.file_manager.get_current_dir_items(self.current_dir_id)
        for item in items:
            if item.is_dir == 1 and item.name == name:
                return True
        return False

    # ---- 文件/目录操作的 UI 处理器（供 file_view_stack 上下文菜单调用） ----
    def _handle_file_download(self, file_info):
        """打开保存对话框并执行下载。"""
        if not file_info:
            return
        default_name = file_info.display_name or file_info.original_name or "file"
        save_path, _ = QFileDialog.getSaveFileName(
            self, tr("Save File"),
            self.config.get("download_path", "") + "/" + default_name)
        if save_path:
            self.download_mgr.start_download(file_info, save_path)

    def _handle_folder_download(self, dir_id):
        """打开目录选择对话框并执行文件夹下载。"""
        root_save_dir = QFileDialog.getExistingDirectory(self, tr("Select Save Directory"))
        if root_save_dir:
            self.download_mgr.start_folder_download(dir_id, root_save_dir)

    def _handle_file_delete(self, file_ids):
        """确认后执行文件删除。"""
        if not file_ids:
            return
        msg = tr("Delete {count} file(s)?").format(count=len(file_ids))
        w = MessageBox(tr("Confirm"), msg, self)
        if w.exec():
            self.file_manager.delete_files(file_ids)

    def _handle_dir_delete(self, dir_id, name):
        """确认后执行目录删除。

        一级目录（parent_id == 0 且有 channel）：提示将同步删除 Telegram 频道。
        子目录：提示将同步清理 Telegram 上的对应资源。
        """
        if not isinstance(dir_id, int) or dir_id <= 0:
            logger.warning(f"[UI] _handle_dir_delete 收到无效 dir_id={dir_id!r} (type={type(dir_id).__name__}), 已忽略")
            return
        info = self.file_manager.get_dir_info(dir_id)
        if not info:
            return
        if info.channel_id == "me" and info.parent_id == 0:
            return  # Saved Messages 是系统目录，不允许删除

        total = self.file_manager.get_file_count_recursive(dir_id)
        if info.parent_id == 0 and info.channel_id:
            # 一级目录：关联的 Telegram 频道将被同步删除
            title = tr("Delete Directory and Channel")
            msg = tr(
                'Delete directory "{name}" and its Telegram channel?\n\n'
                "This will permanently remove the channel and all {total} file(s) "
                "within it. This action cannot be undone."
            ).format(name=name, total=total)
        else:
            # 子目录：仅清理 Telegram 上的对应资源
            title = tr("Delete Directory")
            msg = tr(
                'Delete directory "{name}"?\n\n'
                "Corresponding files on Telegram will also be cleaned up. "
                "This action cannot be undone."
            ).format(name=name)
        w = MessageBox(title, msg, self)
        if w.exec():
            self.file_manager.delete_directory(dir_id)

    # ---- Dialog 弹窗逻辑 ----
    def _show_date_flyout(self):
        dialog = DateSearchDialog(self)
        if dialog.exec():
            start = dialog.start_edit.date().toString("yyyy-MM-dd")
            end = dialog.end_edit.date().toString("yyyy-MM-dd")
            self.search_mgr.search_by_date_range(start, end)

    def _show_search_results_flyout(self, results, search_type):
        dialog = SearchResultDialog(results, search_type, self._navigate_to, self)
        dialog.exec()

    def _show_account_flyout(self):
        dialog = AccountDialog(self.config,
                               logout_callback=self._do_logout, parent=self)
        dialog.exec()

    # ---- 核心导航逻辑 ----
    def _navigate_to(self, dir_id):
        if dir_id != 0 and not self.file_manager.get_dir_info(dir_id):
            dir_id = 0
        self.current_dir_id = dir_id
        self.file_manager.current_dir_id = dir_id
        items = self.file_manager.get_current_dir_items(dir_id)
        self.home_page.file_view.load_items(items)
        path = self.file_manager.get_breadcrumb_path(dir_id)
        # 使用 blockSignals 避免断开/重连信号 — 更安全且更清晰
        self.home_page.breadcrumb.blockSignals(True)
        self.home_page.breadcrumb.clear()
        for d_id, name in path:
            self.home_page.breadcrumb.addItem(str(d_id), name)
        if str(dir_id) in self.home_page.breadcrumb.itemMap:
            self.home_page.breadcrumb.setCurrentItem(str(dir_id))
        self.home_page.breadcrumb.blockSignals(False)


    def _on_item_activated(self, item_id, is_dir):
        if is_dir:
            self._navigate_to(item_id)
        else:
            file_info = self.file_manager.get_file_info(item_id)
            if file_info:
                self._preview_file(file_info)

    def _dispatch_file_operation(self, operation, params):
        if operation == "download":
            file_info = params
            default_name = file_info.display_name or file_info.original_name or "file"
            save_path, _ = QFileDialog.getSaveFileName(
                self, tr("Save File"),
                self.config.get("download_path", "") + "/" + default_name)
            if save_path:
                self.download_mgr.start_download(file_info, save_path)
        elif operation == "rename":
            # params = (local_id, old_name, new_name)
            local_id, old_name, new_name = params
            self.file_manager.rename_file(local_id, new_name)
        elif operation == "move":
            self.file_manager.move_file(*params)
        elif operation == "delete":
            # View 层先确认再删除
            msg = tr("Delete {count} file(s)?").format(count=len(params) if isinstance(params, list) else 1)
            w = MessageBox(tr("Confirm"), msg, self)
            if w.exec():
                self.file_manager.delete_files(params)
        elif operation == "properties":
            text = self.file_manager.get_properties_text(params)
            if text:
                MessageBox(tr("File Properties"), text, self).exec()

    def _refresh_home_stats(self):
        """刷新 HomePage 底部状态栏：云盘总量 + 当日上传量 + 限制。"""
        try:
            total_uploaded = self.db.files.get_total_uploaded_size()
            today_size = self.db.files.get_today_upload_size()
            today_count = self.db.files.get_today_upload_count()
            limit_cfg = self.config_manager.get_upload_limit_settings()

            upload_gb = total_uploaded / (1024 ** 3)
            download_gb = self._total_downloaded_bytes / (1024 ** 3)

            if limit_cfg.get("enabled", False):
                size_limit = limit_cfg.get("max_daily_size_gb")
                count_limit = limit_cfg.get("max_daily_files")
            else:
                size_limit = None   # None → 显示 ∞
                count_limit = None

            logger.debug(f"[HomeStats] upload={upload_gb:.2f}GB, download={download_gb:.2f}GB, "
                         f"today_size={today_size}, today_count={today_count}, "
                         f"size_limit={size_limit}, count_limit={count_limit}")

            self.home_page.update_stats(
                upload_gb=upload_gb,
                download_gb=download_gb,
                today_size_bytes=today_size,
                today_file_count=today_count,
                size_limit_gb=size_limit,
                count_limit=count_limit,
            )
        except Exception:
            logger.exception("[HomeStats] _refresh_home_stats failed")

    @staticmethod
    def _parse_display_size(s: str) -> int:
        """Parse a human-readable size string like '1.2 MB' back to bytes."""
        if not s or s == "-":
            return 0
        units = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}
        parts = s.strip().split()
        if len(parts) == 2:
            try:
                return int(float(parts[0]) * units.get(parts[1].upper(), 1))
            except (ValueError, KeyError):
                pass
        try:
            return int(s)
        except ValueError:
            return 0

    def _on_task_added_for_stats(self, task_id, description, task_type, file_size):
        """缓存下载任务的文件大小，完成时用于累计下载量。"""
        if task_type == "download":
            self._dl_task_sizes[task_id] = self._parse_display_size(file_size)

    def _on_task_finished_for_stats(self, task_id, status):
        """下载完成时累计下载量并刷新状态栏。"""
        size = self._dl_task_sizes.pop(task_id, 0)
        if size > 0:
            self._total_downloaded_bytes += size
        self._refresh_home_stats()

    def _refresh_current_directory(self):
        self._navigate_to(self.current_dir_id)

    def _on_sync_status(self, folder_path, status):
        """同步状态变更 → 更新对应卡片的状态标签。"""
        self.sync_page.update_folder_status(folder_path, status)

    def _on_sync_progress(self, folder_path, done, total):
        """同步进度更新 → 更新对应卡片的进度条和文件计数。"""
        self.sync_page.update_folder_status(folder_path, tr("Syncing"),
                                            synced_files=done, total_files=total)

    def _on_sync_completed(self, folder_path=None, count=0):
        """同步完成 → 刷新文件列表 + 重建同步页卡片（反映最新统计）。"""
        self._refresh_current_directory()
        self._refresh_sync_page()

    def _refresh_sync_page(self):
        """从数据库重新加载同步目录统计数据并刷新卡片。"""
        summaries = self.db.dirs.get_sync_summaries(
            config_auto_sync_settings=self.config.get("auto_sync_settings")
        )
        self.sync_page.refresh_all(summaries)

    # ---- 其他系统功能 ----
    def _preview_file(self, file_info):
        from view.preview_flyout import PreviewFlyoutView
        if self._current_preview is not None:
            try:
                self._current_preview.close()
            except RuntimeError:
                pass
            self._current_preview = None
        view = PreviewFlyoutView(file_info, self.task_manager, self.db, self,
                                 cached_media_path=file_info.cached_video_path)
        view.setAttribute(Qt.WA_DeleteOnClose)
        self._current_preview = view
        view.show_centered(self)

    def _on_show_info_bar(self, bar_type: str, title: str, message: str):
        """跨线程槽：在 UI 线程上显示 InfoBar。"""
        if bar_type == "success":
            InfoBar.success(title, message, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
        elif bar_type == "warning":
            InfoBar.warning(title, message, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
        elif bar_type == "error":
            InfoBar.error(title, message, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    def _on_session_expired(self, reason: str):
        """Session 失效回调 — 由 TgWorker 在检测到 UnauthorizedError 时触发。

        清理本地状态，提示用户，并跳转到登录界面。
        """
        logger.warning(f"[MainWindow] Session 失效: {reason}")
        # 先停掉所有 TG 操作
        self.sync_ctrl.stop_sync()
        self.task_manager.stop()
        # 清除登录状态
        self.config["telethon"]["logged_in"] = False
        self.config["telethon"]["user_id"] = 0
        session_file = get_sessions_dir() / "my_account.session"
        if session_file.exists():
            try:
                session_file.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"删除 session 文件失败: {e}")
        self.config_manager.save_now()
        # 提示用户
        InfoBar.warning(
            self.tr("Session Expired"),
            self.tr("Your session was revoked from another device. Please log in again."),
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self,
        )
        self.logout_requested.emit()

    def _do_logout(self):
        self.sync_ctrl.stop_sync()
        self.task_manager.stop()
        self.config["telethon"]["logged_in"] = False
        session_file = get_sessions_dir() / "my_account.session"
        if session_file.exists():
            try:
                session_file.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"删除 session 文件失败: {e}")
        self.config_manager.save_now()
        self.logout_requested.emit()

    def cleanup_and_close(self):
        """销毁托盘图标并真正关闭窗口（不是最小化到托盘）。

        调用此方法而不是 close() 当需要完全销毁窗口时
        （例如退出应用、重新登录时替换主窗口）。
        """
        if hasattr(self, 'tray_icon') and self.tray_icon:
            self.tray_icon.hide()
            self.tray_icon.deleteLater()
            self.tray_icon = None
        self.close()  # closeEvent 会接受，因为 tray_icon 已为 None

    def closeEvent(self, event):
        # 如果托盘图标已被销毁（来自 _real_exit 的真正退出），直接关闭
        if not self.tray_icon:
            event.accept()
            return
        event.ignore()
        self.hide()
        if not self.sync_ctrl.is_running():
            self.sync_ctrl.start_sync()
        self.tray_icon.showMessage(
            tr("CraftCloud"),
            tr("Minimized to tray. Double-click to restore.\nAuto sync resumed."),
            QSystemTrayIcon.Information,
            3000,
        )

    def _setup_tray_icon(self):
        tray = QSystemTrayIcon(self)
        tray.setIcon(app_icon)
        tray.setToolTip(tr("CraftCloud - Running"))
        self.tray_menu = RoundMenu(parent=self)
        a1 = Action(tr("Open Cloud"))
        a1.triggered.connect(self._show_window)
        self.tray_menu.addAction(a1)
        a2 = Action(tr("Exit"))
        a2.triggered.connect(self._real_exit)
        self.tray_menu.addAction(a2)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        return tray

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Context:
            pos = QCursor.pos()
            screen = QApplication.screenAt(pos)
            if not screen:
                screen = QApplication.primaryScreen()
            screen_geo = screen.availableGeometry()
            self.tray_menu.adjustSize()
            menu_width = self.tray_menu.sizeHint().width()
            menu_height = self.tray_menu.sizeHint().height()
            x = pos.x()
            y = pos.y() - menu_height
            if x + menu_width > screen_geo.right():
                x = pos.x() - menu_width
            if x < screen_geo.left():
                x = screen_geo.left()
            if y < screen_geo.top():
                y = pos.y()
            if y + menu_height > screen_geo.bottom():
                y = screen_geo.bottom() - menu_height
            self.tray_menu.exec(QPoint(x, y))
        elif reason == QSystemTrayIcon.DoubleClick:
            self._show_window()

    def _show_window(self):
        self.sync_ctrl.stop_sync()
        self.showNormal()
        self.activateWindow()
        # 从托盘恢复后刷新 UI：同步过程中 DB 已更新，但页面仍是旧数据
        self._refresh_sync_page()
        self._refresh_current_directory()

    def _real_exit(self):
        if hasattr(self, 'tray_icon') and self.tray_icon:
            self.tray_icon.hide()
            self.tray_icon.deleteLater()
            self.tray_icon = None
        # 处理延迟删除事件，确保托盘图标被彻底清理后再退出
        QApplication.processEvents()
        QApplication.instance().quit()
