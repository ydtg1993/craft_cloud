"""媒体缓存生成 — 缩略图、音视频预览切片、大图压缩。

规则：
- 视频：最多 15s，最高 480p
- 音频：最多 30s，降至 128kbps AAC
- 图片：>2MB 时压缩到 2MB 以内
"""
import re
import subprocess
import sys
from pathlib import Path
from loguru import logger
from core.utils import get_ffmpeg_path, get_media_extensions
from core.cache_manager import CacheManager

# Windows 打包后 subprocess 调用 ffmpeg 不弹 CMD 黑窗
_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# ── 配置常量 ────────────────────────────────────────────────────────
VIDEO_CLIP_DURATION = 15       # 视频预览切片最长秒数
VIDEO_MAX_HEIGHT = 480         # 视频预览最高分辨率
AUDIO_CLIP_DURATION = 30      # 音频预览切片最长秒数
AUDIO_BITRATE = "64k"         # 音频预览比特率
IMAGE_MAX_SIZE_BYTES = 0.5 * 1024 * 1024  # 图片压缩阈值 .5MB
THUMB_SIZE = (256, 256)        # 缩略图尺寸


def generate_thumbnail(file_path, output_dir, size=THUMB_SIZE, resource_id=None):
    """为任意文件生成 256×256 JPEG 缩略图。先查 diskcache 缓存。

    Args:
        resource_id: 可选唯一标识符（如 Telegram file_id），用于生成唯一文件名，
                     避免不同扩展名的同名文件（1.webp / 1.jpg）缩略图撞名。
    """
    cache = CacheManager()
    cache_key = f"thumb:{file_path}:{size[0]}x{size[1]}"
    cached = cache.get(cache_key)
    if cached and Path(cached).exists():
        return cached

    if not Path(file_path).exists():
        return None
    # 优先用 resource_id 做文件名前缀，避免同名不同扩展名文件撞名
    if resource_id:
        safe_prefix = re.sub(r'[^\w\-.]', '_', str(resource_id))
    else:
        safe_prefix = re.sub(r'[^\w\-.]', '_', Path(file_path).stem)
    thumb_path = str(Path(output_dir) / f"{safe_prefix}_thumb.jpg")
    ext = Path(file_path).suffix.lower()
    media_exts = get_media_extensions()
    image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}

    if ext in image_exts:
        try:
            from PIL import Image
            with Image.open(file_path) as img:
                img.thumbnail(size)
                img.convert('RGB').save(thumb_path, 'JPEG', quality=80)
            cache.set(cache_key, thumb_path)
            return thumb_path
        except Exception as e:
            logger.debug(f"Pillow failed for {file_path}, falling back to ffmpeg: {e}")

    # 只对视频文件尝试 ffmpeg 提取首帧；音频和文档等跳过
    if ext not in media_exts['video']:
        return None

    cmd = [get_ffmpeg_path(), '-i', file_path, '-vframes', '1', '-q:v', '2', thumb_path, '-y']
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=_CREATION_FLAGS, check=True, timeout=10)
        if Path(thumb_path).exists():
            cache.set(cache_key, thumb_path)
            return thumb_path
    except FileNotFoundError:
        logger.warning("ffmpeg not found, skipping thumbnail generation.")
    except Exception as e:
        logger.warning(f"Failed to generate thumbnail for {file_path}: {e}")
    return None


def generate_media_clip(file_path, output_dir, is_audio=False, resource_id=None):
    """生成音视频预览切片。

    视频：最多 15s，分辨率 ≤ 240p，H.264 + AAC。
    音频：最多 30s，AAC 64kbps。

    Args:
        resource_id: 可选唯一标识符，用于生成唯一文件名。
    """
    cache = CacheManager()
    duration = AUDIO_CLIP_DURATION if is_audio else VIDEO_CLIP_DURATION
    cache_key = f"clip:{file_path}:{duration}:v2"
    cached = cache.get(cache_key)
    if cached and Path(cached).exists():
        return cached

    if not Path(file_path).exists():
        return None
    if resource_id:
        safe_prefix = re.sub(r'[^\w\-.]', '_', str(resource_id))
    else:
        safe_prefix = re.sub(r'[^\w\-.]', '_', Path(file_path).stem)

    if is_audio:
        # 音频：一律重编码为 AAC 128kbps M4A，-c copy 在 flac/ogg 等格式上
        # -t 截断行为不可靠，且容器与编码可能不匹配
        clip_path = str(Path(output_dir) / f"{safe_prefix}_clip.m4a")
        cmd = [get_ffmpeg_path(), '-i', file_path, '-t', str(duration),
               '-c:a', 'aac', '-b:a', AUDIO_BITRATE,
               '-vn', clip_path, '-y']
    else:
        # 视频：一律重编码以限制时长 + 分辨率，输出 MP4
        clip_path = str(Path(output_dir) / f"{safe_prefix}_clip.mp4")
        cmd = [get_ffmpeg_path(), '-i', file_path, '-t', str(duration),
               '-vf', f'scale=-2:{VIDEO_MAX_HEIGHT}',
               '-c:v', 'libx264', '-preset', 'slow',
               '-r', '20',
               '-crf', '26',
               '-c:a', 'aac', '-b:a', AUDIO_BITRATE,
               clip_path, '-y']

    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=_CREATION_FLAGS, check=True, timeout=120)
        if Path(clip_path).exists():
            cache.set(cache_key, clip_path)
            return clip_path
    except FileNotFoundError:
        logger.warning("ffmpeg not found, skipping clip generation.")
    except Exception as e:
        logger.warning(f"Failed to generate media clip for {file_path}: {e}")
    return None


def generate_image_preview(file_path, output_dir, resource_id=None):
    """为超大图片生成压缩版预览。

    先分析原始图片尺寸和文件大小，计算目标缩放比，一次压缩到位。
    策略：优先缩分辨率，质量保底 70。

    Args:
        resource_id: 可选唯一标识符，用于生成唯一文件名。
    """
    if not Path(file_path).exists():
        return None

    try:
        original_size = Path(file_path).stat().st_size
    except OSError:
        return None
    if original_size <= IMAGE_MAX_SIZE_BYTES:
        return None

    cache = CacheManager()
    cache_key = f"img_preview:{file_path}:v2"
    cached = cache.get(cache_key)
    if cached and Path(cached).exists():
        return cached

    try:
        from PIL import Image
        if resource_id:
            safe_prefix = re.sub(r'[^\w\-.]', '_', str(resource_id))
        else:
            safe_prefix = re.sub(r'[^\w\-.]', '_', Path(file_path).stem)
        preview_path = str(Path(output_dir) / f"{safe_prefix}_preview.jpg")

        with Image.open(file_path) as img:
            w, h = img.size
            pixels = w * h
            # ── 分析阶段：计算需要的压缩比 ────────────────────────
            # JPEG 体积 ≈ pixels × quality_factor，预算 20% 安全余量
            overhead = 0.8
            size_ratio = (IMAGE_MAX_SIZE_BYTES / original_size) * overhead

            # 根据需要的压缩比选择策略
            if size_ratio >= 0.85:
                # 轻微超标（2-2.4MB）：仅降质量
                target_quality = 80
                scale = 1.0
            elif size_ratio >= 0.5:
                # 中等超标（2.4-4MB）：质量 78 + 适度缩分辨率
                target_quality = 78
                scale = size_ratio ** 0.45  # sqrt 偏保守
            elif size_ratio >= 0.2:
                # 明显超标（4-10MB）：质量 75 + 缩放
                target_quality = 75
                scale = (size_ratio * 0.9) ** 0.5
            else:
                # 严重超标（>10MB）：质量 70 + 激进缩放
                target_quality = 70
                scale = (size_ratio * 0.85) ** 0.5

            # 尺寸上限：宽度不超过 2560px
            max_dim = 2560
            if max(w, h) * scale > max_dim:
                scale = max_dim / max(w, h)

            new_w = max(1, int(w * scale))
            new_h = max(1, int(h * scale))

            # ── 执行压缩 ────────────────────────────────────────
            # 转 RGB（丢掉 alpha 通道）
            if img.mode in ('RGBA', 'P', 'LA'):
                rgb = img.convert('RGB')
            else:
                rgb = img

            if new_w != w or new_h != h:
                rgb = rgb.resize((new_w, new_h), Image.LANCZOS)

            rgb.save(preview_path, 'JPEG', quality=target_quality)

            # ── 安全兜底：仍超标则降质量到 60 再试一次 ──────────
            if Path(preview_path).stat().st_size > IMAGE_MAX_SIZE_BYTES:
                rgb.save(preview_path, 'JPEG', quality=60)

            final_size = Path(preview_path).stat().st_size
            logger.debug(
                f"[ImageCache] {basename}: {original_size/1024:.0f}KB → "
                f"{final_size/1024:.0f}KB "
                f"({w}×{h}→{new_w}×{new_h}, q={target_quality})"
            )
            cache.set(cache_key, preview_path)
            return preview_path

    except ImportError:
        logger.debug("Pillow not available, skipping image preview compression")
    except Exception as e:
        logger.warning(f"Failed to compress image {file_path}: {e}")
    return None


def generate_media_cache(file_path, cache_dir, resource_id=None):
    """统一生成媒体缓存（缩略图 + 预览文件）。

    Args:
        resource_id: 可选唯一标识符（如 Telegram file_id），用于生成唯一文件名，
                     避免同名不同扩展名文件的缓存撞名。

    返回: (thumb_path, preview_path)
    - 视频/音频: preview_path 为切片 (.mp4/.mp3), thumb_path 为首帧缩略图
    - 图片: preview_path 为压缩版（原始 >2MB 时），thumb_path 为缩略图
    - 其他: 只生成缩略图，preview_path = None
    """
    thumb_path = generate_thumbnail(file_path, cache_dir, resource_id=resource_id)
    media_preview_path = None

    ext = Path(file_path).suffix.lower()
    media_exts = get_media_extensions()

    if ext in media_exts['video']:
        media_preview_path = generate_media_clip(file_path, cache_dir, is_audio=False, resource_id=resource_id)
    elif ext in media_exts['audio']:
        media_preview_path = generate_media_clip(file_path, cache_dir, is_audio=True, resource_id=resource_id)
    elif ext in media_exts['image']:
        media_preview_path = generate_image_preview(file_path, cache_dir, resource_id=resource_id)

    return thumb_path, media_preview_path