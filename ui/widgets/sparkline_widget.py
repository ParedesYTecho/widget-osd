"""
sparkline_widget.py — Gráfica sparkline vectorial ultra-ligera en tiempo real con curva suave y relleno en gradiente.
Renderizado nativo con QPainter y anti-aliasing.
"""

from collections import deque
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


class SparklineWidget(QWidget):
    def __init__(
        self,
        max_points: int = 50,
        height: int = 38,
        line_color: str = "#cbd5e1",
        fill_alpha: int = 40,
        parent=None,
    ):
        super().__init__(parent)
        self.max_points = max_points
        self.points = deque([0.0] * max_points, maxlen=max_points)
        self.line_color = QColor(line_color)
        self.fill_alpha = fill_alpha
        self.min_val = 0.0
        self.max_val = 100.0
        self.setFixedHeight(height)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def add_value(self, val: float):
        self.points.append(max(0.0, float(val)))
        self.update()

    def set_color(self, color: str):
        self.line_color = QColor(color)
        self.update()

    def paintEvent(self, event):
        if not self.points:
            return

        w = float(self.width())
        h = float(self.height())
        if w <= 4 or h <= 4:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Faint horizontal tactical grid lines
        grid_pen = QPen(QColor(self.line_color.red(), self.line_color.green(), self.line_color.blue(), 25), 1.0)
        painter.setPen(grid_pen)
        painter.drawLine(0, int(h * 0.33), int(w), int(h * 0.33))
        painter.drawLine(0, int(h * 0.66), int(w), int(h * 0.66))

        n = len(self.points)
        step_x = w / max(1.0, float(n - 1))
        span = max(1.0, self.max_val - self.min_val)

        coords = []
        for i, val in enumerate(self.points):
            clamped = max(self.min_val, min(self.max_val, val))
            norm_y = (clamped - self.min_val) / span
            y = (1.0 - norm_y) * (h - 4.0) + 2.0
            x = float(i) * step_x
            coords.append(QPointF(x, y))

        if len(coords) < 2:
            painter.end()
            return

        path = QPainterPath()
        path.moveTo(coords[0])
        for p in coords[1:]:
            path.lineTo(p)

        # Gradient fill using line color
        fill_path = QPainterPath(path)
        fill_path.lineTo(QPointF(coords[-1].x(), h))
        fill_path.lineTo(QPointF(coords[0].x(), h))
        fill_path.closeSubpath()

        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(self.line_color.red(), self.line_color.green(), self.line_color.blue(), max(20, self.fill_alpha)))
        grad.setColorAt(0.5, QColor(self.line_color.red(), self.line_color.green(), self.line_color.blue(), int(self.fill_alpha * 0.4)))
        grad.setColorAt(1.0, QColor(self.line_color.red(), self.line_color.green(), self.line_color.blue(), 0))

        painter.fillPath(fill_path, grad)

        # Crisp outline stroke
        pen = QPen(self.line_color)
        pen.setWidthF(1.2)
        painter.setPen(pen)
        painter.drawPath(path)

        painter.end()
