"""Cache manager — diskcache-based caching for thumbnails, metadata, and API results."""
from pathlib import Path
from diskcache import Cache
from loguru import logger
from core.utils import get_cache_dir


def remove_media_cache_files(thumb_path: str | None, clip_path: str | None):
    """删除缩略图/预览切片等磁盘文件，并清理 diskcache 映射。

    供 FileRepository.delete_file 和 DirectoryRepository.delete_directory_recursive 共用。
    """
    if not thumb_path and not clip_path:
        return

    cache = CacheManager()
    for cache_file in (thumb_path, clip_path):
        if not cache_file:
            continue
        try:
            p = Path(cache_file)
            if p.exists():
                p.unlink()
                logger.debug(f"[Cache] 已删除缓存文件: {p.name}")
        except Exception as e:
            logger.warning(f"[Cache] 删除缓存文件失败: {cache_file}, {e}")

    # 清理 diskcache 中引用这些路径的 key
    for path_val in (thumb_path, clip_path):
        if path_val:
            cache.remove_by_value_substring(path_val)


class CacheManager:
    """Singleton cache manager backed by diskcache.

    Usage::

        cache = CacheManager()
        cache.set("key", value, expire=3600)
        value = cache.get("key")
    """

    _instance = None

    def __new__(cls) -> "CacheManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        cache_dir = get_cache_dir() / "diskcache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache = Cache(str(cache_dir))
        logger.debug(f"Cache initialized at {cache_dir}")

    def get(self, key: str, default=None):
        """Retrieve a cached value."""
        return self._cache.get(key, default)

    def set(self, key: str, value, expire: int | None = None) -> None:
        """Store a value in cache with optional TTL in seconds."""
        self._cache.set(key, value, expire=expire)

    def delete(self, key: str) -> None:
        """Remove a key from cache."""
        self._cache.delete(key)

    def clear(self) -> None:
        """Clear all cached data."""
        self._cache.clear()

    def __contains__(self, key: str) -> bool:
        return key in self._cache

    def remove_by_value_substring(self, substring: str) -> int:
        """删除所有 value 中包含 substring 的 key。返回删除数。"""
        removed = 0
        for key in list(self._cache):
            try:
                val = self._cache.get(key, "")
                if substring in str(val):
                    self._cache.delete(key)
                    removed += 1
            except Exception:
                pass
        return removed
