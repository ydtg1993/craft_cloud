"""核心基础设施工具函数。

纯系统工具：路径、时间、格式化。不含业务逻辑或 UI 代码。
"""
import sys
import os
import atexit
from pathlib import Path
from datetime import datetime, timezone, timedelta
from loguru import logger
from core.translator import tr

# ── 单实例锁 ─────────────────────────────────────────────────
_instance_lock_path = None


def _is_process_running(pid: int) -> bool:
    """检查指定 PID 的进程是否仍在运行（跨平台）。"""
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


def acquire_single_instance_lock() -> bool:
    """获取单实例锁，确保只有一个程序实例在运行。

    使用 PID 锁文件方式：启动时写入当前 PID，启动前检查已有 PID
    是否仍在运行。进程崩溃时锁文件自动变为过期，下次启动会清理。

    Returns:
        True:  成功获取锁，当前是唯一实例
        False: 已有实例在运行，应退出
    """
    global _instance_lock_path

    if getattr(sys, 'frozen', False):
        data_dir = Path(sys.executable).parent / "data"
    else:
        data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    lock_path = data_dir / ".instance.lock"

    if lock_path.exists():
        try:
            with open(lock_path, 'r') as f:
                old_pid = int(f.read().strip())
            if _is_process_running(old_pid):
                return False
        except (ValueError, OSError):
            pass  # 锁文件损坏，覆盖它

        # 清理过期锁
        try:
            lock_path.unlink()
        except OSError:
            pass

    try:
        with open(lock_path, 'w') as f:
            f.write(str(os.getpid()))
        _instance_lock_path = lock_path
        atexit.register(_release_single_instance_lock)
        return True
    except OSError:
        return False


def _release_single_instance_lock():
    """退出时清理锁文件。"""
    global _instance_lock_path
    if _instance_lock_path and _instance_lock_path.exists():
        try:
            _instance_lock_path.unlink()
        except OSError:
            pass
        _instance_lock_path = None



def _init_logging():
    """Configure loguru — console + rotating file handlers."""
    logger.remove()

    # PyInstaller console=False 时 sys.stderr 可能为 None
    if sys.stderr is not None:
        logger.add(
            sys.stderr,
            level="INFO",
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
            filter=lambda record: "telethon" not in record["extra"].get("name", ""),
        )

    if getattr(sys, 'frozen', False):
        log_dir = Path(sys.executable).parent / "data" / "logs"
    else:
        log_dir = Path(__file__).resolve().parent.parent / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.add(
        log_dir / "app_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        rotation="00:00",
        retention="7 days",
        encoding="utf-8",
        compression="gz",
    )

_init_logging()


def format_file_size(size: int) -> str:
    """统一的文件大小格式化"""
    if size is None:
        return tr("Unknown")
    try:
        size = float(size)
    except (ValueError, TypeError):
        return str(size)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def get_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def build_path_string(path_parts: list) -> str:
    """将 [(id, name), ...] 转换为 /dir1/dir2 格式"""
    root_name = tr("Root")
    parts = [name for _, name in path_parts if name != root_name]
    return "/" + "/".join(parts) if parts else "/"


def beijing_now():
    return datetime.now(timezone(timedelta(hours=8)))


def beijing_now_str():
    return beijing_now().strftime("%Y-%m-%d %H:%M:%S")


def beijing_today_str():
    return beijing_now().strftime("%Y-%m-%d")


def resource_path(relative_path: str) -> Path:
    if getattr(sys, 'frozen', False):
        base = Path(sys._MEIPASS) / 'resources'
    else:
        base = Path(__file__).resolve().parent.parent / "resources"
    return base / relative_path


def get_sessions_dir() -> Path:
    if getattr(sys, 'frozen', False):
        p = Path(sys.executable).parent / "sessions"
    else:
        p = Path(__file__).resolve().parent.parent / "sessions"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_db_path() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent / "data" / "craftfiles.db"
    return Path("data/craftfiles.db")


def get_cache_dir() -> Path:
    if getattr(sys, 'frozen', False):
        p = Path(sys.executable).parent / "data" / "cache"
    else:
        p = Path(__file__).resolve().parent.parent / "data" / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_ffmpeg_path() -> str:
    """返回 ffmpeg 可执行文件路径。

    优先返回 bundled 版本（scripts/ffmpeg.exe），找不到则回退到系统 PATH。
    打包后 PyInstaller COLLECT 会把 scripts/ffmpeg.exe 放到 dist 根目录的 scripts/ 下。
    兼容不同 PyInstaller 版本 _MEIPASS 指向的差异：
    - 旧版 _MEIPASS 指向 exe 所在目录
    - 新版 _MEIPASS 可能指向 _internal 子目录
    因此按优先级尝试多个 candidate 路径。
    """
    if getattr(sys, 'frozen', False):
        candidates = [
            Path(sys._MEIPASS) / "scripts" / "ffmpeg.exe",
            Path(sys.executable).parent / "scripts" / "ffmpeg.exe",
        ]
    else:
        candidates = [
            Path(__file__).resolve().parent.parent / "scripts" / "ffmpeg.exe",
        ]
    for bundled in candidates:
        if bundled.is_file():
            return str(bundled)
    return "ffmpeg"  # 回退到系统 PATH


MEDIA_EXTENSIONS = {
    'video': {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv'},
    'audio': {'.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a'},
    'image': {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'},
}


def get_media_extensions():
    """返回媒体文件扩展名映射（向后兼容包装器）。"""
    return MEDIA_EXTENSIONS


def is_media_file(filename):
    ext = Path(filename).suffix.lower()
    return ext in MEDIA_EXTENSIONS['video'] or ext in MEDIA_EXTENSIONS['audio'] or ext in MEDIA_EXTENSIONS['image']
