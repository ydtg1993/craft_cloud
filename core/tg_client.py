"""Session file helper — ensure SQLite WAL mode for Telethon session.

Called once at startup by TgWorkerThread._connect_client() and by
BaseSyncTask._start_client(). Not needed elsewhere — the single shared
Telethon client manages its own connection lifecycle.
"""
import sqlite3
import threading
from core.utils import get_sessions_dir
from loguru import logger

_wal_lock = threading.Lock()


def ensure_session_wal():
    """给 Telethon session SQLite 文件开启 WAL 模式 + busy_timeout。

    在创建 TelegramClient 前调用。通过 PRAGMA 检查当前 journal_mode，
    如果已经是 WAL 则跳过（纯读操作，无锁竞争）。
    仅在需要切换时才加锁执行写操作。

    多线程同时调用安全：读检查无锁；写切换有 threading.Lock 保护。
    """
    session_path = get_sessions_dir() / "my_account.session"
    if not session_path.exists():
        return

    try:
        # 快速读检查：已 WAL 则跳过（无需加锁，纯读）
        conn = sqlite3.connect(str(session_path), timeout=3)
        cur = conn.execute("PRAGMA journal_mode")
        current_mode = (cur.fetchone() or [""])[0].upper()
        if current_mode == "WAL":
            # 再检查 busy_timeout
            cur = conn.execute("PRAGMA busy_timeout")
            current_timeout = (cur.fetchone() or [0])[0]
            conn.close()
            if current_timeout >= 30000:
                return  # 已正确配置，跳过
        else:
            conn.close()

        # 需要写操作：加锁防止并发设置
        with _wal_lock:
            conn = sqlite3.connect(str(session_path), timeout=3)
            cur = conn.execute("PRAGMA journal_mode")
            current_mode = (cur.fetchone() or [""])[0].upper()
            if current_mode != "WAL":
                conn.execute("PRAGMA journal_mode=WAL")
                logger.debug(f"[Session] journal_mode 已切换为 WAL")
            cur = conn.execute("PRAGMA busy_timeout")
            current_timeout = (cur.fetchone() or [0])[0]
            if current_timeout < 30000:
                conn.execute("PRAGMA busy_timeout=30000")
                logger.debug(f"[Session] busy_timeout 已设为 30000ms")
            conn.close()
    except Exception as e:
        logger.debug(f"[Session] WAL 设置失败: {e}")
