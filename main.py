import sys

# ═══════════════════════════════════════════════════════════════
# pkg_resources 桩 — setuptools >= 82 移除了 pkg_resources，
# 但 apscheduler 在 import 时需要它。必须在 apscheduler 被
# 首次导入之前完成注入。
# ═══════════════════════════════════════════════════════════════
try:
    import pkg_resources
except ModuleNotFoundError:
    from core.pkg_resources_stub import get_distribution  # noqa: F401 — side-effect only

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QApplication, QMessageBox
from qfluentwidgets import FluentTranslator, setTheme, Theme
from loguru import logger

from core.config_manager import ConfigManager
from core.translator import AppTranslator
from core.utils import acquire_single_instance_lock


def main():
    # ── 单实例检查 ───────────────────────────────────────────
    if not acquire_single_instance_lock():
        # 已有实例在运行，显示原生提示框（不依赖 QApplication）
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                "CraftCloud 已在运行中，请检查系统托盘。",
                "CraftCloud",
                0x40,  # MB_ICONINFORMATION
            )
        else:
            print("CraftCloud is already running.")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Install QFluentWidgets built-in translator (follows system locale by default)
    fluent_translator = FluentTranslator()
    app.installTranslator(fluent_translator)

    # Install app translator based on saved language
    config_mgr = ConfigManager()
    lang = config_mgr.get_language()
    _LANG_MAP = {
        "zh": QLocale.Chinese,
        "en": QLocale.English,
        "fr": QLocale.French,
        "de": QLocale.German,
        "ru": QLocale.Russian,
        "ko": QLocale.Korean,
    }
    locale = QLocale(_LANG_MAP.get(lang, QLocale.English))
    app_translator = AppTranslator(locale)
    app.installTranslator(app_translator)

    # 应用保存的主题设置
    saved_theme = config_mgr.config.get("theme", "light")
    setTheme(Theme.DARK if saved_theme == "dark" else Theme.LIGHT)

    # 强制处理一次事件，确保 qfluentwidgets 内部完全初始化
    app.processEvents()

    main_window = None

    def show_main_window():
        nonlocal main_window
        from view.main_window import MainWindow
        if main_window is not None:
            main_window.close()

        main_window = MainWindow(config_mgr)
        main_window.logout_requested.connect(show_login_window)
        main_window.showNormal()
        main_window.raise_()
        main_window.activateWindow()


    def show_login_window():
        nonlocal main_window
        from view.login_window import LoginWindow
        if main_window is not None:
            main_window.close()
            main_window = None
        login = LoginWindow(config_mgr)
        if login.exec() == LoginWindow.Accepted:
            show_main_window()
        else:
            sys.exit(0)

    if config_mgr.has_valid_session():
        show_main_window()
    else:
        show_login_window()

    exit_code = app.exec()
    config_mgr.flush()  # Ensure any deferred config saves are written
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
