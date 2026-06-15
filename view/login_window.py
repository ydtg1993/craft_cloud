"""Login window — Telethon QR code login, ultra-minimalist design."""
import asyncio
import io
import sys
import threading
import traceback
from pathlib import Path

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QApplication, QWidget
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QIcon, QPixmap, QFont, QColor, QPalette
from qfluentwidgets import (
    LineEdit,
    BodyLabel,
    InfoBar,
    InfoBarPosition,
    FluentIcon,
    ImageLabel,
    SubtitleLabel,
    PrimaryPushButton,
    IconWidget,
    ElevatedCardWidget,
)

from core.config_manager import ConfigManager
from core.telethon_login import connect_client, export_qr_login, wait_qr_login
from core.utils import resource_path, get_sessions_dir
from loguru import logger

WORK_DIR = str(get_sessions_dir())
CONNECT_TIMEOUT = 15


class LoginWindow(QDialog):
    """QR code login using Telethon — Ultra-Minimalist Style."""

    login_success = Signal()
    login_error = Signal(str)
    _qr_image_ready = Signal(bytes)
    _qr_url_ready = Signal(str)

    def __init__(self, config_manager: ConfigManager):
        super().__init__()
        self.config_manager = config_manager
        self.config = config_manager.config
        telethon_cfg = config_manager.config.get("telethon", {})

        # 优先从 users 表读取当前凭证，fallback 到 config（兼容旧配置迁移）
        api_id_val, api_hash_val = self._load_api_credentials(telethon_cfg)

        # 设置窗口图标
        icon_path = resource_path("tc.png")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        else:
            # 如果 tc.png 不存在，尝试 tc.ico
            ico_path = resource_path("tc.ico")
            if ico_path.exists():
                self.setWindowIcon(QIcon(str(ico_path)))
            else:
                logger.warning("Window icon not found")

        self.setWindowTitle(self.tr("Telegram Login"))
        # 优化窗体比例，高度略微增加以容纳大按钮和内部指南
        self.resize(360, 480)

        # 主布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)

        # ── 标题栏 (简约 Logo + 标题) ───────────────────────
        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        self.logo_label = ImageLabel()
        logo_path = resource_path("tc.png")
        if logo_path.exists():
            pixmap = QPixmap(str(logo_path))
            self.logo_label.setPixmap(pixmap.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.logo_label.setFixedSize(48, 48)
        header_layout.addWidget(self.logo_label)

        title = SubtitleLabel(self.tr("Telegram Login"))
        title.setFont(QFont(title.font().family(), 18, QFont.DemiBold))
        header_layout.addWidget(title)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # ── 输入区域 ────────────────────────────────────────
        self.api_id_edit = LineEdit()
        self.api_id_edit.setPlaceholderText(self.tr("API ID"))
        self.api_id_edit.setText(str(api_id_val))
        self.api_id_edit.setFixedHeight(36)
        layout.addWidget(self.api_id_edit)

        self.api_hash_edit = LineEdit()
        self.api_hash_edit.setPlaceholderText(self.tr("API Hash"))
        self.api_hash_edit.setEchoMode(LineEdit.Password)
        self.api_hash_edit.setText(api_hash_val)
        self.api_hash_edit.setFixedHeight(36)
        layout.addWidget(self.api_hash_edit)

        # ── 二维码容器 (内置扫码指南) ───────────────────────
        self.qr_container = ElevatedCardWidget()
        self.qr_container.setFixedSize(300, 200)

        container_layout = QVBoxLayout(self.qr_container)
        container_layout.setAlignment(Qt.AlignCenter)
        container_layout.setContentsMargins(8, 8, 8, 8)
        container_layout.setSpacing(8)

        # 占位图标
        self.qr_placeholder_icon = IconWidget(FluentIcon.QRCODE)
        self.qr_placeholder_icon.setFixedSize(44, 44)

        # 🌟 整合进占位区的扫码路径说明
        self.qr_placeholder_text = BodyLabel(
            self.tr("Scan via Telegram app:\nSettings - Devices - Link Desktop")
        )
        self.qr_placeholder_text.setAlignment(Qt.AlignCenter)
        self.qr_placeholder_text.setWordWrap(True)
        self.qr_placeholder_text.setFont(QFont(self.qr_placeholder_text.font().family(), 10))

        # 真正的二维码图片控件
        self.qr_image_label = ImageLabel()
        self.qr_image_label.setFixedSize(176, 176)
        self.qr_image_label.setAlignment(Qt.AlignCenter)
        self.qr_image_label.hide()

        container_layout.addWidget(self.qr_placeholder_icon, 0, Qt.AlignCenter)
        container_layout.addWidget(self.qr_placeholder_text, 0, Qt.AlignCenter)
        container_layout.addWidget(self.qr_image_label, 0, Qt.AlignCenter)

        layout.addWidget(self.qr_container, 0, Qt.AlignCenter)

        # ── 大操作按钮 (使用 qfluentwidgets 的 PrimaryPushButton) ──
        self.generate_btn = PrimaryPushButton(FluentIcon.QRCODE, self.tr("Generate QR Code"))
        self.generate_btn.setFixedSize(295, 40)
        self.generate_btn.clicked.connect(self._generate_qr)
        layout.addWidget(self.generate_btn, 0, Qt.AlignCenter)

        # ── 状态提示栏 ──────────────────────────────────────
        self.qr_status = BodyLabel(self.tr("Click the button above to start"))
        self.qr_status.setAlignment(Qt.AlignCenter)
        self._set_status_color("#A3A3A3")
        layout.addWidget(self.qr_status)

        # 后端状态初始化
        self._client = None
        self._qr_login_obj = None
        self._abort_event = threading.Event()

        self.login_success.connect(self._on_login_success)
        self.login_error.connect(self._on_login_error)
        self._qr_image_ready.connect(self._on_qr_image_ready)
        self._qr_url_ready.connect(self._on_qr_url_ready)


    # ═══════════════════════════════════════════════════════════
    #  辅助方法
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _load_api_credentials(telethon_cfg: dict) -> tuple:
        """加载 API 凭证：优先从 users 表，fallback 到旧 config。"""
        # 1. 尝试从 users 表读取当前活跃用户
        try:
            from core.db_manager import DBManager
            db = DBManager()
            creds = db.users.get_active_credentials()
            if creds:
                return str(creds["api_id"]), creds["api_hash"]
        except Exception:
            pass

        # 2. Fallback: 旧 config 中的 api_id/api_hash（迁移过渡期）
        old_api_id = telethon_cfg.get("api_id", "")
        old_api_hash = telethon_cfg.get("api_hash", "")
        if old_api_id and old_api_hash:
            return str(old_api_id), old_api_hash

        return "", ""

    def _set_status_color(self, hex_color: str):
        """用 QPalette 设置状态标签颜色，避免 setStyleSheet 触发 CSS 引擎重绘。"""
        pal = self.qr_status.palette()
        pal.setColor(QPalette.WindowText, QColor(hex_color))
        self.qr_status.setPalette(pal)

    # ═══════════════════════════════════════════════════════════
    #  业务逻辑与界面状态切换
    # ═══════════════════════════════════════════════════════════

    def _generate_qr(self):
        api_id = self.api_id_edit.text().strip()
        api_hash = self.api_hash_edit.text().strip()

        if not (api_id and api_hash):
            InfoBar.warning(self.tr("Warning"), self.tr("Fields cannot be empty"), position=InfoBarPosition.TOP,duration=2000, parent=self).setMaximumWidth(280)
            return

        try:
            api_id_int = int(api_id)
        except ValueError:
            InfoBar.error(self.tr("Error"), self.tr("API ID must be an integer"), position=InfoBarPosition.TOP,duration=2000, parent=self).setMaximumWidth(280)
            return

        self._abort_event.set()
        if self._client:
            try: asyncio.run(self._client.disconnect())
            except Exception: pass
            self._client = None
        self._qr_login_obj = None

        session_path = Path(WORK_DIR, "my_account.session")
        if session_path.exists():
            try: session_path.unlink()
            except OSError: pass

        self._abort_event.clear()
        self.generate_btn.setEnabled(False)
        self.generate_btn.setText(self.tr("Connecting..."))
        self.qr_status.setText(self.tr("Connecting to Telegram server..."))

        # 复位容器至"等待生成"状态
        self.qr_image_label.clear()
        self.qr_image_label.hide()
        self.qr_placeholder_icon.show()
        self.qr_placeholder_text.show()

        def _bg_task():
            # Windows 下 ProactorEventLoop 在 PyInstaller 打包后可能异常，
            # 统一使用 SelectorEventLoop（与 tg_worker.py 保持一致）
            if sys.platform == "win32":
                try:
                    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
                except RuntimeError:
                    pass
            try:
                asyncio.run(self._connect_and_generate_qr(api_id_int, api_hash))
            except asyncio.TimeoutError:
                if not self._abort_event.is_set(): self.login_error.emit("Timeout. Check your network.")
            except Exception as e:
                logger.error(traceback.format_exc())
                if not self._abort_event.is_set(): self.login_error.emit(str(e))

        threading.Thread(target=_bg_task, daemon=True).start()

    async def _connect_and_generate_qr(self, api_id: int, api_hash: str):
        if self._abort_event.is_set(): return
        self._client = await connect_client(api_id, api_hash, cleanup_session=False, connect_timeout=CONNECT_TIMEOUT)

        if self._abort_event.is_set():
            await self._client.disconnect()
            return

        self._qr_login_obj = await export_qr_login(self._client)
        await self._show_qr_code(self._qr_login_obj.url)
        self._login_user_info = await wait_qr_login(self._qr_login_obj, timeout=120)

        if self._abort_event.is_set(): return
        await self._client.disconnect()
        self._client = None
        self.login_success.emit()

    async def _show_qr_code(self, qr_url: str):
        try:
            import qrcode
            qr = qrcode.QRCode(version=3, box_size=6, border=1)
            qr.add_data(qr_url)
            qr.make(fit=True)
            qr_image = qr.make_image(fill_color="black", back_color="white")

            buffer = io.BytesIO()
            qr_image.save(buffer, format='PNG')
            self._qr_image_ready.emit(buffer.getvalue())
        except ImportError:
            self._qr_url_ready.emit(qr_url)

    def _on_qr_image_ready(self, png_bytes: bytes):
        pixmap = QPixmap()
        pixmap.loadFromData(png_bytes)
        scaled = pixmap.scaled(176, 176, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        # 🌟 成功获取二维码后，隐藏图标和路径指南，清空出视野
        self.qr_placeholder_icon.hide()
        self.qr_placeholder_text.hide()

        self.qr_image_label.show()
        self.qr_image_label.setPixmap(scaled)

        self.qr_status.setText(self.tr("Please scan the QR code to log in"))
        self._set_status_color("#0078D4")
        self.generate_btn.setText(self.tr("Refresh QR Code"))
        self.generate_btn.setEnabled(True)

    def _on_qr_url_ready(self, qr_url: str):
        self.qr_status.setText(qr_url)
        self.generate_btn.setText(self.tr("Refresh QR Code"))
        self.generate_btn.setEnabled(True)

    def closeEvent(self, event):
        self._abort_event.set()
        if self._client:
            try: asyncio.run(self._client.disconnect())
            except Exception: pass
        event.accept()
        QApplication.instance().quit()

    def _on_login_success(self):
        api_id = int(self.api_id_edit.text().strip())
        api_hash = self.api_hash_edit.text().strip()
        user_info = getattr(self, '_login_user_info', None)

        # 异步写入用户信息到数据库，然后回写 user_id 到 config
        def _save_and_update_config():
            try:
                from core.db_manager import DBManager
                db = DBManager()
                user_pk = db.users.upsert_user(
                    tg_id=user_info['tg_id'],
                    api_id=api_id,
                    api_hash=api_hash,
                    phone=user_info.get('phone', ''),
                    username=user_info.get('username', ''),
                )
                # 更新 config: 存 user_id，清除旧的 api_id/api_hash
                self.config["telethon"] = {
                    "user_id": user_pk,
                    "logged_in": True,
                }
                self.config_manager.save()
                logger.info(f"[Login] 用户信息已存入: {user_info['username']} (pk={user_pk})")
            except Exception as e:
                logger.error(f"[Login] 用户信息写入失败: {e}")

        if user_info:
            threading.Thread(target=_save_and_update_config, daemon=True).start()
        else:
            # 无用户信息时仍保存 logged_in 标志（异常路径）
            self.config["telethon"] = {"user_id": 0, "logged_in": True}
            self.config_manager.save()

        InfoBar.success(self.tr("Success"), self.tr("Login successful!"), position=InfoBarPosition.TOP, parent=self)
        QTimer.singleShot(1000, self.accept)

    def _on_login_error(self, error_msg=""):
        InfoBar.error(self.tr("Login failed"), error_msg[:100],orient=Qt.Vertical, position=InfoBarPosition.TOP,duration=2000, parent=self)
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText(self.tr("Generate QR Code"))
        self.qr_status.setText(self.tr("Failed. Please try again."))
        self._set_status_color("#FF4D4F")

        self.qr_image_label.clear()
        self.qr_image_label.hide()
        self.qr_placeholder_icon.show()
        self.qr_placeholder_text.show()