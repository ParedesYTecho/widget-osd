"""
spinning_fan_badge.py -- Badge vectorial animado para ventiladores de refrigeracion.
Renderiza un icono de ventilador de 4 aspas que rota fluidamente segun el RPM real
y cambia el color del resplandor segun la velocidad (Silencioso, Normal, Rapido, Maximo).
"""

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QBrush, QPen
from PySide6.QtWidgets import QWidget


class SpinningFanBadge(QWidget):
    """Badge de ventilador con aspas animadas que giran en funcion del RPM."""
    def __init__(self, size: int = 24, parent=None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self._rpm = 0.0
        self._max_rpm = 1800.0
        self._angle = 0.0
        self._is_spinning = False

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._on_tick)

    def set_fan_speed(self, rpm: float, max_rpm: float = 1800.0):
        self._rpm = max(0.0, float(rpm or 0.0))
        self._max_rpm = max(100.0, float(max_rpm or 1800.0))

        if self._rpm > 0:
            if not self._is_spinning:
                self._is_spinning = True
                self._timer.start()
        else:
            if self._is_spinning:
                self._is_spinning = False
                self._timer.stop()
                self.update()

    def _on_tick(self):
        if not self._is_spinning:
            return
        pct = min(1.0, self._rpm / self._max_rpm)
        speed = 3.0 + pct * 14.0
        self._angle = (self._angle + speed) % 360.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        s = float(self._size)
        pct = (self._rpm / self._max_rpm) * 100.0 if self._max_rpm > 0 else 0.0

        if self._rpm <= 0:
            bg_color = QColor(100, 116, 139, 40)
            border_color = QColor(148, 163, 184, 50)
            fan_color = QColor(203, 213, 225, 180)
        else:
            bg_color = QColor(16, 185, 129, 65)
            border_color = QColor(52, 211, 153, 95)
            fan_color = QColor(255, 255, 255, 245)

        radius = s * 0.26
        rect = QRectF(0.5, 0.5, s - 1.0, s - 1.0)
        painter.setBrush(QBrush(bg_color))
        painter.setPen(QPen(border_color, 1.0))
        painter.drawRoundedRect(rect, radius, radius)

        center_x = s / 2.0
        center_y = s / 2.0
        painter.save()
        painter.translate(center_x, center_y)
        painter.rotate(self._angle)

        hub_r = s * 0.12
        blade_len = s * 0.35
        blade_w = s * 0.22

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(fan_color))

        num_blades = 6
        step_angle = 360.0 / num_blades
        for i in range(num_blades):
            painter.save()
            painter.rotate(i * step_angle)
            blade_path = QPainterPath()
            blade_path.moveTo(hub_r * 0.8, -hub_r * 0.5)
            blade_path.cubicTo(
                hub_r + blade_len * 0.4, -blade_w * 1.17,
                hub_r + blade_len * 0.8, -blade_w * 0.78,
                hub_r + blade_len, blade_w * 0.2
            )
            blade_path.cubicTo(
                hub_r + blade_len * 0.9, blade_w * 0.8,
                hub_r + blade_len * 0.5, blade_w * 0.9,
                hub_r * 0.8, hub_r * 0.6
            )
            blade_path.closeSubpath()
            painter.drawPath(blade_path)
            painter.restore()

        painter.setBrush(QBrush(fan_color))
        painter.drawEllipse(QRectF(-hub_r, -hub_r, hub_r * 2, hub_r * 2))

        painter.restore()
        painter.end()
