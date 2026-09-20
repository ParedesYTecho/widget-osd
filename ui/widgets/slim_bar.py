"""
slim_bar.py — Barra de progreso ultra-delgada y minimalista (2px a 6px).
Estilo industrial Apple / Swiss Typography con bordes suaves.
"""

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QBrush, QLinearGradient, QPen
from PySide6.QtWidgets import QWidget


class SlimProgressBarWidget(QWidget):
    def __init__(
        self,
        bar_height: int = 3,
        bar_color: str = "#38bdf8",
        track_color: str = "#1e2433",
        gradient_colors: list[tuple[float, str]] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.bar_height = bar_height
        self.bar_color = QColor(bar_color)
        self.track_color = QColor(track_color)
        self.gradient_colors = gradient_colors
        self.value_percent = 0.0
        self.setFixedHeight(bar_height + 4)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def setValue(self, percent: float):
        self.value_percent = max(0.0, min(100.0, float(percent)))
        self.update()

    def setColor(self, color: str):
        self.bar_color = QColor(color)
        self.gradient_colors = None
        self.update()

    def setGradient(self, colors: list[tuple[float, str]]):
        self.gradient_colors = colors
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        bh = float(self.bar_height)
        y = (h - bh) / 2.0
        r = bh / 2.0

        # Background track
        track_rect = QRectF(0.0, y, w, bh)
        painter.setPen(QPen(QColor(255, 255, 255, 15 if bh > 10 else 0), 1.0))
        painter.setBrush(QBrush(self.track_color))
        painter.drawRoundedRect(track_rect, r, r)

        # Active fill
        fill_w = (self.value_percent / 100.0) * w
        if fill_w > 0:
            target_w = max(bh, min(w, fill_w))
            fill_rect = QRectF(0.0, y, target_w, bh)
            if self.gradient_colors:
                grad = QLinearGradient(0, y, target_w, y)
                for pos, col_str in self.gradient_colors:
                    grad.setColorAt(pos, QColor(col_str))
                painter.setBrush(QBrush(grad))
            else:
                painter.setBrush(QBrush(self.bar_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(fill_rect, r, r)

        painter.end()
