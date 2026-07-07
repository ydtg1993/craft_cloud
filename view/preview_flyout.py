from pathlib import Path
import shutil
import tempfile
import threading
from PySide6.QtWidgets import (QVBoxLayout, QLabel, QTextEdit,
                               QPushButton, QHBoxLayout, QWidget, QSlider, QStyle,
                               QSizePolicy)
from PySide6.QtCore import Qt, Signal, QTimer, QSize, QUrl, QObject
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from qfluentwidgets import ProgressRing, ImageLabel, MessageBoxBase, SubtitleLabel, ToolButton, FluentIcon, qconfig, Theme
from qfluentwidgets import theme as qfw_theme
from core.utils import MEDIA_EXTENSIONS

from loguru import logger


def _format_time(ms):
    if ms <= 0:
        return "00:00"
    total_sec = ms // 1000
    minutes = total_sec // 60
    seconds = total_sec % 60
    return f"{minutes:02}:{seconds:02}"


class PreviewFlyoutView(MessageBoxBase):
    progress = Signal(int)
    MAX_PREVIEW_SIZE = 100 * 1024 * 1024  # 100 MB

    def __init__(self, file_info, task_manager, db, parent=None, cached_media_path=None):
        super().__init__(parent)
        # 解决透明闪烁：强制不透明+禁用亚克力
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowOpacity(1.0)
        if hasattr(self, 'setBackgroundEffectEnabled'):
            self.setBackgroundEffectEnabled(False)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WA_StyledBackground, True)

        self.db = db
        self.file_info = file_info
        self.task_manager = task_manager
        self.cached_media_path = cached_media_path
        self.temp_dir = tempfile.mkdtemp(prefix="tgdrive_prev_")
        self.temp_file = None
        self._abort_download = False

        # Qt Multimedia 相关
        self.player = None
        self.audio_output = None
        self.video_widget = None
        self.is_audio = False
        self.is_video = False
        self.media_path = None
        self._player_initialized = False
        self._pending_init_player = False

        # UI 控件引用（延迟创建）
        self.play_pause_btn = None
        self.position_slider = None
        self.time_label = None
        self.volume_slider = None
        self.volume_label = None
        self.title_bar = None
        self.title_label = None
        self.close_btn = None
        self.media_controls = None
        self.audio_icon_label = None
        self._text_edit = None

        # 隐藏底部按钮
        self.yesButton.hide()
        self.cancelButton.hide()
        self.buttonGroup.hide()
        self.viewLayout.setContentsMargins(0, 0, 0, 0)
        self.viewLayout.setSpacing(0)

        self._setup_title_bar()
        self.content_widget = QWidget()
        self.content_widget.setObjectName("PreviewContent")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        self.content_layout.setSpacing(0)

        # 下载进度界面
        self.download_widget = QWidget()
        download_layout = QVBoxLayout(self.download_widget)
        download_layout.setAlignment(Qt.AlignCenter)
        self.progress_ring = ProgressRing()
        self.progress_ring.setFixedSize(100, 100)
        self.progress_ring.setStrokeWidth(8)
        download_layout.addWidget(self.progress_ring, alignment=Qt.AlignCenter)
        self.progress_label = QLabel("0%")
        self.progress_label.setAlignment(Qt.AlignCenter)
        download_layout.addWidget(self.progress_label)
        self.content_layout.addWidget(self.download_widget)
        self.viewLayout.addWidget(self.content_widget)

        self.media_container = None
        self.progress.connect(self._on_progress)
        self.download_worker = None

        # 应用主题颜色
        self._apply_theme_colors()
        qconfig.themeChanged.connect(self._apply_theme_colors)

        self._adjust_window_size()
        self._start_preview()

    def _setup_title_bar(self):
        self.title_bar = QWidget()
        self.title_bar.setFixedHeight(40)
        h_layout = QHBoxLayout(self.title_bar)
        h_layout.setContentsMargins(15, 0, 10, 0)
        name = self.file_info.display_name or self.file_info.original_name
        self.title_label = SubtitleLabel(name)
        h_layout.addWidget(self.title_label, 1)
        self.close_btn = ToolButton(FluentIcon.CLOSE)
        self.close_btn.setIconSize(QSize(12, 12))
        self.close_btn.clicked.connect(self._safe_close)
        h_layout.addWidget(self.close_btn)
        self.viewLayout.addWidget(self.title_bar)

    def _apply_theme_colors(self):
        """根据当前主题（dark/light）刷新所有硬编码颜色。"""
        is_dark = qfw_theme() == Theme.DARK

        # ── 基础色板 ──
        win_bg = "#1E1E1E" if is_dark else "#FFFFFF"
        surface = "#2D2D2D" if is_dark else "#F5F5F5"
        surface2 = "#353535" if is_dark else "#F0F0F0"
        text_primary = "#FFFFFF" if is_dark else "#000000"
        text_secondary = "#CCCCCC" if is_dark else "#333333"
        btn_bg = "#444444" if is_dark else "#E0E0E0"
        btn_hover = "#555555" if is_dark else "#D0D0D0"
        btn_pressed = "#666666" if is_dark else "#C0C0C0"
        slider_groove = "#555555" if is_dark else "#D0D0D0"
        slider_handle = "#0078D4" if is_dark else "#0066ff"
        radius = "8px"

        # ── 窗口 & 内容 ──
        self.setStyleSheet(f"background-color: {win_bg};")
        self.content_widget.setStyleSheet(
            f"#PreviewContent {{ background-color: {win_bg}; "
            f"border-bottom-left-radius: {radius}; border-bottom-right-radius: {radius}; }}")

        # ── 进度标签 ──
        self.download_widget.setStyleSheet("background-color: transparent;")
        self.progress_label.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {text_secondary}; background: transparent;")

        # ── 标题栏 ──
        if self.title_bar:
            self.title_bar.setStyleSheet(
                f"background-color: {surface}; "
                f"border-top-left-radius: {radius}; border-top-right-radius: {radius};")
        if self.title_label:
            self.title_label.setStyleSheet(f"color: {text_primary}; background: transparent;")
        if self.close_btn:
            self.close_btn.setStyleSheet(f"""
                ToolButton {{ background: transparent; border: none; border-radius: 4px; color: {text_primary}; }}
                ToolButton:hover {{ background-color: {btn_hover}; }}
            """)

        # ── 媒体容器 ──
        if self.media_container:
            self.media_container.setStyleSheet(f"background-color: {win_bg};")

        # ── 音频图标 ──
        if self.audio_icon_label:
            self.audio_icon_label.setStyleSheet(
                f"background-color: {surface2}; border-radius: 10px;")

        # ── 播放控制条 ──
        if self.media_controls:
            self.media_controls.setStyleSheet(
                f"background-color: {surface}; border-radius: {radius};")

        # ── 播放按钮 ──
        if self.play_pause_btn:
            self.play_pause_btn.setStyleSheet(f"""
                QPushButton {{ background-color: {btn_bg}; border-radius: 18px; border: none; }}
                QPushButton:hover {{ background-color: {btn_hover}; }}
                QPushButton:pressed {{ background-color: {btn_pressed}; }}
            """)

        # ── 进度滑块 ──
        if self.position_slider:
            self.position_slider.setStyleSheet(f"""
                QSlider::groove:horizontal {{
                    background: {slider_groove}; height: 6px; border-radius: 3px;
                }}
                QSlider::handle:horizontal {{
                    background: {slider_handle}; width: 14px; margin: -5px 0; border-radius: 7px;
                }}
                QSlider::sub-page:horizontal {{
                    background: {slider_handle}; border-radius: 3px;
                }}
            """)

        # ── 时间标签 ──
        if self.time_label:
            self.time_label.setStyleSheet(
                f"color: {text_secondary}; font-size: 13px; background: transparent;")

        # ── 音量滑块 ──
        if self.volume_slider:
            self.volume_slider.setStyleSheet(f"""
                QSlider::groove:horizontal {{
                    background: {slider_groove}; height: 4px; border-radius: 2px;
                }}
                QSlider::handle:horizontal {{
                    background: {slider_handle}; width: 12px; margin: -4px 0; border-radius: 6px;
                }}
                QSlider::sub-page:horizontal {{
                    background: {slider_handle}; border-radius: 2px;
                }}
            """)

        # ── 文本预览 ──
        if self._text_edit:
            self._text_edit.setStyleSheet(
                f"QTextEdit {{ background-color: {win_bg}; color: {text_primary}; "
                f"border: none; padding: 10px; font-family: Consolas, monospace; }}")

        # ── 视频背景保持纯黑 ──
        if self.video_widget:
            self.video_widget.setStyleSheet("background-color: black;")

    def _adjust_window_size(self):
        ext = Path(self.file_info.display_name or self.file_info.original_name).suffix.lower()
        audio_exts = MEDIA_EXTENSIONS['audio']
        video_exts = MEDIA_EXTENSIONS['video']
        image_exts = MEDIA_EXTENSIONS['image']
        if ext in audio_exts:
            self.widget.setFixedSize(480, 220)
        elif ext in video_exts or ext in image_exts:
            self.widget.setFixedSize(800, 700)
        else:
            self.widget.setFixedSize(600, 450)

    def _start_preview(self):
        if self.cached_media_path and Path(self.cached_media_path).exists():
            if Path(self.cached_media_path).stat().st_size > 0:
                self.temp_file = self.cached_media_path
                self._on_download_finished(self.cached_media_path)
                return
        file_size = self.file_info.file_size or 0
        if file_size > self.MAX_PREVIEW_SIZE:
            self._on_download_error(self.tr("File too large (over 100MB) for online preview, please download and play locally."))
            return
        self.progress_ring.setVisible(True)
        self.progress_label.setVisible(True)
        # 使用共享 Telethon 客户端，不再创建独立客户端
        self.download_worker = DownloadWorker(
            self.file_info, self.task_manager, self.temp_dir
        )
        self.download_worker.signals.progress.connect(self._on_progress)
        self.download_worker.signals.finished.connect(self._on_download_finished)
        self.download_worker.signals.error.connect(self._on_download_error)
        t = threading.Thread(target=self.download_worker.run, daemon=True,
                             name="preview-download")
        t.start()

    def _on_progress(self, percent):
        self.progress_ring.setValue(percent)
        self.progress_label.setText(f"{percent}%")

    def _on_download_finished(self, file_path):
        self.temp_file = file_path
        self.download_widget.setVisible(False)
        self.media_container = QWidget()
        self.media_container.setObjectName("MediaContainer")
        media_layout = QVBoxLayout(self.media_container)
        media_layout.setContentsMargins(0, 0, 0, 0)
        media_layout.setSpacing(0)
        ext = Path(file_path).suffix.lower()
        size = self.file_info.file_size or 0
        video_exts = MEDIA_EXTENSIONS['video']
        audio_exts = MEDIA_EXTENSIONS['audio']
        image_exts = MEDIA_EXTENSIONS['image']
        if ext in image_exts:
            self._setup_image_preview(file_path, media_layout)
        elif ext in audio_exts:
            self.is_audio = True
            self._setup_audio_preview(file_path, media_layout)
        elif ext in video_exts:
            self.is_video = True
            self._setup_video_preview(file_path, media_layout)
        else:
            self._setup_text_preview(file_path, size, media_layout)
        self.content_layout.addWidget(self.media_container)

        # 标记等待初始化，等待窗口显示后再初始化播放器（避免QPainter冲突）
        self._pending_init_player = True
        if self.isVisible():
            QTimer.singleShot(50, self._init_qt_player)

    def showEvent(self, event):
        super().showEvent(event)
        if self._pending_init_player:
            QTimer.singleShot(50, self._init_qt_player)
            self._pending_init_player = False

    def _init_qt_player(self):
        """初始化 Qt Multimedia 播放器（确保只执行一次）"""
        if self._player_initialized:
            return
        if not self.media_path or (not self.is_video and not self.is_audio):
            return

        self._player_initialized = True
        self.audio_output = QAudioOutput()
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.audio_output)

        if self.is_video and self.video_widget:
            self.player.setVideoOutput(self.video_widget)

        # 连接信号
        self.player.positionChanged.connect(self._on_position_changed_ui)
        self.player.durationChanged.connect(self._on_duration_changed_ui)
        self.player.playbackStateChanged.connect(self._on_state_changed)
        self.player.errorOccurred.connect(self._on_player_error)

        # 设置媒体源
        self.player.setSource(QUrl.fromLocalFile(self.media_path))

        # 设置音量 70%
        self.audio_output.setVolume(0.7)
        if self.volume_slider:
            self.volume_slider.setValue(70)

        # 开始播放
        self.player.play()

    def _on_position_changed_ui(self, pos_ms):
        if not self.position_slider.isSliderDown():
            self.position_slider.setValue(pos_ms)
        self._update_time_label(pos_ms)

    def _on_duration_changed_ui(self, dur_ms):
        self.position_slider.setRange(0, dur_ms)
        self._update_time_label(self.player.position() if self.player else 0)

    def _on_state_changed(self, state):
        if state == QMediaPlayer.PlayingState:
            self.play_pause_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        else:
            self.play_pause_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

    def _on_player_error(self, error, error_string):
        logger.error(f"Media player error: {error} - {error_string}")
        self._show_error(f"播放错误: {error_string}")

    def _setup_video_preview(self, file_path, layout):
        self.media_path = file_path
        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background-color: black;")
        self.video_widget.setMinimumHeight(400)
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.video_widget, 1)

        control_widget = self._create_media_controls()
        layout.addWidget(control_widget)

    def _setup_audio_preview(self, file_path, layout):
        self.media_path = file_path
        self.audio_icon_label = QLabel()
        self.audio_icon_label.setAlignment(Qt.AlignCenter)
        self.audio_icon_label.setPixmap(self.style().standardIcon(QStyle.SP_MediaVolume).pixmap(64, 64))
        self.audio_icon_label.setFixedHeight(120)
        layout.addWidget(self.audio_icon_label)

        control_widget = self._create_media_controls()
        layout.addWidget(control_widget)

    def _create_media_controls(self):
        self.media_controls = QWidget()
        ctrl_layout = QHBoxLayout(self.media_controls)
        ctrl_layout.setContentsMargins(15, 8, 15, 8)

        self.play_pause_btn = QPushButton()
        self.play_pause_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.play_pause_btn.setFixedSize(36, 36)
        self.play_pause_btn.clicked.connect(self._toggle_playback)
        ctrl_layout.addWidget(self.play_pause_btn)

        self.position_slider = QSlider(Qt.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.setSingleStep(1000)
        self.position_slider.setPageStep(5000)
        self.position_slider.sliderMoved.connect(self._set_position)
        ctrl_layout.addWidget(self.position_slider)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setAlignment(Qt.AlignCenter)
        ctrl_layout.addWidget(self.time_label)

        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setFixedWidth(80)
        self.volume_slider.setToolTip(self.tr("Volume"))
        self.volume_slider.valueChanged.connect(self._set_volume)
        ctrl_layout.addWidget(self.volume_slider)

        self.volume_label = QLabel()
        self.volume_label.setPixmap(self.style().standardIcon(QStyle.SP_MediaVolume).pixmap(16, 16))
        ctrl_layout.addWidget(self.volume_label)

        return self.media_controls

    def _toggle_playback(self):
        if not self.player:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _set_position(self, pos):
        if self.player:
            self.player.setPosition(pos)

    def _set_volume(self, value):
        if self.audio_output:
            self.audio_output.setVolume(value / 100.0)
        if value == 0:
            self.volume_label.setPixmap(self.style().standardIcon(QStyle.SP_MediaVolumeMuted).pixmap(16, 16))
        else:
            self.volume_label.setPixmap(self.style().standardIcon(QStyle.SP_MediaVolume).pixmap(16, 16))

    def _update_time_label(self, pos_ms):
        if not self.player:
            return
        dur_ms = self.player.duration()
        if dur_ms > 0:
            self.time_label.setText(f"{_format_time(pos_ms)} / {_format_time(dur_ms)}")
        else:
            self.time_label.setText(f"{_format_time(pos_ms)} / --:--")

    def _setup_image_preview(self, file_path, layout):
        pixmap = QPixmap(file_path)
        if pixmap.isNull():
            self._show_error(self.tr("Cannot load image"))
            return
        max_width = 760
        max_height = 570
        scaled_pixmap = pixmap.scaled(max_width, max_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_widget = ImageLabel(scaled_pixmap)
        self.image_widget.setFixedSize(scaled_pixmap.size())
        self.image_widget.setBorderRadius(8, 8, 8, 8)
        layout.addWidget(self.image_widget, 1, Qt.AlignCenter)

    def _setup_text_preview(self, file_path, size, layout):
        read_size = min(size, 1024 * 1024) if size else 1024 * 1024
        try:
            with open(file_path, 'rb') as f:
                data = f.read(read_size)
            try:
                text = data.decode('utf-8')
            except UnicodeDecodeError:
                text = data.decode('latin-1')
            text_edit = QTextEdit()
            text_edit.setReadOnly(True)
            text_edit.setObjectName("PreviewTextEdit")
            text_edit.setPlainText(text)
            text_edit.setStyleSheet(
                "QTextEdit { border: none; padding: 10px; font-family: Consolas, monospace; }")
            self._text_edit = text_edit
            layout.addWidget(text_edit)
        except Exception as e:
            self._show_error(f"{self.tr('Cannot read file')}: {str(e)}")

    def _show_error(self, message):
        label = QLabel(message)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: #d32f2f; font-size: 16px; background: transparent;")
        if self.media_container and self.media_container.layout():
            for i in reversed(range(self.media_container.layout().count())):
                widget = self.media_container.layout().itemAt(i).widget()
                if isinstance(widget, QLabel) and widget.styleSheet().startswith("color: #d32f2f"):
                    widget.deleteLater()
            self.media_container.layout().addWidget(label, 0, Qt.AlignCenter)
        else:
            self.content_layout.addWidget(label, 0, Qt.AlignCenter)

    def _on_download_error(self, error_msg):
        self.progress_ring.setVisible(False)
        self.progress_label.setText(f"{self.tr('Download failed')}: {error_msg}")

    def _cleanup_player(self):
        if self.player:
            self.player.stop()
            try:
                self.player.positionChanged.disconnect()
                self.player.durationChanged.disconnect()
                self.player.playbackStateChanged.disconnect()
                self.player.errorOccurred.disconnect()
            except Exception as e:
                from loguru import logger
                logger.debug(f"播放器信号断开失败: {e}")
            self.player.deleteLater()
            self.player = None
        if self.audio_output:
            self.audio_output.deleteLater()
            self.audio_output = None
        if self.video_widget:
            self.video_widget.deleteLater()
            self.video_widget = None
        self._player_initialized = False

    def _safe_close(self):
        if getattr(self, "_closing", False):
            return
        self._closing = True

        if self.download_worker and not self.download_worker._abort_download:
            self.download_worker.abort()

        self._cleanup_player()

        if self.temp_dir and Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

        self.done(0)

    def reject(self):
        self._safe_close()

    def closeEvent(self, event):
        if not getattr(self, "_closing", False):
            self._safe_close()
        event.accept()

    def show_centered(self, parent):
        self.exec()


class DownloadWorkerSignals(QObject):
    progress = Signal(int)
    finished = Signal(str)
    error = Signal(str)


class DownloadWorker:
    """通过共享 Telethon 客户端下载文件用于预览。

    不再创建独立的 Telethon 客户端和 event loop。
    改为提交到 TgWorkerThread 的共享客户端执行，
    通过 threading.Event 等待结果，彻底避免 session 文件争用。
    """

    def __init__(self, file_info, task_manager, temp_dir):
        super().__init__()
        self._file_info = file_info
        self._task_manager = task_manager
        self._temp_dir = temp_dir
        self._file_name = file_info.display_name or file_info.original_name or "file"
        self._message_id = int(file_info.message_id) if isinstance(file_info.message_id, str) else file_info.message_id
        self._chat_id = int(file_info.chat_id) if isinstance(file_info.chat_id, str) else file_info.chat_id
        self._abort_download = False
        self.signals = DownloadWorkerSignals()
        self._done = threading.Event()
        self._result = None
        self._error = None

    def abort(self):
        """设置中止标志以取消下载。"""
        self._abort_download = True

    def run(self):
        """在预览线程中执行。提交到共享 worker，等待结果。"""

        async def _download(client):
            """在 TgWorkerThread 中执行，使用共享 client。"""
            file_path = Path(self._temp_dir) / self._file_name

            # Resolve entity from chat_id
            from telethon.tl.types import PeerChannel
            if str(self._chat_id).startswith('-100'):
                entity = PeerChannel(int(str(self._chat_id).replace('-100', '')))
            else:
                entity = self._chat_id

            result = await client.get_messages(entity, ids=self._message_id)
            msg = result[0] if isinstance(result, list) else result
            if not msg or not msg.media:
                raise Exception("File not found or deleted")

            def _progress_cb(current, total):
                if self._abort_download:
                    raise Exception("Download cancelled")
                if total:
                    self.signals.progress.emit(int(current * 100 / total))

            await client.download_media(msg, file=file_path, progress_callback=_progress_cb)
            return str(file_path)

        def _on_result(path):
            self._result = path
            self._done.set()

        def _on_error(err):
            if not self._abort_download:
                self._error = err
            self._done.set()

        self._task_manager.run_on_client(_download, _on_result, _on_error)

        # 等待共享 worker 完成下载（最长 5 分钟）
        if not self._done.wait(timeout=300):
            self._error = "Download timeout"
            self._abort_download = True

        if self._result is not None:
            self.signals.finished.emit(self._result)
        elif self._error is not None:
            self.signals.error.emit(self._error)