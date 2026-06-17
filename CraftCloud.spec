# -*- mode: python ; coding: utf-8 -*-

import os, sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# ── 项目模块 + 第三方库隐式导入 ───────────────────────────
_hiddenimports = []

# 项目自己的包
for pkg in ['core', 'model', 'view', 'services']:
    _hiddenimports += collect_submodules(pkg)

# Telethon 子包极多，使用 collect_submodules 一次性收集
_hiddenimports += collect_submodules('telethon')

_hiddenimports += [
    # 🔑 关键密码学依赖（telethon 内部 try/except 引入，PyInstaller 追踪不到）
    'rsa',
    'rsa.core',
    'pyaes',
    'cryptg',

    # 🔑 QR 码（login_window.py 懒加载，PyInstaller 检测不到）
    'qrcode',
    'qrcode.image',
    'qrcode.image.pil',

    # Qt 多媒体（文件预览）
    'PySide6.QtMultimedia',
    'PySide6.QtMultimediaWidgets',

    # 搜索引擎
    'whoosh',
    'whoosh.analysis',
    'whoosh.lang',
    'whoosh.lang.snowball',

    # ORM 方言
    'sqlalchemy',
    'sqlalchemy.dialects.sqlite',
    'sqlalchemy.event',

    # 配置 / 序列化
    'pydantic',
    'pydantic.deprecated',

    # GUI
    'qfluentwidgets',

    # 图像
    'PIL',

    # YAML
    'yaml',

    # asyncio（Windows 打包后子线程事件循环需要）
    'asyncio',
    'asyncio.windows_events',
    'asyncio.windows_utils',

    # apscheduler 需要 pkg_resources
    'pkg_resources',
]

# ── 数据文件收集 ──────────────────────────────────────────
_datas = [
    ('resources', 'resources'),            # 图标 + i18n 翻译文件
    ('config', 'config'),                  # 默认配置文件
]
_datas += collect_data_files('qfluentwidgets')   # QFluentWidgets 图标/样式
_datas += collect_data_files('jieba')            # jieba 分词词典

# ── Analysis ──────────────────────────────────────────────
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=_datas,
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'scipy',
        'pandas',
        'IPython',
        'jupyter',
        'tkinter',
        'unittest',
        'pydoc',
        'distutils',
        'pip',
        'PyQt5',            # 与 PySide6 冲突，PyInstaller 直接 abort
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# ── PYZ ───────────────────────────────────────────────────
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# ── EXE ───────────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
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
    icon='resources/cc.ico',
)

# ── COLLECT ───────────────────────────────────────────────
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
