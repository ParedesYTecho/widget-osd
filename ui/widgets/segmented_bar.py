"""
segmented_bar.py — Barra LED horizontal segmentada estilo Cyberpunk HUD / Terminal.
Renderiza bloques individuales iluminados con brillo de neón.
"""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget


class SegmentedBarWidget(QWidget):
    def __init__(
        self,
        segments: int = 16,
        height: int = 10,
        lit_color: str = "#06b6d4",
        unlit_color: str = "#0d1b2a",
        is_gradient: bool = False,
        has_capsule_border: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.segments = max(4, int(segments))
        self.lit_color = QColor(lit_color)
        self.unlit_color = QColor(unlit_color)
        self.is_gradient = is_gradient
        self.has_capsule_border = has_capsule_border
        self.value_percent = 0.0
        self.setFixedHeight(height)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def setValue(self, percent: float):
        self.value_percent = max(0.0, min(100.0, float(percent)))
        self.update()

    def setColor(self, color: str):
        self.lit_color = QColor(color)
        self.update()

    def _get_seg_color(self, idx: int) -> QColor:
        if not self.is_gradient or self.segments <= 1:
            return self.lit_color
        # Gradient: Cyan (#06b6d4) -> Yellow (#eab308) -> Amber/Orange (#f59e0b)
        t = idx / max(1, self.segments - 1)
        if t <= 0.5:
            f = t / 0.5
            r = int(6 + f * (234 - 6))
            g = int(182 + f * (179 - 182))
            b = int(212 + f * (8 - 212))
        else:
            f = (t - 0.5) / 0.5
            r = int(234 + f * (245 - 234))
            g = int(179 + f * (158 - 179))
            b = int(8 + f * (11 - 8))
        return QColor(r, g, b)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        pad_x = 2.5 if self.has_capsule_border else 0.0
        pad_y = 2.0 if self.has_capsule_border else 0.0

        if self.has_capsule_border:
            # Outer capsule outline
            border_c = QColor(self.lit_color.red(), self.lit_color.green(), self.lit_color.blue(), 110)
            painter.setPen(QPen(border_c, 1.0))
            bg_c = QColor(6, 15, 25, 180)
            painter.setBrush(QBrush(bg_c))
            painter.drawRoundedRect(0.5, 0.5, w - 1.0, h - 1.0, 3.0, 3.0)

        inner_w = w - 2 * pad_x
        inner_h = h - 2 * pad_y
        gap = 2.0
        total_gaps = (self.segments - 1) * gap
        seg_w = max(1.5, (inner_w - total_gaps) / float(self.segments))

        lit_count = int(round((self.value_percent / 100.0) * self.segments))
        if self.value_percent > 0 and lit_count == 0:
            lit_count = 1

        for i in range(self.segments):
            x = pad_x + i * (seg_w + gap)
            is_lit = i < lit_count
            if is_lit:
                color = self._get_seg_color(i)
                glow = QColor(color)
                glow.setAlpha(45)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(glow))
                painter.drawRoundedRect(x - 0.5, pad_y, seg_w + 1.0, inner_h, 1.2, 1.2)
                painter.setBrush(QBrush(color))
                painter.drawRoundedRect(x, pad_y + 0.5, seg_w, inner_h - 1.0, 1.0, 1.0)
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(self.unlit_color))
                painter.drawRoundedRect(x, pad_y + 0.5, seg_w, inner_h - 1.0, 1.0, 1.0)

        painter.end()

class CyberCalibrationSlider(QWidget):
    """Barra de calibración con micro-ticks y muescas ▲ / ▼ para ventiladores Cyberpunk."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(16)
        self._value = 62.0  # Porcentaje 0 a 100
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def setValue(self, val: float):
        self._value = max(0.0, min(100.0, float(val)))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())

        total_ticks = 36
        tick_w = 2.0
        start_x = 4.0
        avail_w = w - (2 * start_x)
        gap = (avail_w - (total_ticks * tick_w)) / max(1, total_ticks - 1)

        current_idx = int(round((self._value / 100.0) * (total_ticks - 1)))

        tick_y_top = 4.0
        tick_h = 8.0

        # Corchetes laterales [ ]
        pen_bracket = QPen(QColor(6, 182, 212, 140), 1.0)
        painter.setPen(pen_bracket)
        painter.drawLine(int(start_x - 3), int(tick_y_top - 1), int(start_x - 3), int(tick_y_top + tick_h + 1))
        painter.drawLine(int(w - start_x + 3), int(tick_y_top - 1), int(w - start_x + 3), int(tick_y_top + tick_h + 1))

        # Ticks
        for i in range(total_ticks):
            x = start_x + i * (tick_w + gap)
            if i <= current_idx:
                painter.setPen(QColor("#06b6d4"))
            else:
                painter.setPen(QColor(18, 40, 60, 160))
            painter.drawLine(int(x), int(tick_y_top), int(x), int(tick_y_top + tick_h))

        # Notch superior (verde lima ▼)
        notch_x = start_x + current_idx * (tick_w + gap) + (tick_w / 2.0)
        painter.setBrush(QBrush(QColor("#84cc16")))
        painter.setPen(Qt.PenStyle.NoPen)
        p_top = QPolygonF([
            QPointF(notch_x - 2.5, 0.0),
            QPointF(notch_x + 2.5, 0.0),
            QPointF(notch_x, 3.5),
        ])
        painter.drawPolygon(p_top)

        # Notch inferior (cyan ▲)
        painter.setBrush(QBrush(QColor("#06b6d4")))
        p_bot = QPolygonF([
            QPointF(notch_x - 2.5, h),
            QPointF(notch_x + 2.5, h),
            QPointF(notch_x, h - 3.5),
        ])
        painter.drawPolygon(p_bot)

        painter.end()
