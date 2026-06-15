from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtCore import QRect

def draw_bottom_gradient_bar(painter: QPainter, rect: QRect, color: QColor, height: int = 3):
    """在矩形底部绘制一条水平渐变带"""
    bar_rect = QRect(rect.x(), rect.bottom() - height, rect.width(), height)
    gradient = QLinearGradient(bar_rect.topLeft(), bar_rect.topRight())
    gradient.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), 0))
    gradient.setColorAt(0.5, color)
    gradient.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
    painter.fillRect(bar_rect, gradient)