"""AboutPage — 关于页面，展示软件信息、开发者、功能、许可证和致谢。"""
import shiboken6
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QFrame)
from qfluentwidgets import (TitleLabel, BodyLabel, CaptionLabel,
                            GroupHeaderCardWidget, HeaderCardWidget, FluentIcon,
                            HyperlinkButton, ScrollArea, Theme, qconfig)
from core.translator import tr
from qfluentwidgets import theme as qfw_theme

VERSION = "2.7.7"
GITHUB_URL = "https://github.com/ydtg1993/craft_cloud"
WEBSITE_URL = "https://craftcloud.cc.cd/"

# ── 致谢的开源项目 ──────────────────────────────────────────────
ACKNOWLEDGMENTS = [
    ("PySide6", "https://www.qt.io/qt-for-python",
     tr("Qt for Python — GUI framework")),
    ("qfluentwidgets", "https://github.com/zhiyiYo/PyQt-Fluent-Widgets",
     tr("Fluent Design component library")),
    ("Telethon", "https://github.com/LonamiWebs/Telethon",
     tr("Telegram MTProto API client library")),
    ("SQLAlchemy", "https://www.sqlalchemy.org/",
     tr("Python SQL toolkit and ORM")),
    ("Pydantic", "https://github.com/pydantic/pydantic",
     tr("Data validation and settings management")),
    ("loguru", "https://github.com/Delgan/loguru",
     tr("Python logging library")),
    ("Whoosh", "https://whoosh.readthedocs.io/",
     tr("Pure Python full-text search engine")),
    ("Pillow", "https://python-pillow.org/",
     tr("Python image processing library")),
    ("jieba", "https://github.com/fxsjy/jieba",
     tr("Chinese word segmentation library")),
    ("diskcache", "https://github.com/grantjenks/python-diskcache",
     tr("Disk cache library")),
    ("qrcode", "https://github.com/lincolnloop/python-qrcode",
     tr("QR code generation library")),
]


class _SectionCard(GroupHeaderCardWidget):
    """通用信息分区卡片，每行用 addGroup 展示。"""

    def __init__(self, title: str, parent=None):
        HeaderCardWidget.__init__(self, parent)
        self.setTitle(title)


class AboutPage(QWidget):
    """关于页面 —— 软件信息、开发者、功能、许可证、致谢。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AboutPage")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        layout.addWidget(TitleLabel(self.tr("About")))

        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.enableTransparentBackground()

        container = QWidget()
        container.setObjectName("aboutScrollContainer")
        container.setStyleSheet("#aboutScrollContainer { background: transparent; }")
        card_layout = QVBoxLayout(container)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(10)

        self._theme_labels = []  # 需要随主题切换颜色的 QLabel

        self._build_app_info(card_layout)
        self._build_developer(card_layout)
        self._build_features(card_layout)
        self._build_license(card_layout)
        self._build_acknowledgments(card_layout)

        card_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        self._apply_theme_colors()
        qconfig.themeChanged.connect(self._apply_theme_colors)

    # ── 应用信息 ───────────────────────────────────────────────
    def _build_app_info(self, layout):
        card = _SectionCard(self.tr("Application"), self)
        card.addGroup(
            FluentIcon.INFO,
            self.tr("Name"),
            "{name}  ·  v{version}".format(
                name=self.tr("CraftCloud"),
                version=VERSION,
            ),
            QWidget(),
        )
        card.addGroup(
            FluentIcon.TAG,
            self.tr("Alias"),
            self.tr("Plane Cloud — Use Telegram as unlimited cloud storage"),
            QWidget(),
        )
        layout.addWidget(card)

    # ── 开发者信息 ─────────────────────────────────────────────
    def _build_developer(self, layout):
        card = _SectionCard(self.tr("Developer"), self)

        github_btn = HyperlinkButton(
            GITHUB_URL, self.tr("GitHub: ydtg1993"), icon=FluentIcon.GITHUB)
        card.addGroup(
            FluentIcon.PEOPLE,
            self.tr("Author"),
            "ydtg1993",
            github_btn,
        )

        website_btn = HyperlinkButton(
            WEBSITE_URL, self.tr("Project Homepage"), icon=FluentIcon.LINK)
        card.addGroup(
            FluentIcon.GLOBE,
            self.tr("Website"),
            WEBSITE_URL,
            website_btn,
        )

        layout.addWidget(card)

    # ── 核心功能 ───────────────────────────────────────────────
    def _build_features(self, layout):
        card = _SectionCard(self.tr("Core Features"), self)

        features = [
            self.tr("🚀 Unlimited Cloud Storage — "
                    "Store files via Telegram channels, no capacity limits"),
            self.tr("📁 Directory Organization — "
                    "Create folders and manage file hierarchy like a local disk"),
            self.tr("🔄 Auto Sync — "
                    "Watch local folders and auto-upload changes to Telegram"),
            self.tr("🔍 Full-Text Search — "
                    "Search files by name or content with Chinese word segmentation"),
            self.tr("📱 QR Code Login — "
                    "Quickly log in using your Telegram mobile app"),
            self.tr("🖥️ System Tray — "
                    "Minimize to tray, continue syncing in the background"),
            self.tr("🌐 No VPN Needed — "
                    "Direct connection to Telegram servers via MTProto protocol"),
            self.tr("🔒 Privacy — "
                    "Files are stored in your personal Telegram channels, "
                    "no third-party access"),
        ]

        for feature in features:
            row = QLabel(feature)
            row.setWordWrap(True)
            base = "font-size: 13px; padding: 2px 0;"
            card.vBoxLayout.addWidget(row)
            self._theme_labels.append((row, base))
        card.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(card)

    # ── 开源许可证 ─────────────────────────────────────────────
    def _build_license(self, layout):
        card = _SectionCard(self.tr("License"), self)

        license_text = (
            "MIT License — Copyright (c) 2026 ydtg1993\n\n"
            + self.tr(
                "Permission is hereby granted, free of charge, to any person "
                "obtaining a copy of this software and associated documentation "
                "files (the \"Software\"), to deal in the Software without "
                "restriction, including without limitation the rights to use, "
                "copy, modify, merge, publish, distribute, sublicense, and/or "
                "sell copies of the Software."
            )
        )
        lbl = BodyLabel(license_text)
        lbl.setWordWrap(True)
        card.vBoxLayout.addWidget(lbl)
        card.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(card)

    # ── 致谢 ───────────────────────────────────────────────────
    def _build_acknowledgments(self, layout):
        card = _SectionCard(self.tr("Acknowledgments"), self)

        intro = CaptionLabel(
            self.tr(
                "Special thanks to the following open-source projects "
                "that make CraftCloud possible:"
            )
        )
        intro.setWordWrap(True)
        card.vBoxLayout.addWidget(intro)

        for name, url, desc in ACKNOWLEDGMENTS:
            link = HyperlinkButton(url, f"{name}")
            card.addGroup(FluentIcon.LIBRARY, name, desc, link)
        card.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(card)

    # ── 主题适配 ───────────────────────────────────────────────
    def _apply_theme_colors(self):
        """主题切换时刷新 feature 标签的文字颜色。"""
        is_dark = qfw_theme() == Theme.DARK
        c = "#FFFFFF" if is_dark else "#000000"
        for lbl, base in self._theme_labels:
            if shiboken6.isValid(lbl):
                lbl.setStyleSheet(f"QLabel {{ {base} color: {c}; }}")
