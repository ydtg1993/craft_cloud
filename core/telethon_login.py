import asyncio
import base64
from pathlib import Path
from telethon import TelegramClient
from core.utils import get_sessions_dir
from loguru import logger

WORK_DIR = str(get_sessions_dir())
SESSION_FILE = Path(WORK_DIR) / "my_account.session"

# Connection retry settings
MAX_CONNECT_RETRIES = 3
RETRY_DELAY = 3  # seconds between retries


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════

def _cleanup_stale_session():
    """Remove stale session file to ensure a clean connection."""
    if SESSION_FILE.exists():
        try:
            SESSION_FILE.unlink()
            logger.info("已删除残留的 session 文件")
        except OSError as e:
            logger.warning(f"无法删除 session 文件: {e}")


# ═══════════════════════════════════════════════════════════════
#  QR code login
# ═══════════════════════════════════════════════════════════════

def generate_qr_url(token: bytes) -> str:
    """Generate tg://login URL from raw token bytes."""
    token_b64 = base64.urlsafe_b64encode(token).decode().rstrip("=")
    return f"tg://login?token={token_b64}"


async def connect_client(api_id: int, api_hash: str, cleanup_session: bool = False,
                        connect_timeout: int = 15) -> TelegramClient:
    """Connect a bare Telethon client with per-attempt timeout and retry.

    Args:
        cleanup_session: If True, delete stale session file before connecting.
        connect_timeout: Per-attempt timeout in seconds (default 15).
    """
    if cleanup_session:
        _cleanup_stale_session()

    last_error = None
    for attempt in range(1, MAX_CONNECT_RETRIES + 1):
        client = TelegramClient(
            str(SESSION_FILE),
            api_id,
            api_hash,
        )
        try:
            logger.info(f"连接 Telegram (第 {attempt}/{MAX_CONNECT_RETRIES} 次)...")
            await asyncio.wait_for(client.connect(), timeout=connect_timeout)
            logger.info("Telegram 连接成功")
            return client
        except asyncio.TimeoutError:
            last_error = f"连接超时 ({connect_timeout}秒)"
            logger.warning(f"连接超时 (第 {attempt}/{MAX_CONNECT_RETRIES} 次)")
        except Exception as e:
            last_error = e
            logger.warning(f"连接失败 (第 {attempt}/{MAX_CONNECT_RETRIES} 次): {e}")

        # Clean up failed client
        try:
            await client.disconnect()
        except Exception:
            pass

        if attempt < MAX_CONNECT_RETRIES:
            logger.info(f"等待 {RETRY_DELAY}s 后重试...")
            await asyncio.sleep(RETRY_DELAY)

    raise ConnectionError(f"无法连接到 Telegram（已重试 {MAX_CONNECT_RETRIES} 次）: {last_error}")


# ═══════════════════════════════════════════════════════════════
#  Telethon native QR login export
# ═══════════════════════════════════════════════════════════════

async def export_qr_login(client: TelegramClient):
    """Initiate QR login via Telethon's native qr_login() method.

    Returns:
        QrLogin object with .url property for the QR code URL,
        and .wait() method to await user scanning.
    """
    logger.info("正在生成 QR 登录令牌...")
    qr_login = await client.qr_login()
    logger.info(f"QR login URL generated")
    return qr_login


async def wait_qr_login(qr_login, timeout: int = 120) -> dict:
    """Wait for user to scan QR code and confirm login.

    Args:
        qr_login: The QrLogin object from export_qr_login().
        timeout: Maximum wait time in seconds.

    Returns:
        dict with keys: tg_id, username, phone, first_name, last_name.
    """
    logger.info("等待扫码登录...")
    try:
        user = await asyncio.wait_for(qr_login.wait(), timeout=timeout)
        username = getattr(user, 'username', '') or ''
        first = getattr(user, 'first_name', '') or ''
        last = getattr(user, 'last_name', '') or ''
        display_name = (first + ' ' + last).strip() or username or str(user.id)
        user_info = {
            'tg_id': user.id,
            'username': display_name,
            'phone': getattr(user, 'phone', '') or '',
        }
        logger.info(f"扫码登录成功 ✅ — 用户: {display_name} (tg_id={user.id})")
        return user_info
    except asyncio.TimeoutError:
        logger.warning("扫码登录超时")
        raise Exception("扫码超时，请重试")
