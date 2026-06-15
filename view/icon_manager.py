from PySide6.QtWidgets import QApplication, QStyle, QFileIconProvider
from PySide6.QtCore import QFileInfo

class IconManager:
    _icon_provider = QFileIconProvider()
    _cache = {}

    @classmethod
    def get_icon(cls, filename: str):
        if not filename:
            return QApplication.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        if ext not in cls._cache:
            temp_path = f"temp.{ext}" if ext else "temp"
            cls._cache[ext] = cls._icon_provider.icon(QFileInfo(temp_path))
        icon = cls._cache[ext]
        if icon.isNull():
            return QApplication.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        return icon