"""核心基础设施工具函数。

纯系统工具：路径、时间、格式化。不含业务逻辑或 UI 代码。
"""
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from loguru import logger
from core.translator import tr



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
