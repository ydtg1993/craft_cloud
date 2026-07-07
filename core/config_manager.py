"""Configuration manager — Pydantic-validated YAML config with dict-compatible API."""
import sys
from pathlib import Path
import yaml
from pydantic import BaseModel, Field
from PySide6.QtCore import QTimer
from loguru import logger
from core.utils import get_sessions_dir


# ═══════════════════════════════════════════════════════════════
# Pydantic Config Models
# ═══════════════════════════════════════════════════════════════


class TelethonConfig(BaseModel):
    user_id: int = 0                    # users 表主键，用于查询当前激活用户的凭证
    logged_in: bool = False


class UploadLimitConfig(BaseModel):
    enabled: bool = True
    max_daily_size_gb: float = 200.0
    max_daily_files: int = 800
    max_single_file_size_gb: float = 1.8
    reset_hour: int = 0


class SyncFolderConfig(BaseModel):
    interval_type: str = "hourly"
    interval_value: int = 1
    target_dir_id: int = 0
    channel_name: str = ""


class AutoSyncConfig(BaseModel):
    enabled: bool = False
    upload_interval: int = 15  # seconds between file uploads (1-60)
    folders: dict[str, SyncFolderConfig] = Field(default_factory=dict)


class AppConfig(BaseModel):
    """Pydantic model for the full application config."""
    telethon: TelethonConfig = Field(default_factory=TelethonConfig)
    download_path: str = str(Path.home() / "Downloads")
    language: str = "en"
    theme: str = "light"
    view_mode: str = "icon"
    clipboard_enabled: bool = True
    upload_retry_times: int = 3
    max_concurrent_uploads: int = 3
    upload_limit_settings: UploadLimitConfig = Field(default_factory=UploadLimitConfig)
    auto_sync_settings: AutoSyncConfig = Field(default_factory=AutoSyncConfig)


# ═══════════════════════════════════════════════════════════════
# ConfigManager (dict-compatible API over Pydantic + YAML)
# ═══════════════════════════════════════════════════════════════

class ConfigManager:
    """Configuration manager using Pydantic validation + YAML storage.

    Backward-compatible: ``self.config`` is a plain dict for existing callers.

    save() uses a 500ms debounce timer to coalesce rapid calls from UI
    event handlers. For critical paths (logout, session expiry), use
    save_now() which writes immediately and blocks — acceptable because
    those paths already transition away from the main window.
    """

    # Debounce interval for deferred saves (ms)
    _SAVE_DEBOUNCE_MS = 500

    def __init__(self, config_path: str = "config/config.yaml"):
        if getattr(sys, 'frozen', False):
            config_path = str(Path(sys.executable).parent / "config" / "config.yaml")
        self.config_path = config_path
        self.config = self.load()
        self._migrate_old_config()
        # Debounce timer: coalesces rapid save() calls into one disk write
        self._save_timer = QTimer()
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(self._SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self._do_save)

    def load(self) -> dict:
        """Load config from YAML, validate with Pydantic, return as dict."""
        if not Path(self.config_path).exists():
            logger.info(f"配置文件不存在，使用默认配置: {self.config_path}")
            return self._default_dict()
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            validated = AppConfig(**data)
            logger.info(f"配置文件已加载: {self.config_path}")
            return validated.model_dump()
        except Exception as e:
            logger.warning(f"无法读取配置文件 {self.config_path}: {e}，使用默认配置")
            return self._default_dict()

    def save(self) -> None:
        """Schedule a deferred save on the main thread, or save immediately if
        called from a background thread (where QTimer cannot fire).

        On the main thread: coalesces rapid calls from UI event handlers
        (set_view_mode, set_language, update_sync_folder, etc.) via a
        500ms debounce timer. Returns immediately — the actual I/O
        happens asynchronously on the Qt event loop.

        On a background thread: writes immediately (QTimer needs an
        event loop, which background threads don't have).

        For critical main-thread paths that need an immediate write
        (logout, session expiry), use save_now().
        """
        if self._is_main_thread():
            self._save_timer.start()
        else:
            # Background thread (e.g. sync tasks): QTimer won't fire here
            self._do_save()

    def save_now(self) -> None:
        """Immediately validate and persist config to YAML (blocking).

        Use only for critical paths where data loss is unacceptable and
        the blocking I/O is acceptable (e.g. before logout or exit).
        """
        self._save_timer.stop()  # Cancel any pending deferred save
        self._do_save()

    def flush(self) -> None:
        """Force any pending deferred save to disk. Call before app exit."""
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._do_save()

    @staticmethod
    def _is_main_thread() -> bool:
        import threading
        return threading.current_thread() is threading.main_thread()

    def _do_save(self) -> None:
        """Internal: validate and persist config to YAML."""
        try:
            validated = AppConfig(**self.config)
            data = validated.model_dump()
            Path(self.config_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        except Exception as e:
            logger.error(f"无法保存配置文件: {e}")

    @staticmethod
    def _default_dict() -> dict:
        return AppConfig().model_dump()

    def _migrate_old_config(self) -> None:
        """Migrate legacy config keys, then remove them to avoid repeat migration."""

    def _ensure_keys_exist(self) -> None:
        defaults = self._default_dict()
        for key in ("upload_limit_settings", "auto_sync_settings"):
            if key not in self.config:
                self.config[key] = defaults[key]

    # ── Public Helpers ──────────────────────────────────────────

    def has_valid_session(self) -> bool:
        telethon = self.config.get("telethon", {})
        if not telethon.get("logged_in"):
            return False
        if not telethon.get("user_id"):
            return False
        return (get_sessions_dir() / "my_account.session").exists()

    def get_language(self) -> str:
        return self.config.get("language", "zh")

    def set_language(self, lang: str) -> None:
        self.config["language"] = lang
        self.save()

    def get_view_mode(self) -> str:
        return self.config.get("view_mode", "list")

    def set_view_mode(self, mode: str) -> None:
        self.config["view_mode"] = mode
        self.save()

    def get_upload_limit_settings(self) -> dict:
        return self.config.get("upload_limit_settings", {})

    def get_auto_sync_settings(self) -> dict:
        return self.config.get("auto_sync_settings", {})

    def update_sync_folder(self, folder_path: str, cfg: dict) -> None:
        self.config.setdefault("auto_sync_settings", {})
        self.config["auto_sync_settings"].setdefault("folders", {})
        self.config["auto_sync_settings"]["folders"][folder_path] = cfg
        self.save()

    def remove_sync_folder(self, folder_path: str) -> None:
        if "auto_sync_settings" in self.config:
            self.config["auto_sync_settings"].get("folders", {}).pop(folder_path, None)
            self.save()
