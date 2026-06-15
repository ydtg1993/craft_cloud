"""共享数据传输对象（DTO），可被所有层安全导入。"""
from collections import namedtuple

# ═══════════════════════════════════════════════════════════════
# 同步状态常量
# ═══════════════════════════════════════════════════════════════

SYNC_PENDING = 0   # 等待中 / 同步中 / 已取消
SYNC_SUCCESS = 1   # 同步完成
SYNC_FAILED = 2    # 同步失败

SYNC_STATUS_TEXT = {
    SYNC_PENDING: "Pending",
    SYNC_SUCCESS: "Success",
    SYNC_FAILED: "Failed",
}


def sync_status_display(status: int) -> str:
    """将状态码转为显示文本。"""
    return SYNC_STATUS_TEXT.get(status, "Pending")


# ═══════════════════════════════════════════════════════════════
# Namedtuples / DTOs
# ═══════════════════════════════════════════════════════════════

# 用于 QIconView 的 UserRole 存储
IconViewItemData = namedtuple('IconViewItemData', ['id', 'is_dir', 'is_sync_root'])

# 用于 QTableView 的 UserRole 存储
TableItemData = namedtuple('TableItemData', ['id', 'is_dir'])

# 用于搜索结果对话框
SearchItemData = namedtuple('SearchItemData', ['id', 'dir_id'])

# 同步文件夹摘要 — 每个 is_sync=1 的根目录一个实例
SyncFolderSummary = namedtuple('SyncFolderSummary', [
    'dir_id',           # int: Directory.id
    'dir_name',         # str: 目录名
    'local_path',       # str: 本地文件夹路径
    'channel_id',       # str|None: TG 频道 ID
    'channel_name',     # str: TG 频道名（人类可读）
    'total_files',      # int: 该目录下所有文件数（含子目录）
    'synced_files',     # int: 已同步的文件数（is_sync=1）
    'total_size',       # int: 总文件大小（bytes）
    'synced_size',      # int: 已同步文件大小（bytes）
    'status',           # int: 同步状态 (0=pending, 1=success, 2=failed)
    'last_sync_time',   # str|None: 上次同步时间
    'error_message',    # str|None: 错误信息
])
