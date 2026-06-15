"""视图层图标工具。"""
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtCore import Qt, QSize, QPoint
from qfluentwidgets import InfoBadgeManager


def create_overlay_icon(base_icon: QIcon, overlay_path: str, size: QSize = QSize(32, 32)) -> QIcon:
    """在基础图标的右下角叠加一个小图标"""
    pixmap = QPixmap(size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.drawPixmap(0, 0, base_icon.pixmap(size))
    overlay_icon = QIcon(overlay_path)
    overlay_size = QSize(size.width() // 2, size.height() // 2)
    overlay_pixmap = overlay_icon.pixmap(overlay_size)
    x = size.width() - overlay_size.width()
    y = size.height() - overlay_size.height()
    painter.drawPixmap(x, y, overlay_pixmap)
    painter.end()
    return QIcon(pixmap)


@InfoBadgeManager.register('Custom')
class CustomInfoBadgeManager(InfoBadgeManager):
    """将徽章放在目标项的右侧中央"""

    def position(self):
        x = self.target.width() - self.badge.width() - 4
        y = (self.target.height() - self.badge.height()) // 2
        return QPoint(x, y)
