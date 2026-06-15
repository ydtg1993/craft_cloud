"""AboutPage — 关于页面，展示软件信息、开发者、功能、许可证、致谢和更新日志。"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QFrame)
from qfluentwidgets import (TitleLabel, BodyLabel, CaptionLabel, SubtitleLabel,
                            GroupHeaderCardWidget, HeaderCardWidget, FluentIcon,
                            HyperlinkButton, ScrollArea)
from core.translator import tr

VERSION = "2.0.0"
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

# ── 版本历史 ──────────────────────────────────────────────────
CHANGELOG = [
    ("v2.0.0", "2026-06", [
        tr("Complete architecture refactoring: layered architecture "
           "(core/model/services/view), SOLID principles"),
        tr("Technology stack modernization: SQLAlchemy 2.x ORM, "
           "Pydantic config, loguru logging"),
        tr("UI upgrade: qfluentwidgets Fluent Design component library"),
        tr("New Task Queue unified scheduling, Auto Sync dashboard"),
        tr("System tray minimization with background auto sync"),
        tr("Whoosh full-text search + Chinese word segmentation (jieba)"),
    ]),
    ("v1.x", "2024 — 2025", [
        tr("Initial release based on PyQt5"),
        tr("Basic file upload/download functionality"),
        tr("Telegram channel-based storage"),
    ]),
]


class _SectionCard(GroupHeaderCardWidget):
    """通用信息分区卡片，每行用 addGroup 展示。"""

    def __init__(self, title: str, parent=None):
        HeaderCardWidget.__init__(self, parent)
        self.setTitle(title)
        self.setStyleSheet("""
            GroupHeaderCardWidget {
                border-radius: 8px;
                border: none;
            }
        """)


class AboutPage(QWidget):
    """关于页面 —— 软件信息、开发者、功能、许可证、致谢、更新日志。"""

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
        card_layout = QVBoxLayout(container)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(10)

        self._build_app_info(card_layout)
        self._build_developer(card_layout)
        self._build_features(card_layout)
        self._build_license(card_layout)
        self._build_acknowledgments(card_layout)
        self._build_changelog(card_layout)

        card_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

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
            row.setStyleSheet("QLabel { font-size: 13px; padding: 2px 0; }")
            card.vBoxLayout.addWidget(row)
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

    # ── 更新日志 ───────────────────────────────────────────────
    def _build_changelog(self, layout):
        card = _SectionCard(self.tr("Version History"), self)

        for version, date, changes in CHANGELOG:
            header = SubtitleLabel(f"{version}  ({date})")
            card.vBoxLayout.addWidget(header)

            for change in changes:
                item = CaptionLabel(f"  •  {change}")
                item.setWordWrap(True)
                item.setStyleSheet(
                    "QLabel { font-size: 12px; }")
                card.vBoxLayout.addWidget(item)

            # 版本之间加一点间距
            spacer = QWidget()
            spacer.setFixedHeight(6)
            card.vBoxLayout.addWidget(spacer)
        card.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(card)
