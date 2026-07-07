# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — cross-platform (Windows / Linux / macOS)."""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# ── Platform detection ──────────────────────────────────────────
IS_WIN   = sys.platform == 'win32'
IS_MACOS = sys.platform == 'darwin'
IS_LINUX = sys.platform.startswith('linux')

# ── Project modules + third-party hidden imports ─────────────────
_hiddenimports = []

for pkg in ['core', 'model', 'view', 'services']:
    _hiddenimports += collect_submodules(pkg)

_hiddenimports += collect_submodules('telethon')

_hiddenimports += [
    # Cryptography (Telethon internals, try/except imports)
    'rsa', 'rsa.core',
    'pyaes',
    'cryptg',

    # QR code (lazy-imported in login_window.py)
    'qrcode', 'qrcode.image', 'qrcode.image.pil',

    # Qt Multimedia (file preview)
    'PySide6.QtMultimedia',
    'PySide6.QtMultimediaWidgets',

    # Search engine
    'whoosh', 'whoosh.analysis', 'whoosh.lang', 'whoosh.lang.snowball',

    # ORM dialects
    'sqlalchemy', 'sqlalchemy.dialects.sqlite', 'sqlalchemy.event',

    # Config / serialization
    'pydantic', 'pydantic.deprecated',

    # GUI
    'qfluentwidgets',

    # Imaging
    'PIL',

    # YAML
    'yaml',

    # asyncio event loop policies
    'asyncio',

    # APScheduler needs pkg_resources (setuptools >= 82 removed it)
    'pkg_resources',
]

# Platform-specific hidden imports
if IS_WIN:
    _hiddenimports += [
        'asyncio.windows_events',
        'asyncio.windows_utils',
    ]
elif IS_MACOS:
    _hiddenimports += [
        'asyncio.unix_events',
    ]
elif IS_LINUX:
    _hiddenimports += [
        'asyncio.unix_events',
    ]

# ── Data files ──────────────────────────────────────────────────
_datas = [
    ('resources', 'resources'),
    ('config', 'config'),
]

# ffmpeg binary (optional, bundled for media preview)
_ffmpeg_name = 'ffmpeg.exe' if IS_WIN else 'ffmpeg'
_ffmpeg_src = Path(SPECPATH).resolve() / 'scripts' / _ffmpeg_name
if _ffmpeg_src.is_file():
    _datas.append((str(_ffmpeg_src), 'scripts'))

_datas += collect_data_files('qfluentwidgets')
_datas += collect_data_files('jieba')

# ── Icon (platform-specific format) ─────────────────────────────
if IS_WIN:
    _icon_path = 'resources/cc.ico'
elif IS_MACOS:
    _icon_path = 'resources/cc.icns'
else:
    _icon_path = 'resources/cc.png'  # Linux DEs accept PNG

# ── Excludes (reduce bundle size) ───────────────────────────────
_excludes = [
    'matplotlib', 'scipy', 'pandas',
    'IPython', 'jupyter',
    'tkinter', 'unittest', 'pydoc',
    'distutils', 'pip',
    'PyQt5',
]

# ── Analysis ────────────────────────────────────────────────────
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=_datas,
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# ── PYZ ─────────────────────────────────────────────────────────
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# ── EXE ─────────────────────────────────────────────────────────
_exe_kwargs = dict(
    name='CraftCloud',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon_path,
)

# macOS: .app bundle instead of raw executable
if IS_MACOS:
    _exe_kwargs['argv_emulation'] = True

exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [], **_exe_kwargs)

# ── COLLECT ─────────────────────────────────────────────────────
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CraftCloud',
)

# ── macOS: create .app bundle ───────────────────────────────────
if IS_MACOS:
    app = BUNDLE(
        coll,
        name='CraftCloud.app',
        icon=_icon_path,
        bundle_identifier='cc.craftcloud.app',
        info_plist={
            'CFBundleDisplayName': 'CraftCloud',
            'CFBundleName': 'CraftCloud',
            'CFBundleShortVersionString': '2.8.1',
            'CFBundleVersion': '2.8.1',
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '11.0',
        },
    )
