"""
ring_gauge_v3.py — Micro-anillo y arco de progreso circular vectorial anti-aliased con estética Glass HUD.
Soporta modo circular cerrado y modo de arco semi-circular / horseshoe con degradados vibrantes.
"""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget


class RingGaugeV3(QWidget):
    """Micro-indicador circular y de arco vectorial de precisión para telemetría."""
    def __init__(self, size: int = 44, stroke: float = 4.0, arc_mode: bool = False, parent=None):
        super().__init__(parent)
        self._base_size = size
        self._base_stroke = stroke
        self._size = size
        self._stroke = stroke
        self._arc_mode = arc_mode
        self.setFixedSize(size, size)
        self._value = 0.0
        self._min = 0.0
        self._max = 100.0
        self._custom_color = None

    def set_arc_mode(self, enabled: bool):
        self._arc_mode = enabled
        self.update()

    def set_scale(self, scale: float):
        """Ajusta el tamaño y grosor del anillo según el factor de escala de la UI."""
        self._size = max(26, int(self._base_size * scale))
        self._stroke = max(2.8, self._base_stroke * scale)
        self.setFixedSize(self._size, self._size)
        self.update()

    def set_dimensions(self, size: int, stroke: float):
        """Ajusta directamente el tamaño y grosor del trazo."""
        self._size = size
        self._stroke = stroke
        self.setFixedSize(size, size)
        self.update()

    def setValue(self, val: float):
        try:
            self._value = max(self._min, min(self._max, float(val or 0.0)))
        except (ValueError, TypeError):
            self._value = 0.0
        self.update()

    def value(self) -> float:
        return self._value

    def setCustomColor(self, color_hex: str | None):
        self._custom_color = QColor(color_hex) if color_hex else None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        padding = self._stroke / 2.0 + 2.5
        rect = QRectF(padding, padding, self._size - padding * 2, self._size - padding * 2)

        if self._arc_mode:
            # Modo Horseshoe / Arco abierto abajo (270 grados de recorrido, de 225° a -45°)
            start_angle = 225 * 16
            total_span = -270 * 16

            # 1. Pista de fondo translúcida
            track_pen = QPen(QColor(255, 255, 255, 32))
            track_pen.setWidthF(self._stroke)
            track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(track_pen)
            painter.drawArc(rect, start_angle, total_span)

            # 2. Arco de progreso activo
            if self._value > 0.0:
                span_fraction = min(1.0, self._value / self._max)
                active_span = int(total_span * span_fraction)

                if self._custom_color:
                    value_pen = QPen(self._custom_color)
                else:
                    grad = QLinearGradient(0, self._size, self._size, 0)
                    grad.setColorAt(0.0, QColor("#10b981"))
                    grad.setColorAt(0.65, QColor("#34d399"))
                    grad.setColorAt(1.0, QColor("#f59e0b"))
                    value_pen = QPen(QBrush(grad), self._stroke)

                value_pen.setWidthF(self._stroke)
                value_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(value_pen)
                painter.drawArc(rect, start_angle, active_span)

        else:
            # Modo círculo 360° estándar
            track_pen = QPen(QColor(255, 255, 255, 20))
            track_pen.setWidthF(self._stroke)
            track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(track_pen)
            painter.drawArc(rect, 0, 360 * 16)

            if self._custom_color:
                color = self._custom_color
            else:
                if self._value < 60.0:
                    color = QColor("#10b981")
                elif self._value < 85.0:
                    color = QColor("#f59e0b")
                else:
                    color = QColor("#f43f5e")

            if self._value > 0.0:
                value_pen = QPen(color)
                value_pen.setWidthF(self._stroke)
                value_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(value_pen)
                span_angle = int(- (self._value / self._max) * 360 * 16)
                painter.drawArc(rect, 1440, span_angle)

        painter.end()
