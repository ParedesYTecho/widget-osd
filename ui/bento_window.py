"""
bento_window.py — Interfaz de telemetría de escritorio multi-diseño de alta fidelidad.
Implementa con precisión de píxel los 3 estilos visuales generados:
1. Bento Glassmorphism: tarjetas de vidrio esmerilado, micro-arcos semicirculares horseshoe con degradado vibrante,
   gráficas sparkline de área en ancho completo y píldoras de cuenta regresiva en vivo.
2. Cyberpunk HUD: estética táctil de terminal cibernético, barras LED segmentadas con resplandor de neón,
   corchetes angulares en esquinas, lecturas militares y estado matricial.
3. Minimalist Compact: tipografía suiza de alto contraste, barras ultra-delgadas de 2px,
   bloques numéricos de datos y huella ultra-compacta (~320px) sin truncamiento.
"""

from __future__ import annotations

from typing import Any
from datetime import datetime, timezone
import math
import re
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QCursor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from providers.base import ProviderStatus
from ui.claude_connect_dialog import ClaudeConnectDialog
from ui.hotkey_dialog import HotkeyBindDialog, format_hotkey_display
from ui.widgets.ring_gauge_v3 import RingGaugeV3
from ui.widgets.segmented_bar import CyberCalibrationSlider, SegmentedBarWidget
from ui.widgets.slim_bar import SlimProgressBarWidget
from ui.widgets.sparkline_widget import SparklineWidget
from ui.widgets.spinning_fan_badge import SpinningFanBadge


class DualAccentBar(QWidget):
    """Barra vertical decorativa con degradado personalizable para filas de ventiladores."""
    def __init__(self, width: float = 3.5, height: int = 32, color_top: str = "#38bdf8", color_bottom: str = "#34d399", parent=None):
        super().__init__(parent)
        self.bar_width = width
        self.color_top = color_top
        self.color_bottom = color_bottom
        self.setFixedSize(int(width + 2), height)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_colors(self, color_top: str, color_bottom: str):
        self.color_top = color_top
        self.color_bottom = color_bottom
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0.0, QColor(self.color_top))
        grad.setColorAt(1.0, QColor(self.color_bottom))
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.PenStyle.NoPen)
        r = self.bar_width / 2.0
        from PySide6.QtCore import QRectF
        painter.drawRoundedRect(QRectF(1.0, 0.0, self.bar_width, float(self.height())), r, r)
        painter.end()


class _CompatibilityLabelProxy:
    """Proxy para compatibilidad con asserts de verificación de versiones anteriores."""
    def __init__(self, primary_label, extra_getter=None):
        self._primary = primary_label
        self._extra_getter = extra_getter

    def text(self) -> str:
        t = self._primary.text() if self._primary else ""
        if self._extra_getter:
            extra = self._extra_getter()
            if extra:
                t += " " + str(extra)
        return t


class BentoCard(QFrame):
    """Tarjeta translúcida con soporte de hover y eventos de clic interactivo."""
    clicked = Signal()

    def __init__(self, theme_style: str = "bento_glass", accent_color: str = "#06b6d4", tab_cut_x: float = 0.0, parent=None):
        super().__init__(parent)
        self.theme_style = theme_style
        self.accent_color = accent_color
        self.tab_cut_x = tab_cut_x
        self._is_hovered = False
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.apply_theme(theme_style)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self._is_hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._is_hovered = False
        self.update()
        super().leaveEvent(event)

    def set_accent_color(self, color: str):
        self.accent_color = color
        self.update()

    def apply_theme(self, theme_style: str):
        self.theme_style = theme_style
        if theme_style == "cyberpunk_hud":
            self.setStyleSheet("""
                BentoCard {
                    background-color: transparent;
                    border: none;
                }
            """)
        elif theme_style == "minimalist_compact":
            self.setStyleSheet("""
                BentoCard {
                    background-color: #161822;
                    border: 1px solid #232736;
                    border-radius: 6px;
                }
                BentoCard:hover {
                    background-color: #1b1e2b;
                    border: 1px solid #333a4f;
                }
            """)
        else:  # bento_glass
            self.setStyleSheet("""
                BentoCard {
                    background-color: rgba(255, 255, 255, 0.04);
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 14px;
                }
                BentoCard:hover {
                    background-color: rgba(255, 255, 255, 0.065);
                    border: 1px solid rgba(255, 255, 255, 0.14);
                }
                BentoCard#gemini_card {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 rgba(16, 185, 129, 0.22),
                        stop:0.55 rgba(20, 140, 100, 0.12),
                        stop:1 rgba(245, 158, 11, 0.18));
                    border: 1px solid rgba(52, 211, 153, 0.28);
                    border-radius: 14px;
                }
                BentoCard#gemini_card:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 rgba(16, 185, 129, 0.28),
                        stop:0.55 rgba(20, 140, 100, 0.18),
                        stop:1 rgba(245, 158, 11, 0.24));
                    border: 1px solid rgba(52, 211, 153, 0.45);
                }
            """)

    def paintEvent(self, event):
        if self.theme_style == "cyberpunk_hud":
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            r = self.rect().adjusted(1, 1, -1, -1)
            accent = QColor(self.accent_color)
            alpha_border = 180 if self._is_hovered else 110
            pen_border = QPen(QColor(accent.red(), accent.green(), accent.blue(), alpha_border), 1.0)
            pen_corner = QPen(accent, 2.0)
            c_len = 8.0

            if self.tab_cut_x > 0:
                tab_w = min(float(r.width() - 35), float(self.tab_cut_x))
                cut_d = 12.0
                top_ledge_y = float(r.top() + cut_d)

                path = QPainterPath()
                path.moveTo(r.left() + 4.0, r.top())
                path.lineTo(r.left() + tab_w, r.top())
                path.lineTo(r.left() + tab_w + cut_d, top_ledge_y)
                path.lineTo(r.right() - 4.0, top_ledge_y)
                path.quadTo(r.right(), top_ledge_y, r.right(), top_ledge_y + 4.0)
                path.lineTo(r.right(), r.bottom() - 4.0)
                path.quadTo(r.right(), r.bottom(), r.right() - 4.0, r.bottom())
                path.lineTo(r.left() + 4.0, r.bottom())
                path.quadTo(r.left(), r.bottom(), r.left(), r.bottom() - 4.0)
                path.lineTo(r.left(), r.top() + 4.0)
                path.quadTo(r.left(), r.top(), r.left() + 4.0, r.top())

                painter.fillPath(path, QColor(7, 13, 23, 240))
                painter.setPen(pen_border)
                painter.drawPath(path)

                # Diagonal hash marks \\\\\\\\ on the ledge
                h_start = r.left() + tab_w + cut_d + 8.0
                h_end = r.right() - 40.0
                if h_end > h_start:
                    painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 140), 1.2))
                    sx = h_start
                    while sx < h_end:
                        painter.drawLine(int(sx), int(top_ledge_y - 2), int(sx + 5), int(top_ledge_y - 9))
                        sx += 7.0

                # Tactical brackets
                painter.setPen(pen_corner)
                painter.drawLine(int(r.left()), int(r.top() + c_len), int(r.left()), int(r.top()))
                painter.drawLine(int(r.left()), int(r.top()), int(r.left() + c_len), int(r.top()))
                painter.drawLine(int(r.right() - c_len), int(top_ledge_y), int(r.right()), int(top_ledge_y))
                painter.drawLine(int(r.right()), int(top_ledge_y), int(r.right()), int(top_ledge_y + c_len))
                painter.drawLine(int(r.left()), int(r.bottom() - c_len), int(r.left()), int(r.bottom()))
                painter.drawLine(int(r.left()), int(r.bottom()), int(r.left() + c_len), int(r.bottom()))
                painter.drawLine(int(r.right() - c_len), int(r.bottom()), int(r.right()), int(r.bottom()))
                painter.drawLine(int(r.right()), int(r.bottom()), int(r.right()), int(r.bottom() - c_len))
            else:
                path = QPainterPath()
                path.addRoundedRect(r, 4, 4)
                painter.fillPath(path, QColor(7, 13, 23, 240))
                painter.setPen(pen_border)
                painter.drawPath(path)

                painter.setPen(pen_corner)
                painter.drawLine(int(r.left()), int(r.top() + c_len), int(r.left()), int(r.top()))
                painter.drawLine(int(r.left()), int(r.top()), int(r.left() + c_len), int(r.top()))
                painter.drawLine(int(r.right() - c_len), int(r.top()), int(r.right()), int(r.top()))
                painter.drawLine(int(r.right()), int(r.top()), int(r.right()), int(r.top() + c_len))
                painter.drawLine(int(r.left()), int(r.bottom() - c_len), int(r.left()), int(r.bottom()))
                painter.drawLine(int(r.left()), int(r.bottom()), int(r.left() + c_len), int(r.bottom()))
                painter.drawLine(int(r.right() - c_len), int(r.bottom()), int(r.right()), int(r.bottom()))
                painter.drawLine(int(r.right()), int(r.bottom()), int(r.right()), int(r.bottom() - c_len))

            painter.end()
        else:
            super().paintEvent(event)


class BentoWindow(QWidget):
    close_requested = Signal()
    hide_requested = Signal()
    reload_requested = Signal()
    scale_changed = Signal(float)
    hotkey_changed = Signal(dict)
    position_changed = Signal(int, int)
    provider_setup_requested = Signal(str)
    ai_modules_changed = Signal(dict)
    theme_changed = Signal(str)
    content_mode_changed = Signal(str)
    size_changed = Signal()

    CONTENT_MODES = {"all": "Todo", "hardware": "Solo hardware", "fps": "Solo FPS", "quotas": "Solo cuotas"}

    _EXTENDED_PROVIDER_DEFS = {
        "openrouter": ("OpenRouter", "#10b981", "◈ OPENROUTER", "Credits balance"),
        "deepseek": ("DeepSeek", "#3b82f6", "⯁ DEEPSEEK", "API balance"),
        "kimi": ("Kimi K2", "#a855f7", "▲ KIMI K2", "Moonshot balance"),
        "perplexity": ("Perplexity", "#06b6d4", "◆ PERPLEXITY", "Pro subscription"),
    }

    def __init__(
        self,
        fan_aliases: dict | None = None,
        claude_provider=None,
        ui_scale: float = 1.0,
        ai_modules: dict | None = None,
        hotkey_config: dict | None = None,
        theme_style: str = "bento_glass",
        content_mode: str = "all",
    ):
        super().__init__()

        self.fan_aliases = fan_aliases or {
            "CPU": "CPU Fan",
            "CPU_OPT": "CPU Optional",
            "Chasis1": "Chassis 1",
            "GPU Ventilador": "GPU Fan",
        }
        self.claude_provider = claude_provider
        self.ui_scale = float(ui_scale or 1.0)
        self.content_mode = content_mode if content_mode in self.CONTENT_MODES else "all"
        self.theme_style = theme_style or "bento_glass"
        self.ai_modules = ai_modules or {
            "show_claude": False,
            "show_antigravity": True,
            "show_codex": True,
            "show_gemini": False,
            "show_copilot": True,
            "show_grok": True,
            "show_cursor": True,
        }
        self.hotkey_config = hotkey_config or {
            "modifiers": ["ctrl"],
            "key": "period",
        }

        self.card_display_modes: dict[str, int] = {}
        self.cached_provider_data: dict[str, dict] = {}
        self.last_hardware_data: dict = {}
        self._bento_fan_rows: dict[str, dict] = {}

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._drag_pos = None

        self._init_ui()
        self.update_hardware({})
        for p_id in self._EXTENDED_PROVIDER_DEFS:
            if self.ai_modules.get(f"show_{p_id}", False):
                self._ensure_ai_card(p_id)
        self.set_theme(self.theme_style, save=False)
        for name in self.ai_cards:
            self.update_quota_provider(name, {"status": ProviderStatus.LOADING})
        self.update_antigravity({"status": ProviderStatus.STALE})
        self.apply_scale(self.ui_scale, save=False)

    def _ensure_ai_card(self, provider_id: str):
        if provider_id in self.bento_ai_cards or provider_id not in self._EXTENDED_PROVIDER_DEFS:
            return
        title, color, cyber_tag, sub_text = self._EXTENDED_PROVIDER_DEFS[provider_id]

        # 1. Bento Card
        card = BentoCard("bento_glass")
        card.clicked.connect(lambda checked=False, name=provider_id: self._cycle_card_mode(name))
        box = QVBoxLayout(card)
        box.setContentsMargins(11, 8, 11, 8)
        box.setSpacing(1)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: 700; border: none; background: transparent;")
        dot = QLabel("")
        dot.setVisible(False)
        setup_btn = QPushButton("")
        setup_btn.setVisible(False)
        setup_btn.setStyleSheet("background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.4); border-radius: 4px; padding: 1px 6px; font-size: 9px; font-weight: 600;")
        setup_btn.clicked.connect(lambda checked=False, name=provider_id: self._provider_action(name))

        sub = QLabel(sub_text)
        sub.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 500; border: none; background: transparent;")
        box.addWidget(lbl_title)
        box.addWidget(sub)

        mid = QHBoxLayout()
        mid.setContentsMargins(0, 2, 0, 2)
        val = QLabel("--")
        val.setStyleSheet("color: #ffffff; font-size: 22px; font-weight: 800; border: none; background: transparent;")
        mid.addWidget(val)
        mid.addStretch()
        gauge = RingGaugeV3(size=44, stroke=4.0, arc_mode=True)
        gauge.setCustomColor(color)
        gauge.setValue(100.0)
        mid.addWidget(gauge)
        box.addLayout(mid)

        foot = QLabel("Active")
        foot.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 500; border: none; background: transparent;")
        pill = QLabel("")
        pill.setVisible(False)
        bot_row = QHBoxLayout()
        bot_row.addWidget(foot)
        bot_row.addStretch()
        bot_row.addWidget(pill)
        box.addLayout(bot_row)

        dot.setParent(card)
        setup_btn.setParent(card)

        self.bento_ai_cards[provider_id] = {
            "card": card,
            "title_label": lbl_title,
            "dot": dot,
            "setup": setup_btn,
            "subtitle": sub,
            "value": val,
            "gauge": gauge,
            "foot": foot,
            "pill": pill,
        }

        # 2. Cyberpunk Card
        c_card = BentoCard("cyberpunk_hud", accent_color=color)
        c_card.setFixedHeight(82)
        c_card.clicked.connect(lambda checked=False, name=provider_id: self._cycle_card_mode(name))
        c_box = QVBoxLayout(c_card)
        c_box.setContentsMargins(10, 8, 10, 8)
        c_box.setSpacing(3)
        top = QHBoxLayout()
        tag = QLabel(cyber_tag)
        tag.setStyleSheet("color: #ffffff; font-size: 9px; font-weight: 800; font-family: monospace;")
        top.addWidget(tag)
        top.addStretch()
        icon = QLabel("●")
        icon.setStyleSheet(f"color: {color}; font-size: 9px; font-weight: 800;")
        top.addWidget(icon)
        c_box.addLayout(top)
        seg = SegmentedBarWidget(segments=16, height=10, lit_color=color)
        c_box.addWidget(seg)
        c_val = QLabel("ACTIVE")
        c_val.setStyleSheet(f"color: {color}; font-size: 9px; font-weight: 700; font-family: monospace;")
        reset = QLabel("STATUS: OK")
        reset.setStyleSheet("color: #64748b; font-size: 8px; font-family: monospace;")
        c_box.addWidget(c_val)
        c_box.addWidget(reset)

        self.cyber_ai_cards[provider_id] = {
            "card": c_card,
            "tag": tag,
            "seg": seg,
            "val": c_val,
            "reset": reset,
            "status": None,
            "color": color,
        }

        # 3. Minimalist Row
        row = QWidget()
        r_box = QHBoxLayout(row)
        r_box.setContentsMargins(0, 1, 0, 1)
        r_box.setSpacing(6)
        m_lbl = QLabel(title)
        m_lbl.setStyleSheet("color: #f1f5f9; font-size: 11px; font-weight: 600; min-width: 65px;")
        bar = SlimProgressBarWidget(bar_height=3, bar_color=color)
        m_val = QLabel("--")
        m_val.setStyleSheet("font-size: 10px; min-width: 95px;")
        r_box.addWidget(m_lbl)
        r_box.addWidget(bar, 1)
        r_box.addWidget(m_val)
        self.mini_ai_layout.addWidget(row)

        self.mini_ai_rows[provider_id] = {
            "row": row,
            "lbl": m_lbl,
            "bar": bar,
            "val": m_val,
        }

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(14, 12, 14, 12)
        self.main_layout.setSpacing(10)

        # -------------------------------------------------------------
        # HEADER COMÚN
        # -------------------------------------------------------------
        self.header_widget = QWidget()
        self.header_layout = QHBoxLayout(self.header_widget)
        self.header_layout.setContentsMargins(2, 0, 2, 0)
        self.header_layout.setSpacing(8)

        title_box = QHBoxLayout()
        title_box.setSpacing(6)
        self.logo_dot = QLabel("●")
        self.logo_dot.setStyleSheet("color: #38bdf8; font-size: 8px;")
        self.title_label = QLabel("WIDGETS")
        self.title_label.setStyleSheet("color: #f8fafc; font-size: 12px; font-weight: 800; font-family: 'Segoe UI', Inter, sans-serif;")
        self.version_tag = QLabel("v3.2")
        self.version_tag.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 600;")

        title_box.addWidget(self.logo_dot)
        title_box.addWidget(self.title_label)
        title_box.addWidget(self.version_tag)
        self.header_layout.addLayout(title_box)

        initial_hotkey_text = format_hotkey_display(
            self.hotkey_config.get("modifiers", ["ctrl"]),
            self.hotkey_config.get("key", "period")
        )
        self.hotkey_badge = QPushButton(initial_hotkey_text)
        self.hotkey_badge.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.hotkey_badge.setToolTip("Haz clic para cambiar el atajo de teclado global")
        self.hotkey_badge.clicked.connect(self._open_hotkey_dialog)
        self.header_layout.addWidget(self.hotkey_badge)

        self.header_layout.addStretch()

        self.btn_min = QPushButton("—")
        self.btn_min.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_min.setToolTip("Ocultar ventana")
        self.btn_min.clicked.connect(self.hide_requested.emit)
        self.header_layout.addWidget(self.btn_min)

        self.btn_close = QPushButton("✕")
        self.btn_close.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_close.setToolTip("Cerrar aplicación")
        self.btn_close.clicked.connect(self._on_close_clicked)
        self.header_layout.addWidget(self.btn_close)

        self.main_layout.addWidget(self.header_widget)

        # -------------------------------------------------------------
        # 3 VISTAS ESPECÍFICAS DE CADA TEMA
        # -------------------------------------------------------------
        self.bento_view = QWidget()
        self.cyberpunk_view = QWidget()
        self.minimalist_view = QWidget()

        self._build_bento_view()
        self._build_cyberpunk_view()
        self._build_minimalist_view()

        self.main_layout.addWidget(self.bento_view)
        self.main_layout.addWidget(self.cyberpunk_view)
        self.main_layout.addWidget(self.minimalist_view)

        self.fps_only_label = QLabel("FPS --")
        self.fps_only_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fps_only_label.setStyleSheet("color: #ffffff; font-size: 28px; font-weight: 700; padding: 8px;")
        self.main_layout.addWidget(self.fps_only_label)

        # Labels de compatibilidad para verify_release.py
        self._last_top_proc_str = ""
        self.lbl_gpu_sub = _CompatibilityLabelProxy(self.bento_lbl_gpu_sub, extra_getter=lambda: self.bento_pill_fps.text())
        self.lbl_ram_sub = _CompatibilityLabelProxy(self.bento_lbl_ram_sub, extra_getter=lambda: self._last_top_proc_str)
        self.ai_cards = self.bento_ai_cards

    # =================================================================
    # 1. CONSTRUCCIÓN DE LA VISTA: BENTO GLASSMORPHISM
    # =================================================================
    def _build_bento_view(self):
        layout = QVBoxLayout(self.bento_view)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # AI Section Label (oculto en Bento para limpieza visual idéntica a la maqueta)
        self.bento_ai_label = QLabel("CUOTAS DE IA")
        self.bento_ai_label.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700; margin-left: 2px;")
        self.bento_ai_label.setVisible(False)
        layout.addWidget(self.bento_ai_label)

        # AI Grid (2x2)
        self.bento_ai_grid = QGridLayout()
        self.bento_ai_grid.setContentsMargins(0, 0, 0, 0)
        self.bento_ai_grid.setSpacing(6)

        # Claude card (opcional)
        self.bento_card_claude = BentoCard("bento_glass")
        self.bento_card_claude.clicked.connect(lambda: self._cycle_card_mode("claude"))
        self.bento_card_claude.setCursor(Qt.CursorShape.PointingHandCursor)
        c_box = QVBoxLayout(self.bento_card_claude)
        c_box.setContentsMargins(11, 8, 11, 8)
        c_box.setSpacing(1)
        self.bento_lbl_claude_title = QLabel("Claude Code")
        self.bento_lbl_claude_title.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: 700; border: none; background: transparent;")
        self.bento_sub_claude = QLabel("Cuota 5h")
        self.bento_sub_claude.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 500; border: none; background: transparent;")
        c_box.addWidget(self.bento_lbl_claude_title)
        c_box.addWidget(self.bento_sub_claude)
        self.bento_dot_claude = QLabel("")
        self.bento_dot_claude.setVisible(False)
        self.bento_btn_claude = QPushButton("")
        self.bento_btn_claude.setVisible(False)

        c_mid = QHBoxLayout()
        c_mid.setContentsMargins(0, 1, 0, 1)
        c_mid.setSpacing(4)

        c_left = QVBoxLayout()
        c_left.setSpacing(1)
        self.bento_val_claude = QLabel("--")
        self.bento_val_claude.setStyleSheet("color: #ffffff; font-size: 26px; font-weight: 800; border: none; background: transparent;")
        self.bento_foot_claude = QLabel("live countdown")
        self.bento_foot_claude.setStyleSheet("color: #94a3b8; font-size: 9.5px; font-weight: 500; border: none; background: transparent;")
        c_left.addWidget(self.bento_val_claude)
        c_left.addWidget(self.bento_foot_claude)
        c_mid.addLayout(c_left)
        c_mid.addStretch()

        c_right = QVBoxLayout()
        c_right.setSpacing(1)
        c_right.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.bento_gauge_claude = RingGaugeV3(size=44, stroke=4.0, arc_mode=True)
        self.bento_gauge_claude.setCustomColor("#f59e0b")
        self.bento_gauge_claude.setValue(0.0)
        self.bento_pill_claude = QLabel("--")
        self.bento_pill_claude.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bento_pill_claude.setStyleSheet(
            "background: rgba(0, 0, 0, 0.45); border: 1px solid rgba(255, 255, 255, 0.1); "
            "color: #fef3c7; border-radius: 8px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
        )
        c_right.addWidget(self.bento_gauge_claude, alignment=Qt.AlignmentFlag.AlignCenter)
        c_right.addWidget(self.bento_pill_claude, alignment=Qt.AlignmentFlag.AlignCenter)
        c_mid.addLayout(c_right)

        c_box.addLayout(c_mid)
        self.bento_dot_claude.setParent(self.bento_card_claude)
        self.bento_btn_claude.setParent(self.bento_card_claude)

        # 1. Antigravity Card - Top Left
        self.bento_card_ag = BentoCard("bento_glass")
        self.bento_card_ag.setObjectName("gemini_card")
        self.bento_card_ag.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bento_card_ag.clicked.connect(lambda: self._cycle_card_mode("antigravity"))
        ag_box = QVBoxLayout(self.bento_card_ag)
        ag_box.setContentsMargins(11, 8, 11, 8)
        ag_box.setSpacing(1)

        self.bento_lbl_ag_title = QLabel("Antigravity")
        self.bento_lbl_ag_title.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: 700; border: none; background: transparent;")
        self.bento_sub_ag = QLabel("Cuota 5h")
        self.bento_sub_ag.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 500; border: none; background: transparent;")
        self.bento_dot_ag = QLabel("")
        self.bento_dot_ag.setVisible(False)
        ag_box.addWidget(self.bento_lbl_ag_title)
        ag_box.addWidget(self.bento_sub_ag)
        self.bento_dot_ag.setParent(self.bento_card_ag)

        ag_mid = QHBoxLayout()
        ag_mid.setContentsMargins(0, 1, 0, 1)
        ag_mid.setSpacing(4)

        ag_left = QVBoxLayout()
        ag_left.setSpacing(1)
        self.bento_val_ag = QLabel("--")
        self.bento_val_ag.setStyleSheet("color: #ffffff; font-size: 26px; font-weight: 800; border: none; background: transparent;")
        self.bento_foot_ag = QLabel("sync required")
        self.bento_foot_ag.setStyleSheet("color: #94a3b8; font-size: 9.5px; font-weight: 500; border: none; background: transparent;")
        ag_left.addWidget(self.bento_val_ag)
        ag_left.addWidget(self.bento_foot_ag)
        ag_mid.addLayout(ag_left)
        ag_mid.addStretch()

        ag_right = QVBoxLayout()
        ag_right.setSpacing(1)
        ag_right.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.bento_gauge_ag = RingGaugeV3(size=44, stroke=4.0, arc_mode=True)
        self.bento_gauge_ag.setValue(0.0)
        self.bento_pill_ag = QLabel("--")
        self.bento_pill_ag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bento_pill_ag.setStyleSheet(
            "background: rgba(0, 0, 0, 0.45); border: 1px solid rgba(255, 255, 255, 0.1); "
            "color: #fef3c7; border-radius: 8px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
        )
        ag_right.addWidget(self.bento_gauge_ag, alignment=Qt.AlignmentFlag.AlignCenter)
        ag_right.addWidget(self.bento_pill_ag, alignment=Qt.AlignmentFlag.AlignCenter)
        ag_mid.addLayout(ag_right)

        ag_box.addLayout(ag_mid)

        # Quota cards (Codex, Copilot, Grok, Gemini CLI, Cursor)
        self.bento_ai_cards = {}
        for provider_id, title in (
            ("codex", "Codex Plus"),
            ("gemini", "Gemini CLI"),
            ("copilot", "GitHub Copilot"),
            ("grok", "Grok"),
            ("cursor", "Cursor AI"),
        ):
            card = BentoCard("bento_glass")
            if provider_id == "gemini":
                card.setCursor(Qt.CursorShape.ArrowCursor)
            else:
                card.clicked.connect(lambda checked=False, name=provider_id: self._cycle_card_mode(name))
            box = QVBoxLayout(card)
            box.setContentsMargins(11, 8, 11, 8)
            box.setSpacing(1)

            lbl_title = QLabel(title)
            lbl_title.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: 700; border: none; background: transparent;")
            dot = QLabel("")
            dot.setVisible(False)
            setup_btn = QPushButton("")
            setup_btn.setVisible(False)
            setup_btn.setStyleSheet("background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.4); border-radius: 4px; padding: 1px 6px; font-size: 9px; font-weight: 600;")
            setup_btn.clicked.connect(lambda checked=False, name=provider_id: self._provider_action(name))

            if provider_id == "codex":
                # Codex Plus: Top Right
                sub = QLabel("Cuota 5h")
                sub.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 500; border: none; background: transparent;")
                box.addWidget(lbl_title)
                box.addWidget(sub)

                mid = QHBoxLayout()
                mid.setContentsMargins(0, 1, 0, 1)
                mid.setSpacing(4)

                col_left = QVBoxLayout()
                col_left.setSpacing(1)
                val = QLabel("--")
                val.setStyleSheet("color: #ffffff; font-size: 26px; font-weight: 800; border: none; background: transparent;")
                foot = QLabel("live countdown")
                foot.setStyleSheet("color: #94a3b8; font-size: 9.5px; font-weight: 500; border: none; background: transparent;")
                col_left.addWidget(val)
                col_left.addWidget(foot)
                mid.addLayout(col_left)
                mid.addStretch()

                col_right = QVBoxLayout()
                col_right.setSpacing(1)
                col_right.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                gauge = RingGaugeV3(size=44, stroke=4.0, arc_mode=True)
                gauge.setCustomColor("#84cc16")
                gauge.setValue(0.0)
                pill = QLabel("--")
                pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
                pill.setStyleSheet(
                    "background: rgba(0, 0, 0, 0.45); border: 1px solid rgba(255, 255, 255, 0.1); "
                    "color: #fef3c7; border-radius: 8px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
                )
                col_right.addWidget(gauge, alignment=Qt.AlignmentFlag.AlignCenter)
                col_right.addWidget(pill, alignment=Qt.AlignmentFlag.AlignCenter)
                mid.addLayout(col_right)

                box.addLayout(mid)

            elif provider_id == "copilot":
                # GitHub Copilot: Bottom Left
                box.addWidget(lbl_title)

                mid = QHBoxLayout()
                mid.setContentsMargins(0, 1, 0, 1)
                mid.setSpacing(4)

                col_left = QVBoxLayout()
                col_left.setSpacing(1)
                val = QLabel("--")
                val.setStyleSheet("color: #ffffff; font-size: 22px; font-weight: 800; border: none; background: transparent;")
                sub = QLabel("premium used")
                sub.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 500; border: none; background: transparent;")
                col_left.addWidget(val)
                col_left.addWidget(sub)
                mid.addLayout(col_left)
                mid.addStretch()

                col_right = QVBoxLayout()
                col_right.setSpacing(1)
                col_right.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                gauge = RingGaugeV3(size=44, stroke=4.0, arc_mode=True)
                gauge.setCustomColor("#f59e0b")
                gauge.setValue(96.5)
                foot = QLabel("reset 1 Oct")
                foot.setAlignment(Qt.AlignmentFlag.AlignCenter)
                foot.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 500; border: none; background: transparent;")
                col_right.addWidget(gauge, alignment=Qt.AlignmentFlag.AlignCenter)
                col_right.addWidget(foot, alignment=Qt.AlignmentFlag.AlignCenter)
                mid.addLayout(col_right)

                box.addLayout(mid)
                pill = QLabel("")
                pill.setVisible(False)

            elif provider_id == "grok":
                # Grok: Bottom Right (Clean Glass interior)
                sub = QLabel("--")
                sub.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 500; border: none; background: transparent;")
                box.addWidget(lbl_title)
                box.addWidget(sub)

                val = QLabel("")
                val.setVisible(False)
                val.setStyleSheet("color: #ffffff; font-size: 26px; font-weight: 800; border: none; background: transparent;")
                gauge = RingGaugeV3(size=44, stroke=4.0, arc_mode=True)
                gauge.setVisible(False)
                foot = QLabel("")
                foot.setVisible(False)
                pill = QLabel("")
                pill.setVisible(False)
                mid = QHBoxLayout()
                mid.addWidget(val)
                mid.addStretch()
                mid.addWidget(gauge)
                box.addLayout(mid)
                bot_row = QHBoxLayout()
                bot_row.addWidget(foot)
                bot_row.addStretch()
                bot_row.addWidget(pill)
                box.addLayout(bot_row)
                box.addStretch()

            elif provider_id == "cursor":
                # Cursor AI: Fast Requests
                box.addWidget(lbl_title)

                mid = QHBoxLayout()
                mid.setContentsMargins(0, 1, 0, 1)
                mid.setSpacing(4)

                col_left = QVBoxLayout()
                col_left.setSpacing(1)
                val = QLabel("--")
                val.setStyleSheet("color: #ffffff; font-size: 22px; font-weight: 800; border: none; background: transparent;")
                sub = QLabel("fast requests")
                sub.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 500; border: none; background: transparent;")
                col_left.addWidget(val)
                col_left.addWidget(sub)
                mid.addLayout(col_left)
                mid.addStretch()

                col_right = QVBoxLayout()
                col_right.setSpacing(1)
                col_right.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                gauge = RingGaugeV3(size=44, stroke=4.0, arc_mode=True)
                gauge.setCustomColor("#8b5cf6")
                gauge.setValue(100.0)
                foot = QLabel("--")
                foot.setAlignment(Qt.AlignmentFlag.AlignCenter)
                foot.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 500; border: none; background: transparent;")
                col_right.addWidget(gauge, alignment=Qt.AlignmentFlag.AlignCenter)
                col_right.addWidget(foot, alignment=Qt.AlignmentFlag.AlignCenter)
                mid.addLayout(col_right)

                box.addLayout(mid)
                pill = QLabel("")
                pill.setVisible(False)

            else:
                sub = QLabel("Remaining quota")
                sub.setStyleSheet("color: #64748b; font-size: 10px; border: none; background: transparent;")
                box.addWidget(lbl_title)
                box.addWidget(sub)

                mid = QHBoxLayout()
                mid.setContentsMargins(0, 2, 0, 2)
                val = QLabel("--")
                val.setStyleSheet("color: #ffffff; font-size: 22px; font-weight: 800; border: none; background: transparent;")
                mid.addWidget(val)
                mid.addStretch()
                gauge = RingGaugeV3(size=44, stroke=4.0, arc_mode=True)
                mid.addWidget(gauge)
                box.addLayout(mid)

                foot = QLabel("resets")
                foot.setStyleSheet("color: #64748b; font-size: 10px; border: none; background: transparent;")
                pill = QLabel("Active")
                pill.setStyleSheet("background: rgba(245, 158, 11, 0.18); color: #fbbf24; border-radius: 6px; padding: 2px 6px; font-size: 8px; font-weight: 700;")
                bot_row = QHBoxLayout()
                bot_row.addWidget(foot)
                bot_row.addStretch()
                bot_row.addWidget(pill)
                box.addLayout(bot_row)

            dot.setParent(card)
            setup_btn.setParent(card)
            if pill.parentWidget() is None:
                pill.setParent(card)

            self.bento_ai_cards[provider_id] = {
                "card": card,
                "title_label": lbl_title,
                "dot": dot,
                "setup": setup_btn,
                "subtitle": sub,
                "value": val,
                "gauge": gauge,
                "foot": foot,
                "pill": pill,
            }

        layout.addLayout(self.bento_ai_grid)

        self.bento_hw_container = QWidget()
        layout.addWidget(self.bento_hw_container)
        layout = QVBoxLayout(self.bento_hw_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Hardware Section Label
        self.bento_hw_label = QLabel("Hardware Telemetry")
        self.bento_hw_label.setStyleSheet("color: #cbd5e1; font-size: 12px; font-weight: 700; margin-left: 2px; margin-top: 4px; margin-bottom: 2px;")
        layout.addWidget(self.bento_hw_label)

        # Hardware Cards (4 Full Width Cards)
        # 1. CPU Card
        self.bento_card_cpu = BentoCard("bento_glass")
        cpu_box = QVBoxLayout(self.bento_card_cpu)
        cpu_box.setContentsMargins(11, 8, 11, 8)
        cpu_box.setSpacing(2)
        cpu_top = QHBoxLayout()
        self.bento_lbl_cpu_name = QLabel("CPU")
        self.bento_lbl_cpu_name.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: 700; border: none; background: transparent;")
        self.bento_lbl_cpu_temp = QLabel("-- °C")
        self.bento_lbl_cpu_temp.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: 800; border: none; background: transparent;")
        cpu_top.addWidget(self.bento_lbl_cpu_name)
        cpu_top.addStretch()
        cpu_top.addWidget(self.bento_lbl_cpu_temp)
        cpu_box.addLayout(cpu_top)

        self.bento_lbl_cpu_util = QLabel("Utilization: --")
        self.bento_lbl_cpu_util.setStyleSheet("color: #94a3b8; font-size: 9.5px; font-weight: 500; border: none; background: transparent;")
        cpu_box.addWidget(self.bento_lbl_cpu_util)

        self.bento_spark_cpu = SparklineWidget(height=32, line_color="#cbd5e1", fill_alpha=55)
        cpu_box.addWidget(self.bento_spark_cpu)
        layout.addWidget(self.bento_card_cpu)

        # 2. GPU Card
        self.bento_card_gpu = BentoCard("bento_glass")
        gpu_box = QVBoxLayout(self.bento_card_gpu)
        gpu_box.setContentsMargins(11, 8, 11, 8)
        gpu_box.setSpacing(2)
        gpu_top = QHBoxLayout()
        self.bento_lbl_gpu_name = QLabel("GPU")
        self.bento_lbl_gpu_name.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: 700; border: none; background: transparent;")
        self.bento_lbl_gpu_temp = QLabel("-- °C")
        self.bento_lbl_gpu_temp.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: 800; border: none; background: transparent;")
        gpu_top.addWidget(self.bento_lbl_gpu_name)
        gpu_top.addStretch()
        gpu_top.addWidget(self.bento_lbl_gpu_temp)
        gpu_box.addLayout(gpu_top)

        self.bento_lbl_gpu_sub = QLabel("Utilization: --")
        self.bento_lbl_gpu_sub.setStyleSheet("color: #94a3b8; font-size: 9.5px; font-weight: 500; border: none; background: transparent;")
        gpu_box.addWidget(self.bento_lbl_gpu_sub)

        # Sparkline with floating live FPS pill overlay
        spark_container = QWidget()
        spark_layout = QGridLayout(spark_container)
        spark_layout.setContentsMargins(0, 0, 0, 0)
        self.bento_spark_gpu = SparklineWidget(height=32, line_color="#cbd5e1", fill_alpha=55)
        spark_layout.addWidget(self.bento_spark_gpu, 0, 0)

        self.bento_pill_fps = QLabel("FPS --")
        self.bento_pill_fps.setStyleSheet(
            "background: rgba(28, 34, 44, 0.92); border: 1px solid rgba(255, 255, 255, 0.12); "
            "color: #ffffff; border-radius: 7px; padding: 1px 7px; font-size: 10px; font-weight: 700;"
        )
        spark_layout.addWidget(self.bento_pill_fps, 0, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.bento_pill_fps.raise_()

        gpu_box.addWidget(spark_container)
        layout.addWidget(self.bento_card_gpu)

        # 3. RAM Card
        self.bento_card_ram = BentoCard("bento_glass")
        ram_box = QVBoxLayout(self.bento_card_ram)
        ram_box.setContentsMargins(11, 8, 11, 8)
        ram_box.setSpacing(4)
        ram_top = QHBoxLayout()
        self.bento_lbl_ram_title = QLabel("RAM Usage")
        self.bento_lbl_ram_title.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: 700; border: none; background: transparent;")
        self.bento_lbl_ram_sub = QLabel("-- GB / -- GB")
        self.bento_lbl_ram_sub.setStyleSheet("color: #ffffff; font-size: 12px; font-weight: 700; border: none; background: transparent;")
        ram_top.addWidget(self.bento_lbl_ram_title)
        ram_top.addStretch()
        ram_top.addWidget(self.bento_lbl_ram_sub)
        ram_box.addLayout(ram_top)

        self.bento_bar_ram = SlimProgressBarWidget(
            bar_height=14,
            track_color="#1e242d",
            gradient_colors=[(0.0, "#7ea193"), (0.55, "#a8c7b8"), (1.0, "#dce7e1")]
        )
        self.bento_bar_ram.setValue(93.0)
        ram_box.addWidget(self.bento_bar_ram)
        layout.addWidget(self.bento_card_ram)

        # 4. Cooling Fans Card
        self.bento_card_fans = BentoCard("bento_glass")
        fans_box = QVBoxLayout(self.bento_card_fans)
        fans_box.setContentsMargins(11, 8, 11, 8)
        fans_box.setSpacing(6)
        self.bento_lbl_fans_title = QLabel("Cooling Fans")
        self.bento_lbl_fans_title.setStyleSheet("color: #ffffff; font-size: 12px; font-weight: 700; border: none; background: transparent;")
        fans_box.addWidget(self.bento_lbl_fans_title)

        self.bento_fans_container = QWidget()
        self.bento_fans_layout = QVBoxLayout(self.bento_fans_container)
        self.bento_fans_layout.setContentsMargins(0, 0, 0, 0)
        self.bento_fans_layout.setSpacing(6)
        fans_box.addWidget(self.bento_fans_container)
        layout.addWidget(self.bento_card_fans)

    # =================================================================
    # 2. CONSTRUCCIÓN DE LA VISTA: CYBERPUNK HUD
    # =================================================================
    def _build_cyberpunk_view(self):
        layout = QVBoxLayout(self.cyberpunk_view)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 2x2 AI Grid Tactical
        self.cyber_ai_grid = QGridLayout()
        self.cyber_ai_grid.setContentsMargins(0, 0, 0, 0)
        self.cyber_ai_grid.setSpacing(6)

        # Claude tactical card
        self.cyber_card_claude = BentoCard("cyberpunk_hud", accent_color="#f59e0b")
        self.cyber_card_claude.clicked.connect(lambda: self._cycle_card_mode("claude"))
        cc_box = QVBoxLayout(self.cyber_card_claude)
        cc_box.setContentsMargins(10, 8, 10, 8)
        cc_box.setSpacing(3)
        cc_top = QHBoxLayout()
        self.cyber_lbl_claude_tag = QLabel("[ CLAUDE CODE 🔒 ]")
        self.cyber_lbl_claude_tag.setStyleSheet("color: #f59e0b; font-size: 9px; font-weight: 800; font-family: monospace;")
        cc_top.addWidget(self.cyber_lbl_claude_tag)
        cc_top.addStretch()
        cc_box.addLayout(cc_top)
        self.cyber_seg_claude = SegmentedBarWidget(segments=16, height=10, lit_color="#f59e0b")
        cc_box.addWidget(self.cyber_seg_claude)
        self.cyber_lbl_claude_val = QLabel("0% QUOTA USED")
        self.cyber_lbl_claude_val.setStyleSheet("color: #f59e0b; font-size: 9px; font-weight: 700; font-family: monospace;")
        self.cyber_lbl_claude_reset = QLabel("RESET: 5h Window")
        self.cyber_lbl_claude_reset.setStyleSheet("color: #64748b; font-size: 8px; font-family: monospace;")
        cc_box.addWidget(self.cyber_lbl_claude_val)
        cc_box.addWidget(self.cyber_lbl_claude_reset)

        # Antigravity tactical card
        self.cyber_card_ag = BentoCard("cyberpunk_hud", accent_color="#06b6d4")
        self.cyber_card_ag.setFixedHeight(82)
        self.cyber_card_ag.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cyber_card_ag.clicked.connect(lambda: self._cycle_card_mode("antigravity"))
        cag_box = QVBoxLayout(self.cyber_card_ag)
        cag_box.setContentsMargins(10, 8, 10, 8)
        cag_box.setSpacing(3)
        cag_top = QHBoxLayout()
        self.cyber_lbl_ag_tag = QLabel("✦ ANTIGRAVITY")
        self.cyber_lbl_ag_tag.setStyleSheet("color: #ffffff; font-size: 9px; font-weight: 800; font-family: monospace;")
        self.cyber_lbl_ag_lock = QLabel("🔒")
        self.cyber_lbl_ag_lock.setStyleSheet("color: #06b6d4; font-size: 9px;")
        cag_top.addWidget(self.cyber_lbl_ag_tag)
        cag_top.addStretch()
        cag_top.addWidget(self.cyber_lbl_ag_lock)
        cag_box.addLayout(cag_top)
        self.cyber_seg_ag = SegmentedBarWidget(segments=16, height=12, lit_color="#06b6d4")
        cag_box.addWidget(self.cyber_seg_ag)
        self.cyber_lbl_ag_val = QLabel("NO VERIFIED DATA")
        self.cyber_lbl_ag_val.setStyleSheet("color: #06b6d4; font-size: 9px; font-weight: 800; font-family: monospace;")
        self.cyber_lbl_ag_reset = QLabel("SYNC: ANTIGRAVITY")
        self.cyber_lbl_ag_reset.setStyleSheet("color: #94a3b8; font-size: 8px; font-family: monospace;")
        cag_box.addWidget(self.cyber_lbl_ag_val)
        cag_box.addWidget(self.cyber_lbl_ag_reset)

        # Quota cards cyber (Codex, Gemini CLI, Copilot, Grok, Cursor)
        self.cyber_ai_cards = {}
        for p_id, p_tag, p_col, is_grad in (
            ("codex", "✴ CODEX PLUS", "#84cc16", False),
            ("gemini", "✦ GEMINI CLI", "#06b6d4", False),
            ("copilot", "◆ COPILOT PREMIUM", "#f59e0b", True),
            ("grok", "⧄ GROK", "#06b6d4", False),
            ("cursor", "⮞ CURSOR AI", "#8b5cf6", False),
        ):
            accent = "#84cc16" if p_id == "codex" else ("#8b5cf6" if p_id == "cursor" else "#06b6d4")
            c_card = BentoCard("cyberpunk_hud", accent_color=accent)
            c_card.setFixedHeight(82)
            if p_id == "gemini":
                c_card.setCursor(Qt.CursorShape.ArrowCursor)
            else:
                c_card.setCursor(Qt.CursorShape.PointingHandCursor)
                c_card.clicked.connect(lambda checked=False, name=p_id: self._cycle_card_mode(name))
            box = QVBoxLayout(c_card)
            box.setContentsMargins(10, 8, 10, 8)
            box.setSpacing(3)
            top = QHBoxLayout()
            tag = QLabel(p_tag)
            tag.setStyleSheet("color: #ffffff; font-size: 9px; font-weight: 800; font-family: monospace;")
            top.addWidget(tag)
            top.addStretch()

            status_lbl = None
            if p_id == "codex":
                icon = QLabel("🔒")
                icon.setStyleSheet("color: #84cc16; font-size: 9px; font-weight: 800;")
                top.addWidget(icon)
                box.addLayout(top)
                seg = SegmentedBarWidget(segments=16, height=10, lit_color="#84cc16")
                box.addWidget(seg)
                val = QLabel("--")
                val.setStyleSheet("color: #84cc16; font-size: 9px; font-weight: 800; font-family: monospace;")
                reset = QLabel("Actualizando")
                reset.setStyleSheet("color: #94a3b8; font-size: 8px; font-family: monospace;")
                box.addWidget(val)
                box.addWidget(reset)
            elif p_id == "copilot":
                icon = QLabel("🔒")
                icon.setStyleSheet("color: #06b6d4; font-size: 9px; font-weight: 800;")
                top.addWidget(icon)
                box.addLayout(top)
                seg = SegmentedBarWidget(segments=20, height=10, is_gradient=True)
                box.addWidget(seg)
                val = QLabel("QUOTA: --")
                val.setStyleSheet("color: #f59e0b; font-size: 9px; font-weight: 800; font-family: monospace;")
                reset = QLabel("RESET DATE: 1 OCT 2026")
                reset.setStyleSheet("color: #f59e0b; font-size: 8px; font-weight: 700; font-family: monospace;")
                box.addWidget(val)
                box.addWidget(reset)
            elif p_id == "grok":
                icon = QLabel("☰")
                icon.setStyleSheet("color: #06b6d4; font-size: 9px; font-weight: 800;")
                top.addWidget(icon)
                box.addLayout(top)
                status_lbl = QLabel("IDLE")
                status_lbl.setStyleSheet("color: #f1f5f9; font-size: 15px; font-weight: 800; font-family: monospace;")
                box.addWidget(status_lbl)
                seg = SegmentedBarWidget(segments=16, height=10, lit_color="#06b6d4")
                seg.setVisible(False)
                box.addWidget(seg)
                val = QLabel("PLAN: FREE WEB")
                val.setStyleSheet("color: #94a3b8; font-size: 9px; font-weight: 700; font-family: monospace;")
                reset = QLabel("RESET: --")
                reset.setStyleSheet("color: #94a3b8; font-size: 8px; font-family: monospace;")
                box.addWidget(val)
                box.addWidget(reset)
            elif p_id == "cursor":
                icon = QLabel("🔒")
                icon.setStyleSheet("color: #8b5cf6; font-size: 9px; font-weight: 800;")
                top.addWidget(icon)
                box.addLayout(top)
                status_lbl = QLabel("ACTIVE")
                status_lbl.setStyleSheet("color: #a855f7; font-size: 15px; font-weight: 800; font-family: monospace;")
                box.addWidget(status_lbl)
                seg = SegmentedBarWidget(segments=16, height=10, lit_color="#8b5cf6")
                seg.setVisible(False)
                box.addWidget(seg)
                val = QLabel("QUOTA: --")
                val.setStyleSheet("color: #ffffff; font-size: 8px; font-weight: 700; font-family: 'Segoe UI', sans-serif;")
                reset = QLabel("RESET: --")
                reset.setStyleSheet("color: #a855f7; font-size: 8px; font-weight: 700; font-family: monospace;")
                box.addWidget(val)
                box.addWidget(reset)
            else:
                icon = QLabel("⬡")
                icon.setStyleSheet("color: #06b6d4; font-size: 9px;")
                top.addWidget(icon)
                box.addLayout(top)
                seg = SegmentedBarWidget(segments=16, height=10, lit_color=p_col)
                box.addWidget(seg)
                val = QLabel("ACTIVE")
                val.setStyleSheet(f"color: {p_col}; font-size: 9px; font-weight: 700; font-family: monospace;")
                reset = QLabel("RESET: --")
                reset.setStyleSheet("color: #64748b; font-size: 8px; font-family: monospace;")
                box.addWidget(val)
                box.addWidget(reset)

            self.cyber_ai_cards[p_id] = {
                "card": c_card,
                "tag": tag,
                "seg": seg,
                "val": val,
                "reset": reset,
                "status": status_lbl,
                "color": p_col,
            }

        layout.addLayout(self.cyber_ai_grid)

        self.cyber_hw_container = QWidget()
        layout.addWidget(self.cyber_hw_container)
        layout = QVBoxLayout(self.cyber_hw_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Hardware Section Card (combines CPU + GPU in one unified Cyberpunk card)
        self.cyber_card_hw = BentoCard("cyberpunk_hud", accent_color="#06b6d4", tab_cut_x=185.0)
        self.cyber_card_hw.setFixedHeight(218)
        hw_box = QVBoxLayout(self.cyber_card_hw)
        hw_box.setContentsMargins(10, 8, 10, 8)
        hw_box.setSpacing(6)

        hw_head = QHBoxLayout()
        self.cyber_lbl_hw_title = QLabel("SYSTEM HARDWARE STATUS")
        self.cyber_lbl_hw_title.setStyleSheet("color: #ffffff; font-size: 10px; font-weight: 800; font-family: monospace;")
        self.cyber_lbl_hw_hazard = QLabel("\\\\\\\\\\\\\\\\ ⬡ ⛶")
        self.cyber_lbl_hw_hazard.setStyleSheet("color: #0891b2; font-size: 9px; font-family: monospace;")
        hw_head.addWidget(self.cyber_lbl_hw_title)
        hw_head.addStretch()
        hw_head.addWidget(self.cyber_lbl_hw_hazard)
        hw_box.addLayout(hw_head)

        # 1. CPU Tactical Sub-section
        c_cpu_head = QHBoxLayout()
        self.cyber_lbl_cpu_name = QLabel("CPU")
        self.cyber_lbl_cpu_name.setStyleSheet("color: #ecfeff; font-size: 11px; font-weight: 800; font-family: monospace;")
        self.cyber_lbl_cpu_chip = QLabel("CPU ▮▮▮▮▮▮▮ ⬡")
        self.cyber_lbl_cpu_chip.setStyleSheet("color: #06b6d4; font-size: 9px; font-family: monospace;")
        c_cpu_head.addWidget(self.cyber_lbl_cpu_name)
        c_cpu_head.addStretch()
        c_cpu_head.addWidget(self.cyber_lbl_cpu_chip)
        hw_box.addLayout(c_cpu_head)

        c_cpu_mid = QHBoxLayout()
        c_cpu_mid.setContentsMargins(0, 0, 0, 0)
        c_cpu_mid.setSpacing(6)

        c_cpu_left = QVBoxLayout()
        c_cpu_left.setSpacing(2)
        c_cpu_l_box = QHBoxLayout()
        self.cyber_lbl_cpu_load = QLabel("12.3%")
        self.cyber_lbl_cpu_load.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: 800; font-family: 'Segoe UI', 'Consolas', sans-serif;")
        c_cpu_load_sub = QLabel("LOAD")
        c_cpu_load_sub.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700; font-family: 'Segoe UI', sans-serif; padding-bottom: 2px;")
        c_cpu_l_box.addWidget(self.cyber_lbl_cpu_load)
        c_cpu_l_box.addWidget(c_cpu_load_sub, 0, Qt.AlignmentFlag.AlignBottom)
        c_cpu_l_box.addStretch()
        c_cpu_left.addLayout(c_cpu_l_box)
        self.cyber_seg_cpu = SegmentedBarWidget(segments=16, height=11, lit_color="#06b6d4")
        c_cpu_left.addWidget(self.cyber_seg_cpu)
        c_cpu_mid.addLayout(c_cpu_left, 46)

        c_cpu_c2 = QVBoxLayout()
        c_cpu_c2.setSpacing(2)
        self.cyber_lbl_cpu_temp = QLabel("58°C")
        self.cyber_lbl_cpu_temp.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: 800; font-family: 'Segoe UI', 'Consolas', sans-serif;")
        c_cpu_c2.addWidget(self.cyber_lbl_cpu_temp)
        self.cyber_spark_cpu_temp = SparklineWidget(height=22, line_color="#06b6d4", fill_alpha=55)
        c_cpu_c2.addWidget(self.cyber_spark_cpu_temp)
        c_cpu_mid.addLayout(c_cpu_c2, 27)

        c_cpu_div = QFrame()
        c_cpu_div.setFixedWidth(1)
        c_cpu_div.setStyleSheet("background: #0e2238;")
        c_cpu_mid.addWidget(c_cpu_div)

        c_cpu_c3 = QVBoxLayout()
        c_cpu_c3.setSpacing(2)
        c_cpu_p_box = QHBoxLayout()
        self.cyber_lbl_cpu_pwr = QLabel("65W")
        self.cyber_lbl_cpu_pwr.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: 800; font-family: 'Segoe UI', 'Consolas', sans-serif;")
        c_cpu_pwr_sub = QLabel("POWER")
        c_cpu_pwr_sub.setStyleSheet("color: #64748b; font-size: 8px; font-weight: 700; font-family: 'Segoe UI', sans-serif; padding-bottom: 2px;")
        c_cpu_p_box.addWidget(self.cyber_lbl_cpu_pwr)
        c_cpu_p_box.addWidget(c_cpu_pwr_sub, 0, Qt.AlignmentFlag.AlignBottom)
        c_cpu_p_box.addStretch()
        c_cpu_c3.addLayout(c_cpu_p_box)
        self.cyber_spark_cpu_pwr = SparklineWidget(height=22, line_color="#06b6d4", fill_alpha=40)
        c_cpu_c3.addWidget(self.cyber_spark_cpu_pwr)
        c_cpu_mid.addLayout(c_cpu_c3, 27)

        hw_box.addLayout(c_cpu_mid)

        div_hw = QFrame()
        div_hw.setFixedHeight(1)
        div_hw.setStyleSheet("background: #0e2238;")
        hw_box.addWidget(div_hw)

        # 2. GPU Tactical Sub-section
        c_gpu_head = QHBoxLayout()
        self.cyber_lbl_gpu_name = QLabel("GPU")
        self.cyber_lbl_gpu_name.setStyleSheet("color: #ecfeff; font-size: 11px; font-weight: 800; font-family: monospace;")
        self.cyber_lbl_gpu_chip = QLabel("GPU ▮▮▮▮▮▮▮ ⬢")
        self.cyber_lbl_gpu_chip.setStyleSheet("color: #84cc16; font-size: 9px; font-family: monospace;")
        c_gpu_head.addWidget(self.cyber_lbl_gpu_name)
        c_gpu_head.addStretch()
        c_gpu_head.addWidget(self.cyber_lbl_gpu_chip)
        hw_box.addLayout(c_gpu_head)

        c_gpu_mid = QHBoxLayout()
        c_gpu_mid.setContentsMargins(0, 0, 0, 0)
        c_gpu_mid.setSpacing(5)

        c_gpu_c1 = QVBoxLayout()
        c_gpu_c1.setSpacing(2)
        c_gpu_l_box = QHBoxLayout()
        self.cyber_lbl_gpu_load = QLabel("6%")
        self.cyber_lbl_gpu_load.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: 800; font-family: 'Segoe UI', 'Consolas', sans-serif;")
        c_gpu_load_sub = QLabel("LOAD")
        c_gpu_load_sub.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700; font-family: 'Segoe UI', sans-serif; padding-bottom: 2px;")
        c_gpu_l_box.addWidget(self.cyber_lbl_gpu_load)
        c_gpu_l_box.addWidget(c_gpu_load_sub, 0, Qt.AlignmentFlag.AlignBottom)
        c_gpu_l_box.addStretch()
        c_gpu_c1.addLayout(c_gpu_l_box)
        self.cyber_seg_gpu = SegmentedBarWidget(segments=16, height=11, lit_color="#84cc16")
        c_gpu_c1.addWidget(self.cyber_seg_gpu)
        c_gpu_mid.addLayout(c_gpu_c1, 35)

        c_gpu_c2 = QVBoxLayout()
        c_gpu_c2.setSpacing(2)
        self.cyber_lbl_gpu_temp = QLabel("46°C")
        self.cyber_lbl_gpu_temp.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: 800; font-family: 'Segoe UI', 'Consolas', sans-serif;")
        c_gpu_c2.addWidget(self.cyber_lbl_gpu_temp)
        c_gpu_c2_sp = QWidget()
        c_gpu_c2_sp.setFixedHeight(22)
        c_gpu_c2.addWidget(c_gpu_c2_sp)
        c_gpu_mid.addLayout(c_gpu_c2, 21)

        c_gpu_div1 = QFrame()
        c_gpu_div1.setFixedWidth(1)
        c_gpu_div1.setStyleSheet("background: #0e2238;")
        c_gpu_mid.addWidget(c_gpu_div1)

        c_gpu_c3 = QVBoxLayout()
        c_gpu_c3.setSpacing(2)
        c_gpu_f_box = QHBoxLayout()
        self.cyber_lbl_gpu_fps = QLabel("--")
        self.cyber_lbl_gpu_fps.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: 800; font-family: 'Segoe UI', 'Consolas', sans-serif;")
        c_gpu_fps_sub = QLabel("FPS")
        c_gpu_fps_sub.setStyleSheet("color: #64748b; font-size: 8px; font-weight: 700; font-family: 'Segoe UI', sans-serif; padding-bottom: 2px;")
        c_gpu_f_box.addWidget(self.cyber_lbl_gpu_fps)
        c_gpu_f_box.addWidget(c_gpu_fps_sub, 0, Qt.AlignmentFlag.AlignBottom)
        c_gpu_f_box.addStretch()
        c_gpu_c3.addLayout(c_gpu_f_box)
        self.cyber_spark_gpu_fps = SparklineWidget(height=22, line_color="#84cc16", fill_alpha=55)
        c_gpu_c3.addWidget(self.cyber_spark_gpu_fps)
        c_gpu_mid.addLayout(c_gpu_c3, 22)

        c_gpu_div2 = QFrame()
        c_gpu_div2.setFixedWidth(1)
        c_gpu_div2.setStyleSheet("background: #0e2238;")
        c_gpu_mid.addWidget(c_gpu_div2)

        c_gpu_c4 = QVBoxLayout()
        c_gpu_c4.setSpacing(2)
        c_gpu_p_box = QHBoxLayout()
        self.cyber_lbl_gpu_pwr = QLabel("-- W")
        self.cyber_lbl_gpu_pwr.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: 800; font-family: 'Segoe UI', 'Consolas', sans-serif;")
        c_gpu_pwr_sub = QLabel("POWER")
        c_gpu_pwr_sub.setStyleSheet("color: #64748b; font-size: 8px; font-weight: 700; font-family: monospace; padding-bottom: 2px;")
        c_gpu_p_box.addWidget(self.cyber_lbl_gpu_pwr)
        c_gpu_p_box.addWidget(c_gpu_pwr_sub, 0, Qt.AlignmentFlag.AlignBottom)
        c_gpu_p_box.addStretch()
        c_gpu_c4.addLayout(c_gpu_p_box)
        self.cyber_spark_gpu_pwr = SparklineWidget(height=22, line_color="#84cc16", fill_alpha=40)
        c_gpu_c4.addWidget(self.cyber_spark_gpu_pwr)
        c_gpu_mid.addLayout(c_gpu_c4, 22)

        hw_box.addLayout(c_gpu_mid)
        layout.addWidget(self.cyber_card_hw)

        # Compat aliases
        self.cyber_card_cpu = self.cyber_card_hw
        self.cyber_card_gpu = self.cyber_card_hw
        self.cyber_spark_cpu = self.cyber_spark_cpu_temp
        self.cyber_spark_gpu = self.cyber_spark_gpu_fps

        # 3. RAM Tactical Row
        self.cyber_card_ram = BentoCard("cyberpunk_hud", accent_color="#06b6d4")
        self.cyber_card_ram.setFixedHeight(58)
        cram_box = QVBoxLayout(self.cyber_card_ram)
        cram_box.setContentsMargins(10, 6, 10, 6)
        cram_box.setSpacing(4)
        c_ram_top = QHBoxLayout()
        self.cyber_lbl_ram_title = QLabel("RAM STATUS")
        self.cyber_lbl_ram_title.setStyleSheet("color: #06b6d4; font-size: 9px; font-weight: 800; font-family: monospace;")
        self.cyber_lbl_ram_val = QLabel("14.8 GB / 15.9 GB (93%) USED")
        self.cyber_lbl_ram_val.setStyleSheet("color: #ecfeff; font-size: 9px; font-weight: 700; font-family: monospace;")
        c_ram_top.addWidget(self.cyber_lbl_ram_title)
        c_ram_top.addStretch()
        c_ram_top.addWidget(self.cyber_lbl_ram_val)
        cram_box.addLayout(c_ram_top)
        self.cyber_seg_ram = SegmentedBarWidget(segments=32, height=11, lit_color="#06b6d4")
        cram_box.addWidget(self.cyber_seg_ram)
        c_dots = QLabel("●  ○")
        c_dots.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c_dots.setStyleSheet("color: #0891b2; font-size: 7px;")
        cram_box.addWidget(c_dots)
        layout.addWidget(self.cyber_card_ram)

        # 4. Cooling Tactical Row
        self.cyber_card_fans = BentoCard("cyberpunk_hud", accent_color="#06b6d4", tab_cut_x=155.0)
        self.cyber_card_fans.setFixedHeight(98)
        cfan_box = QVBoxLayout(self.cyber_card_fans)
        cfan_box.setContentsMargins(10, 6, 10, 6)
        cfan_box.setSpacing(3)
        c_fan_head = QHBoxLayout()
        self.cyber_lbl_cooling_title = QLabel("COOLING SUBSYSTEM")
        self.cyber_lbl_cooling_title.setStyleSheet("color: #ffffff; font-size: 10px; font-weight: 800; font-family: monospace;")
        c_fan_haz = QLabel("\\\\\\\\\\\\\\\\ 🔒 ⚙")
        c_fan_haz.setStyleSheet("color: #0891b2; font-size: 9px; font-family: monospace;")
        c_fan_head.addWidget(self.cyber_lbl_cooling_title)
        c_fan_head.addStretch()
        c_fan_head.addWidget(c_fan_haz)
        cfan_box.addLayout(c_fan_head)

        cfan_row = QHBoxLayout()
        cfan_row.setContentsMargins(0, 0, 0, 0)
        cfan_row.setSpacing(6)

        # Col 1: CPU fan
        c_f1 = QVBoxLayout()
        c_f1.setSpacing(1)
        self.cyber_lbl_f1_t = QLabel("CPU FAN")
        self.cyber_lbl_f1_t.setStyleSheet("color: #ffffff; font-size: 9px; font-weight: 800; font-family: monospace;")
        self.cyber_lbl_f1_sub = QLabel("Sensor · --")
        self.cyber_lbl_f1_sub.setStyleSheet("color: #06b6d4; font-size: 7.5px; font-weight: 600; font-family: monospace;")
        c_f1.addWidget(self.cyber_lbl_f1_t)
        c_f1.addWidget(self.cyber_lbl_f1_sub)

        c_f1_val_row = QHBoxLayout()
        self.cyber_lbl_f1_v = QLabel("1720")
        self.cyber_lbl_f1_v.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: 800; font-family: monospace;")
        c_f1_rpm_lbl = QLabel("RPM")
        c_f1_rpm_lbl.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700; font-family: monospace; padding-bottom: 2px;")
        c_f1_val_row.addWidget(self.cyber_lbl_f1_v)
        c_f1_val_row.addWidget(c_f1_rpm_lbl, 0, Qt.AlignmentFlag.AlignBottom)
        c_f1_val_row.addStretch()
        c_f1.addLayout(c_f1_val_row)

        self.cyber_slider_fan = CyberCalibrationSlider()
        self.cyber_seg_fan = self.cyber_slider_fan
        c_f1.addWidget(self.cyber_slider_fan)
        cfan_row.addLayout(c_f1, 35)

        div_fan1 = QFrame()
        div_fan1.setFixedWidth(1)
        div_fan1.setStyleSheet("background: #0e2238;")
        cfan_row.addWidget(div_fan1)

        # Col 2: Chassis Fan 1 (120mm PWM Case Fan)
        c_f2 = QVBoxLayout()
        c_f2.setSpacing(1)
        self.cyber_lbl_f2_t = QLabel("CHASSIS 1")
        self.cyber_lbl_f2_t.setStyleSheet("color: #ffffff; font-size: 9px; font-weight: 800; font-family: monospace;")
        self.cyber_lbl_f2_sub = QLabel("120mm · Normal")
        self.cyber_lbl_f2_sub.setStyleSheet("color: #06b6d4; font-size: 7.5px; font-weight: 600; font-family: monospace;")
        c_f2.addWidget(self.cyber_lbl_f2_t)
        c_f2.addWidget(self.cyber_lbl_f2_sub)

        c_f2_val_row = QHBoxLayout()
        self.cyber_lbl_f2_v = QLabel("920")
        self.cyber_lbl_f2_v.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: 800; font-family: monospace;")
        c_f2_rpm_lbl = QLabel("RPM")
        c_f2_rpm_lbl.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700; font-family: monospace; padding-bottom: 2px;")
        c_f2_val_row.addWidget(self.cyber_lbl_f2_v)
        c_f2_val_row.addWidget(c_f2_rpm_lbl, 0, Qt.AlignmentFlag.AlignBottom)
        c_f2_val_row.addStretch()
        c_f2.addLayout(c_f2_val_row)

        self.cyber_slider_fan2 = CyberCalibrationSlider()
        c_f2.addWidget(self.cyber_slider_fan2)
        cfan_row.addLayout(c_f2, 33)

        div_fan2 = QFrame()
        div_fan2.setFixedWidth(1)
        div_fan2.setStyleSheet("background: #0e2238;")
        cfan_row.addWidget(div_fan2)

        # Col 3: GPU fan
        c_f3 = QVBoxLayout()
        c_f3.setSpacing(1)
        self.cyber_lbl_f3_t = QLabel("GPU FAN")
        self.cyber_lbl_f3_t.setStyleSheet("color: #ffffff; font-size: 9px; font-weight: 800; font-family: monospace;")
        self.cyber_lbl_f3_sub = QLabel("Sensor · --")
        self.cyber_lbl_f3_sub.setStyleSheet("color: #84cc16; font-size: 7.5px; font-weight: 600; font-family: monospace;")
        c_f3.addWidget(self.cyber_lbl_f3_t)
        c_f3.addWidget(self.cyber_lbl_f3_sub)

        c_f3_val_row = QHBoxLayout()
        self.cyber_lbl_f3_v = QLabel("0")
        self.cyber_lbl_f3_v.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: 800; font-family: monospace;")
        c_f3_rpm_lbl = QLabel("RPM")
        c_f3_rpm_lbl.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700; font-family: monospace; padding-bottom: 2px;")
        c_f3_val_row.addWidget(self.cyber_lbl_f3_v)
        c_f3_val_row.addWidget(c_f3_rpm_lbl, 0, Qt.AlignmentFlag.AlignBottom)
        c_f3_val_row.addStretch()
        c_f3.addLayout(c_f3_val_row)

        self.cyber_slider_fan3 = CyberCalibrationSlider()
        c_f3.addWidget(self.cyber_slider_fan3)
        cfan_row.addLayout(c_f3, 32)

        cfan_box.addLayout(cfan_row)
        layout.addWidget(self.cyber_card_fans)

    # =================================================================
    # 3. CONSTRUCCIÓN DE LA VISTA: MINIMALIST COMPACT
    # =================================================================
    def _build_minimalist_view(self):
        layout = QVBoxLayout(self.minimalist_view)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(7)

        def _make_hdiv(color: str = "#1e222e") -> QFrame:
            f = QFrame()
            f.setFixedHeight(1)
            f.setStyleSheet(f"background: {color};")
            return f

        def _make_vdiv(color: str = "#232736") -> QFrame:
            f = QFrame()
            f.setFixedWidth(1)
            f.setStyleSheet(f"background: {color};")
            return f

        # Swiss Header: SYSTEM • AI | TELEMETRY
        self.mini_title = QLabel()
        self.mini_title.setText('<span style="color:#ffffff; font-weight:800; font-size:13px; font-family:\'Segoe UI\', Inter, sans-serif;">SYSTEM • AI </span><span style="color:#64748b; font-weight:400; font-size:13px;">| TELEMETRY</span>')
        layout.addWidget(self.mini_title)
        layout.addSpacing(1)

        # AI Section Label
        self.mini_ai_label = QLabel("AI QUOTA")
        self.mini_ai_label.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 700; font-family: 'Segoe UI', Inter, sans-serif; letter-spacing: 0.5px;")
        layout.addWidget(self.mini_ai_label)
        layout.addWidget(_make_hdiv("#1e222e"))

        # Container for vertical rows
        self.mini_ai_container = QWidget()
        self.mini_ai_layout = QVBoxLayout(self.mini_ai_container)
        self.mini_ai_layout.setContentsMargins(0, 0, 0, 0)
        self.mini_ai_layout.setSpacing(5)

        # Claude Row
        self.mini_row_claude = QWidget()
        mc_box = QHBoxLayout(self.mini_row_claude)
        mc_box.setContentsMargins(0, 1, 0, 1)
        mc_box.setSpacing(6)
        self.mini_lbl_claude = QLabel("Claude Code")
        self.mini_lbl_claude.setStyleSheet("color: #f1f5f9; font-size: 11px; font-weight: 600; min-width: 65px;")
        self.mini_bar_claude = SlimProgressBarWidget(bar_height=3, bar_color="#f59e0b")
        self.mini_val_claude = QLabel("0% (5h)")
        self.mini_val_claude.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 600; min-width: 90px; text-align: right;")
        mc_box.addWidget(self.mini_lbl_claude)
        mc_box.addWidget(self.mini_bar_claude, 1)
        mc_box.addWidget(self.mini_val_claude)
        self.mini_ai_layout.addWidget(self.mini_row_claude)

        # Antigravity Row
        self.mini_row_ag = QWidget()
        mag_box = QHBoxLayout(self.mini_row_ag)
        mag_box.setContentsMargins(0, 1, 0, 1)
        mag_box.setSpacing(6)
        self.mini_lbl_ag = QLabel("Antigravity")
        self.mini_lbl_ag.setStyleSheet("color: #f1f5f9; font-size: 11px; font-weight: 600; min-width: 65px;")
        self.mini_bar_ag = SlimProgressBarWidget(bar_height=3, bar_color="#06b6d4")
        self.mini_val_ag = QLabel()
        self.mini_val_ag.setText('<span style="color:#64748b; font-weight:500;">No verified quota</span>')
        self.mini_val_ag.setStyleSheet("font-size: 10px; min-width: 95px;")
        mag_box.addWidget(self.mini_lbl_ag)
        mag_box.addWidget(self.mini_bar_ag, 1)
        mag_box.addWidget(self.mini_val_ag)
        self.mini_ai_layout.addWidget(self.mini_row_ag)
        self.mini_ai_layout.addWidget(_make_hdiv("#181b24"))

        # Dynamic Provider Rows (Codex, Gemini CLI, Copilot, Grok, Cursor)
        self.mini_ai_rows = {}
        for p_id, p_title, p_col in (
            ("codex", "Codex Plus", "#84cc16"),
            ("gemini", "Gemini CLI", "#06b6d4"),
            ("copilot", "Copilot", "#f59e0b"),
            ("grok", "Grok", "#10b981"),
            ("cursor", "Cursor", "#8b5cf6"),
        ):
            row = QWidget()
            r_box = QHBoxLayout(row)
            r_box.setContentsMargins(0, 1, 0, 1)
            r_box.setSpacing(6)
            lbl = QLabel(p_title)
            lbl.setStyleSheet("color: #f1f5f9; font-size: 11px; font-weight: 600; min-width: 65px;")
            bar = SlimProgressBarWidget(bar_height=3, bar_color=p_col)
            val = QLabel()
            val.setStyleSheet("font-size: 10px; min-width: 95px;")
            val.setText("--")

            r_box.addWidget(lbl)
            r_box.addWidget(bar, 1)
            r_box.addWidget(val)
            self.mini_ai_layout.addWidget(row)
            if p_id != "cursor":
                self.mini_ai_layout.addWidget(_make_hdiv("#181b24"))

            self.mini_ai_rows[p_id] = {
                "row": row,
                "label": lbl,
                "bar": bar,
                "val": val,
                "color": p_col,
            }

        layout.addWidget(self.mini_ai_container)
        layout.addWidget(_make_hdiv("#1e222e"))

        self.mini_hw_container = QWidget()
        layout.addWidget(self.mini_hw_container)
        layout = QVBoxLayout(self.mini_hw_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)

        # Hardware Section Label
        self.mini_hw_label = QLabel("HARDWARE")
        self.mini_hw_label.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 700; font-family: 'Segoe UI', Inter, sans-serif; letter-spacing: 0.5px;")
        layout.addWidget(self.mini_hw_label)
        layout.addWidget(_make_hdiv("#1e222e"))

        # CPU Block (Swiss Columns)
        cpu_col = QVBoxLayout()
        cpu_col.setSpacing(2)
        lbl_cpu_t = QLabel("CPU")
        lbl_cpu_t.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700;")
        cpu_col.addWidget(lbl_cpu_t)

        cpu_grid = QHBoxLayout()
        cpu_grid.setContentsMargins(0, 0, 0, 0)
        cpu_grid.setSpacing(6)

        # CPU Col 1
        c_c1 = QVBoxLayout()
        c_c1.setSpacing(0)
        self.mini_cpu_name = QLabel("CPU")
        self.mini_cpu_name.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: 700;")
        s1 = QLabel("Usage")
        s1.setStyleSheet("color: #64748b; font-size: 9px;")
        c_c1.addWidget(self.mini_cpu_name)
        c_c1.addWidget(s1)
        cpu_grid.addLayout(c_c1, 1)

        cpu_grid.addWidget(_make_vdiv())

        # CPU Col 2
        c_c2 = QVBoxLayout()
        c_c2.setSpacing(0)
        self.mini_cpu_load = QLabel("12.3%")
        self.mini_cpu_load.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: 700;")
        s2 = QLabel("Usage")
        s2.setStyleSheet("color: #64748b; font-size: 9px;")
        c_c2.addWidget(self.mini_cpu_load)
        c_c2.addWidget(s2)
        cpu_grid.addLayout(c_c2, 1)

        cpu_grid.addWidget(_make_vdiv())

        # CPU Col 3
        c_c3 = QVBoxLayout()
        c_c3.setSpacing(0)
        self.mini_cpu_temp = QLabel("58°C")
        self.mini_cpu_temp.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: 700;")
        s3 = QLabel("Temp")
        s3.setStyleSheet("color: #64748b; font-size: 9px;")
        c_c3.addWidget(self.mini_cpu_temp)
        c_c3.addWidget(s3)
        cpu_grid.addLayout(c_c3, 1)

        cpu_col.addLayout(cpu_grid)
        layout.addLayout(cpu_col)
        layout.addWidget(_make_hdiv("#1e222e"))

        # GPU Block
        gpu_col = QVBoxLayout()
        gpu_col.setSpacing(2)
        lbl_gpu_t = QLabel("GPU")
        lbl_gpu_t.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700;")
        gpu_col.addWidget(lbl_gpu_t)

        gpu_grid = QHBoxLayout()
        gpu_grid.setContentsMargins(0, 0, 0, 0)
        gpu_grid.setSpacing(6)

        # GPU Col 1
        g_c1 = QVBoxLayout()
        g_c1.setSpacing(0)
        self.mini_gpu_name = QLabel("GPU")
        self.mini_gpu_name.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: 700;")
        gs1 = QLabel("Usage")
        gs1.setStyleSheet("color: #64748b; font-size: 9px;")
        g_c1.addWidget(self.mini_gpu_name)
        g_c1.addWidget(gs1)
        gpu_grid.addLayout(g_c1, 1)

        gpu_grid.addWidget(_make_vdiv())

        # GPU Col 2
        g_c2 = QVBoxLayout()
        g_c2.setSpacing(0)
        self.mini_gpu_load = QLabel("6%")
        self.mini_gpu_load.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: 700;")
        gs2 = QLabel("Usage")
        gs2.setStyleSheet("color: #64748b; font-size: 9px;")
        g_c2.addWidget(self.mini_gpu_load)
        g_c2.addWidget(gs2)
        gpu_grid.addLayout(g_c2, 1)

        gpu_grid.addWidget(_make_vdiv())

        # GPU Col 3 (Was missing previously!)
        g_c3 = QVBoxLayout()
        g_c3.setSpacing(0)
        self.mini_gpu_temp = QLabel("46°C")
        self.mini_gpu_temp.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: 700;")
        gs3 = QLabel("Temp")
        gs3.setStyleSheet("color: #64748b; font-size: 9px;")
        g_c3.addWidget(self.mini_gpu_temp)
        g_c3.addWidget(gs3)
        gpu_grid.addLayout(g_c3, 1)

        gpu_col.addLayout(gpu_grid)
        layout.addLayout(gpu_col)
        layout.addWidget(_make_hdiv("#1e222e"))

        # RAM Block
        ram_col = QVBoxLayout()
        ram_col.setSpacing(3)
        lbl_ram_t = QLabel("RAM")
        lbl_ram_t.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700;")
        ram_col.addWidget(lbl_ram_t)
        self.mini_bar_ram = SlimProgressBarWidget(bar_height=3, bar_color="#f59e0b")
        ram_col.addWidget(self.mini_bar_ram)

        ram_grid = QHBoxLayout()
        ram_grid.setContentsMargins(0, 0, 0, 0)
        ram_grid.setSpacing(6)

        # RAM Col 1
        r_c1 = QVBoxLayout()
        r_c1.setSpacing(0)
        self.mini_ram_gb = QLabel("14.8 GB")
        self.mini_ram_gb.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: 700;")
        self.mini_ram_total = QLabel("15.9 GB")
        self.mini_ram_total.setStyleSheet("color: #64748b; font-size: 9px;")
        r_c1.addWidget(self.mini_ram_gb)
        r_c1.addWidget(self.mini_ram_total)
        ram_grid.addLayout(r_c1, 1)

        ram_grid.addWidget(_make_vdiv())

        # RAM Col 2
        r_c2 = QVBoxLayout()
        r_c2.setSpacing(0)
        self.mini_ram_percent = QLabel("--%")
        self.mini_ram_percent.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: 700;")
        self.mini_ram_temp = self.mini_ram_percent  # compatibilidad con integraciones antiguas
        rs2 = QLabel("Used")
        rs2.setStyleSheet("color: #64748b; font-size: 9px;")
        r_c2.addWidget(self.mini_ram_percent)
        r_c2.addWidget(rs2)
        ram_grid.addLayout(r_c2, 1)

        ram_grid.addWidget(_make_vdiv())

        # RAM Col 3
        r_c3 = QVBoxLayout()
        r_c3.setSpacing(0)
        self.mini_ram_fps = QLabel("FPS --")
        self.mini_ram_fps.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: 700;")
        rs3 = QLabel("Games")
        rs3.setStyleSheet("color: #64748b; font-size: 9px;")
        r_c3.addWidget(self.mini_ram_fps)
        r_c3.addWidget(rs3)
        ram_grid.addLayout(r_c3, 1)

        ram_col.addLayout(ram_grid)
        layout.addLayout(ram_col)
        layout.addWidget(_make_hdiv("#1e222e"))

        # FAN Block (3 columns for all physical fans)
        fan_col = QVBoxLayout()
        fan_col.setSpacing(2)
        lbl_fan_t = QLabel("COOLING FANS")
        lbl_fan_t.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700;")
        fan_col.addWidget(lbl_fan_t)

        fan_grid = QHBoxLayout()
        fan_grid.setContentsMargins(0, 0, 0, 0)
        fan_grid.setSpacing(6)

        # Col 1: CPU Fan
        fn1_c = QVBoxLayout()
        fn1_c.setSpacing(0)
        self.mini_fan1_rpm = QLabel("1720 RPM")
        self.mini_fan1_rpm.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: 700;")
        self.mini_fan1_sub = QLabel("CPU · Máximo")
        self.mini_fan1_sub.setStyleSheet("color: #64748b; font-size: 9px;")
        fn1_c.addWidget(self.mini_fan1_rpm)
        fn1_c.addWidget(self.mini_fan1_sub)
        fan_grid.addLayout(fn1_c, 1)

        fan_grid.addWidget(_make_vdiv())

        # Col 2: Chassis Fan 1
        fn2_c = QVBoxLayout()
        fn2_c.setSpacing(0)
        self.mini_fan2_rpm = QLabel("920 RPM")
        self.mini_fan2_rpm.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: 700;")
        self.mini_fan2_sub = QLabel("Caja · Normal")
        self.mini_fan2_sub.setStyleSheet("color: #64748b; font-size: 9px;")
        fn2_c.addWidget(self.mini_fan2_rpm)
        fn2_c.addWidget(self.mini_fan2_sub)
        fan_grid.addLayout(fn2_c, 1)

        fan_grid.addWidget(_make_vdiv())

        # Col 3: GPU Fan
        fn3_c = QVBoxLayout()
        fn3_c.setSpacing(0)
        self.mini_fan3_rpm = QLabel("0 RPM")
        self.mini_fan3_rpm.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: 700;")
        self.mini_fan3_sub = QLabel("GPU · 0 dB")
        self.mini_fan3_sub.setStyleSheet("color: #64748b; font-size: 9px;")
        fn3_c.addWidget(self.mini_fan3_rpm)
        fn3_c.addWidget(self.mini_fan3_sub)
        fan_grid.addLayout(fn3_c, 1)

        # Backward compatibility aliases
        self.mini_fan_rpm = self.mini_fan1_rpm
        self.mini_fan_sub = self.mini_fan1_sub

        fan_col.addLayout(fan_grid)
        layout.addLayout(fan_col)

    # -----------------------------------------------------------------
    # APLICACIÓN DE VISIBILIDAD DE MÓDULOS AI
    # -----------------------------------------------------------------
    def _is_provider_visible(self, name: str) -> bool:
        default = name in ("antigravity", "codex", "copilot", "grok", "cursor")
        return self.content_mode in ("all", "quotas") and bool(self.ai_modules.get(f"show_{name}", default))

    def _apply_ai_visibility(self):
        # 1. Bento Grid
        while self.bento_ai_grid.count():
            self.bento_ai_grid.takeAt(0)

        bento_cards = [
            ("claude", self.bento_card_claude),
            ("antigravity", self.bento_card_ag),
        ] + [(name, item["card"]) for name, item in self.bento_ai_cards.items()]

        visible_bento = [(name, c) for name, c in bento_cards if self._is_provider_visible(name)]
        for idx, (_, card) in enumerate(visible_bento):
            self.bento_ai_grid.addWidget(card, idx // 2, idx % 2)
            card.setVisible(True)
        vis_set = {c for _, c in visible_bento}
        for _, card in bento_cards:
            if card not in vis_set:
                card.setParent(self.bento_view)
                card.setVisible(False)

        # 2. Cyberpunk Grid
        while self.cyber_ai_grid.count():
            self.cyber_ai_grid.takeAt(0)

        cyber_cards = [
            ("claude", self.cyber_card_claude),
            ("antigravity", self.cyber_card_ag),
        ] + [(name, item["card"]) for name, item in self.cyber_ai_cards.items()]

        visible_cyber = [(name, c) for name, c in cyber_cards if self._is_provider_visible(name)]
        for idx, (_, card) in enumerate(visible_cyber):
            self.cyber_ai_grid.addWidget(card, idx // 2, idx % 2)
            card.setVisible(True)
        c_vis_set = {c for _, c in visible_cyber}
        for _, card in cyber_cards:
            if card not in c_vis_set:
                card.setParent(self.cyberpunk_view)
                card.setVisible(False)

        # 3. Minimalist Rows
        self.mini_row_claude.setVisible(self._is_provider_visible("claude"))
        self.mini_row_ag.setVisible(self._is_provider_visible("antigravity"))
        for name, item in self.mini_ai_rows.items():
            item["row"].setVisible(self._is_provider_visible(name))

        has_ai = bool(visible_bento)
        self.bento_ai_label.setVisible(False if self.theme_style == "bento_glass" else has_ai)
        self.mini_ai_label.setVisible(has_ai)
        self.mini_ai_container.setVisible(has_ai)
        for container in (self.bento_hw_container, self.cyber_hw_container, self.mini_hw_container):
            container.setVisible(self.content_mode in ("all", "hardware"))
        for view, theme in ((self.bento_view, "bento_glass"), (self.cyberpunk_view, "cyberpunk_hud"), (self.minimalist_view, "minimalist_compact")):
            view.setVisible(self.content_mode != "fps" and self.theme_style == theme)
        self.fps_only_label.setVisible(self.content_mode == "fps")

    def set_content_mode(self, mode: str):
        if mode not in self.CONTENT_MODES:
            return
        self.content_mode = mode
        self._apply_ai_visibility()
        self.apply_scale(self.ui_scale, save=False)
        self.content_mode_changed.emit(mode)

    def add_content_menu(self, menu):
        submenu = menu.addMenu("Contenido")
        for mode, label in self.CONTENT_MODES.items():
            action = submenu.addAction(label)
            action.setData(mode)
            action.setCheckable(True)
            action.setChecked(self.content_mode == mode)
            action.triggered.connect(lambda checked=False, value=mode: self.set_content_mode(value))
        submenu.aboutToShow.connect(lambda: [action.setChecked(action.data() == self.content_mode) for action in submenu.actions()])
        return submenu

    def add_scale_menu(self, menu):
        submenu = menu.addMenu("Tamaño")
        for scale in (0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 2.0):
            action = submenu.addAction(f"{scale:.0%}")
            action.setData(scale)
            action.setCheckable(True)
            action.setChecked(self.ui_scale == scale)
            action.triggered.connect(lambda checked=False, value=scale: self.apply_scale(value))
        submenu.aboutToShow.connect(lambda: [action.setChecked(action.data() == self.ui_scale) for action in submenu.actions()])
        return submenu

    def update_ai_modules(self, ai_modules: dict):
        self.ai_modules = ai_modules
        for p_id in self._EXTENDED_PROVIDER_DEFS:
            if self.ai_modules.get(f"show_{p_id}", False):
                self._ensure_ai_card(p_id)
        self._apply_ai_visibility()
        self.apply_scale(self.ui_scale, save=False)

    # -----------------------------------------------------------------
    # GESTIÓN DE TEMAS VISUALES (Bento Glass, Cyberpunk HUD, Minimalist)
    # -----------------------------------------------------------------
    def set_theme(self, theme_style: str, save: bool = True):
        valid = ("bento_glass", "cyberpunk_hud", "minimalist_compact")
        self.theme_style = theme_style if theme_style in valid else "bento_glass"

        self.bento_view.setVisible(self.theme_style == "bento_glass")
        self.cyberpunk_view.setVisible(self.theme_style == "cyberpunk_hud")
        self.minimalist_view.setVisible(self.theme_style == "minimalist_compact")

        if self.theme_style == "cyberpunk_hud":
            self.header_widget.setVisible(False)
            self.main_layout.setContentsMargins(10, 10, 10, 10)
            self.main_layout.setSpacing(6)
            self.title_label.setText("WIDGETS HUD")
            self.logo_dot.setStyleSheet("color: #06b6d4; font-size: 8px;")
        elif self.theme_style == "minimalist_compact":
            self.header_widget.setVisible(False)
            self.main_layout.setContentsMargins(12, 10, 12, 10)
            self.main_layout.setSpacing(6)
            self.title_label.setText("SYSTEM • AI | TELEMETRY")
            self.logo_dot.setStyleSheet("color: #38bdf8; font-size: 8px;")
        else:
            self.header_widget.setVisible(False)
            self.main_layout.setContentsMargins(8, 8, 8, 8)
            self.main_layout.setSpacing(6)
            self.title_label.setText("WIDGETS")
            self.logo_dot.setStyleSheet("color: #38bdf8; font-size: 8px;")

        self._apply_ai_visibility()
        self.apply_scale(self.ui_scale, save=False)

        # Re-aplicar datos cacheados a las 3 vistas
        if self.last_hardware_data:
            self.update_hardware(self.last_hardware_data)
        for name, data in self.cached_provider_data.items():
            if name == "claude":
                self.update_claude(data)
            elif name == "antigravity":
                self.update_antigravity(data)
            elif name in self.ai_cards:
                self.update_quota_provider(name, data)

        self._scale_contents()
        self.adjustSize()
        self.update()
        if save:
            self.theme_changed.emit(self.theme_style)

    # -----------------------------------------------------------------
    # ESCALADO DINÁMICO
    # -----------------------------------------------------------------
    def apply_scale(self, scale: float, save: bool = True):
        scale = float(scale)
        if not math.isfinite(scale):
            return
        self.ui_scale = round(max(0.6, min(2.0, scale)), 2)
        s = self.ui_scale

        if self.content_mode == "fps":
            base_w = 150
        elif self.theme_style == "minimalist_compact":
            base_w = 317
        elif self.theme_style == "cyberpunk_hud":
            base_w = 344
        else:
            base_w = 338
        self.setFixedWidth(int(base_w * s))

        btn_sz = 22
        self.btn_min.setFixedSize(btn_sz, btn_sz)
        self.btn_close.setFixedSize(btn_sz, btn_sz)

        self.hotkey_badge.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 0.05);
                color: #94a3b8;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 2px 7px;
                font-size: 9px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.1);
                color: #f8fafc;
                border-color: #3b82f6;
            }}
        """)

        self.btn_min.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: #64748b;
                border: none;
                border-radius: 4px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.08);
                color: #f8fafc;
            }}
        """)
        self.btn_close.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: #64748b;
                border: none;
                border-radius: 4px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: #ef4444;
                color: #ffffff;
            }}
        """)

        self._scale_contents()
        self.adjustSize()
        self.update()

        if save:
            self.scale_changed.emit(self.ui_scale)

    def _scale_contents(self):
        """Scale from original metrics, including styles replaced by live updates."""
        s = self.ui_scale
        def pixels(text):
            return re.sub(r"(\d+(?:\.\d+)?)px", lambda match: f"{float(match[1]) * s:g}px", text)

        for widget in self.findChildren(QWidget):
            if widget.isWindow():
                continue
            style = widget.styleSheet()
            if style != getattr(widget, "_scaled_style", None):
                widget._base_style = style
            scaled = pixels(getattr(widget, "_base_style", style))
            widget._scaled_style = scaled
            if scaled != style:
                widget.setStyleSheet(scaled)
            if isinstance(widget, QLabel) and "font-size:" in widget.text():
                current = widget.text()
                if current != getattr(widget, "_scaled_text", None):
                    widget._base_text = current
                widget._scaled_text = pixels(widget._base_text)
                if current != widget._scaled_text:
                    widget.setText(widget._scaled_text)
            if isinstance(widget, RingGaugeV3):
                widget.set_scale(s)
                continue
            if not hasattr(widget, "_base_limits"):
                widget._base_limits = (widget.minimumWidth(), widget.maximumWidth(), widget.minimumHeight(), widget.maximumHeight())
            min_w, max_w, min_h, max_h = widget._base_limits
            if min_w == max_w:
                widget.setFixedWidth(max(1, round(min_w * s)))
            if min_h == max_h:
                widget.setFixedHeight(max(1, round(min_h * s)))
        for layout in self.findChildren(QLayout):
            if not hasattr(layout, "_base_metrics"):
                margins = layout.contentsMargins()
                layout._base_metrics = ((margins.left(), margins.top(), margins.right(), margins.bottom()), layout.spacing())
            margins, spacing = layout._base_metrics
            layout.setContentsMargins(*(round(value * s) for value in margins))
            if spacing >= 0:
                layout.setSpacing(round(spacing * s))
        for layout in reversed(self.findChildren(QLayout)):
            layout.invalidate()
            layout.activate()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.size_changed.emit()

    # -----------------------------------------------------------------
    # ACTUALIZACIÓN DE HARDWARE (SINCRONIZACIÓN CON LAS 3 VISTAS)
    # -----------------------------------------------------------------
    def update_hardware(self, data: dict):
        self.last_hardware_data = data

        cpu_pct = float(data.get("cpu_percent", 0.0))
        cpu_temp = data.get("cpu_temp")
        cpu_pwr = data.get("cpu_power")

        gpu_pct = float(data.get("gpu_percent", 0.0))
        gpu_temp = data.get("gpu_temp")
        gpu_hs = data.get("gpu_hotspot")
        fps = float(data.get("fps", 0.0))

        ram_pct = float(data.get("ram_percent", 0.0))
        ram_used = float(data.get("ram_used_gb", 0.0))
        ram_total = float(data.get("ram_total_gb") or 0.0)
        top_proc = str(data.get("top_process") or "").removesuffix(".exe")
        top_gb = float(data.get("top_process_gb", 0.0))

        fans = []
        for item in data.get("fans", []):
            fan = dict(item)
            original_name = str(fan.get("name") or "")
            if original_name in self.fan_aliases:
                fan["name"] = self.fan_aliases[original_name]
            fans.append(fan)

        # Formateo de cadenas
        cpu_temp_str = f"{cpu_temp:.0f}°C" if cpu_temp is not None else "-- °C"
        cpu_pwr_str = f"{cpu_pwr:.0f}W" if cpu_pwr is not None else "-- W"
        gpu_temp_str = f"{gpu_temp:.0f}°C" if gpu_temp is not None else "-- °C"
        fps_badge_str = f"{fps:.0f} FPS" if fps > 0 else "FPS --"
        self.fps_only_label.setText(fps_badge_str)
        fps_text = f" • {fps:.0f} FPS" if fps > 0 else " • FPS --"
        edge_text = f"{gpu_temp:.0f}°C" if gpu_temp is not None else "Edge --"
        hotspot_text = f"HS {gpu_hs:.0f}°C" if gpu_hs is not None else "HS --"
        proc_sub = f" • {top_proc[:10]} {top_gb:.1f}G" if top_proc else ""
        self._last_top_proc_str = proc_sub

        # Color térmico dinámico
        if cpu_temp is None:
            c_color = "#38bdf8"
        elif cpu_temp < 65.0:
            c_color = "#10b981"
        elif cpu_temp < 80.0:
            c_color = "#f59e0b"
        else:
            c_color = "#ef4444"

        # --- 1. Bento Glass ---
        self.bento_lbl_cpu_temp.setText(cpu_temp_str)
        self.bento_lbl_cpu_temp.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: 800; border: none; background: transparent;")
        self.bento_lbl_cpu_util.setText(f"Utilization: {cpu_pct:.1f}%")
        self.bento_spark_cpu.add_value(cpu_pct)

        self.bento_lbl_gpu_temp.setText(gpu_temp_str)
        self.bento_lbl_gpu_temp.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: 800; border: none; background: transparent;")
        self.bento_lbl_gpu_sub.setText(f"Utilization: {gpu_pct:.0f}%")
        self.bento_pill_fps.setText(fps_badge_str)
        self.bento_spark_gpu.add_value(gpu_pct)

        ram_total_text = f"{ram_total:.1f} GB" if ram_total > 0 else "-- GB"
        self.bento_lbl_ram_sub.setText(f"{ram_used:.1f} GB / {ram_total_text}")
        self.bento_lbl_ram_sub.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: 700; border: none; background: transparent;")
        self.bento_bar_ram.setValue(ram_pct)

        self._update_bento_fans(fans)

        # --- 2. Cyberpunk HUD ---
        self.cyber_lbl_cpu_load.setText(f"{cpu_pct:.1f}%")
        self.cyber_seg_cpu.setValue(cpu_pct)
        self.cyber_lbl_cpu_temp.setText(cpu_temp_str)
        self.cyber_lbl_cpu_pwr.setText(cpu_pwr_str)
        self.cyber_spark_cpu_temp.add_value(cpu_pct)
        if cpu_pwr is not None:
            self.cyber_spark_cpu_pwr.add_value(float(cpu_pwr))

        self.cyber_lbl_gpu_load.setText(f"{gpu_pct:.0f}%")
        self.cyber_seg_gpu.setValue(gpu_pct)
        self.cyber_lbl_gpu_temp.setText(gpu_temp_str)
        self.cyber_lbl_gpu_fps.setText(f"{fps:.0f}" if fps > 0 else "--")
        gpu_pwr_val = float(data.get("gpu_power") or 0.0)
        self.cyber_lbl_gpu_pwr.setText(f"{gpu_pwr_val:.0f}W" if data.get("gpu_power") is not None else "-- W")
        self.cyber_spark_gpu_fps.add_value(fps if fps > 0 else 0.0)
        self.cyber_spark_gpu_pwr.add_value(gpu_pwr_val)

        self.cyber_lbl_ram_val.setText(f"{ram_used:.1f} GB / {ram_total_text} ({ram_pct:.0f}%) USED")
        self.cyber_seg_ram.setValue(ram_pct)

        # --- Minimalist Compact Hardware Updates ---
        if hasattr(self, "mini_cpu_load"):
            self.mini_cpu_load.setText(f"{cpu_pct:.1f}%")
        if hasattr(self, "mini_cpu_temp"):
            self.mini_cpu_temp.setText(cpu_temp_str)
        if hasattr(self, "mini_gpu_load"):
            self.mini_gpu_load.setText(f"{gpu_pct:.0f}%")
        if hasattr(self, "mini_gpu_temp"):
            self.mini_gpu_temp.setText(gpu_temp_str)
        if hasattr(self, "mini_ram_gb"):
            self.mini_ram_gb.setText(f"{ram_used:.1f} GB")
        if hasattr(self, "mini_ram_total"):
            self.mini_ram_total.setText(ram_total_text)
        if hasattr(self, "mini_ram_percent"):
            self.mini_ram_percent.setText(f"{ram_pct:.0f}%")
        if hasattr(self, "mini_ram_fps"):
            self.mini_ram_fps.setText(fps_badge_str)
        if hasattr(self, "mini_bar_ram"):
            self.mini_bar_ram.setValue(ram_pct)

        for label in (self.cyber_lbl_f1_v, self.cyber_lbl_f2_v, self.cyber_lbl_f3_v):
            label.setText("--")
        for label in (self.mini_fan1_rpm, self.mini_fan2_rpm, self.mini_fan3_rpm):
            label.setText("-- RPM")
        for slider in (self.cyber_slider_fan, self.cyber_slider_fan2, self.cyber_slider_fan3):
            slider.setValue(0.0)
        if fans and len(fans) >= 1:
            f0 = fans[0]
            r0 = float(f0.get("rpm", 0))
            l0 = str(f0.get("speed_label") or "Sin clasificación")
            h0 = str(f0.get("hardware") or "Ventilador")
            self.cyber_lbl_f1_t.setText(str(f0.get("name", "CPU FAN")).upper())
            if hasattr(self, "cyber_lbl_f1_sub"):
                self.cyber_lbl_f1_sub.setText(f"{h0} · {l0}")
            self.cyber_lbl_f1_v.setText(f"{int(round(r0))}")
            max0 = float(f0.get("max_rpm") or 0.0)
            self.cyber_slider_fan.setValue((r0 / max0) * 100.0 if max0 > 0 else 0.0)

            if hasattr(self, "mini_fan1_rpm"):
                self.mini_fan1_rpm.setText(f"{int(round(r0))} RPM")
            if hasattr(self, "mini_fan1_sub"):
                self.mini_fan1_sub.setText(f"CPU · {l0}")
            self.mini_fan_rpm.setText(f"{int(round(r0))} RPM")

            if len(fans) > 1:
                f1 = fans[1]
                r1 = float(f1.get("rpm", 0))
                l1 = str(f1.get("speed_label") or "Sin clasificación")
                h1 = str(f1.get("hardware") or "Ventilador")
                self.cyber_lbl_f2_t.setText(str(f1.get("name", "CHASSIS FAN 1")).upper())
                if hasattr(self, "cyber_lbl_f2_sub"):
                    self.cyber_lbl_f2_sub.setText(f"{h1} · {l1}")
                self.cyber_lbl_f2_v.setText(f"{int(round(r1))}")
                if hasattr(self, "cyber_slider_fan2"):
                    max1 = float(f1.get("max_rpm") or 0.0)
                    self.cyber_slider_fan2.setValue((r1 / max1) * 100.0 if max1 > 0 else 0.0)
                if hasattr(self, "mini_fan2_rpm"):
                    self.mini_fan2_rpm.setText(f"{int(round(r1))} RPM")
                if hasattr(self, "mini_fan2_sub"):
                    self.mini_fan2_sub.setText(f"Caja · {l1}")

            if len(fans) > 2:
                f2 = fans[2]
                r2 = float(f2.get("rpm", 0))
                l2 = str(f2.get("speed_label") or "Sin clasificación")
                h2 = str(f2.get("hardware") or "Ventilador")
                if hasattr(self, "cyber_lbl_f3_t"):
                    self.cyber_lbl_f3_t.setText(str(f2.get("name", "GPU FAN")).upper())
                if hasattr(self, "cyber_lbl_f3_sub"):
                    self.cyber_lbl_f3_sub.setText(f"{h2} · {l2}")
                if hasattr(self, "cyber_lbl_f3_v"):
                    self.cyber_lbl_f3_v.setText(f"{int(round(r2))}")
                if hasattr(self, "cyber_slider_fan3"):
                    max2 = float(f2.get("max_rpm") or 0.0)
                    self.cyber_slider_fan3.setValue((r2 / max2) * 100.0 if max2 > 0 else 0.0)
                if hasattr(self, "mini_fan3_rpm"):
                    self.mini_fan3_rpm.setText(f"{int(round(r2))} RPM")
                if hasattr(self, "mini_fan3_sub"):
                    self.mini_fan3_sub.setText(f"GPU · {l2}")

    def _update_bento_fans(self, fans: list[dict]):
        # Render all physical fans with exact hardware info and speed states
        items_to_show = fans
        self.bento_lbl_fans_title.setText("Cooling Fans" if fans else "Ventiladores · sin datos")

        bar_colors = [
            ("#f43f5e", "#fb7185"),  # CPU Fan: Rose Red
            ("#10b981", "#34d399"),  # Chassis Fan: Emerald Mint
            ("#06b6d4", "#38bdf8"),  # GPU Fan: Cyan
        ]

        current_keys = set()
        for idx, f in enumerate(items_to_show):
            key = f"bento_fan_{idx}"
            current_keys.add(key)

            display_name = str(f.get("name") or f"Fan {idx + 1}")
            hardware = str(f.get("hardware") or "")
            location = str(f.get("location") or "")
            if hardware and location:
                sub_text = f"{hardware} • {location}"
            elif hardware or location:
                sub_text = hardware or location
            else:
                sub_text = "Disipador / Chasis"

            rpm = float(f.get("rpm", 0.0))
            max_rpm = max(1.0, float(f.get("max_rpm") or 1800.0))
            speed_label = str(f.get("speed_label") or ("Parado (0 dB)" if rpm <= 0 else f"{int(round((rpm / max_rpm) * 100))}%"))

            top_col, bot_col = bar_colors[idx % len(bar_colors)]

            lbl_lower = speed_label.lower()
            if "parado" in lbl_lower or rpm <= 0:
                pill_style = "background: rgba(100, 116, 139, 0.18); color: #94a3b8; border: 1px solid rgba(148, 163, 184, 0.22); border-radius: 4px; padding: 1px 6px; font-size: 9px; font-weight: 600; font-family: 'Segoe UI', sans-serif;"
            elif "silencioso" in lbl_lower:
                pill_style = "background: rgba(16, 185, 129, 0.16); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.28); border-radius: 4px; padding: 1px 6px; font-size: 9px; font-weight: 600; font-family: 'Segoe UI', sans-serif;"
            elif "normal" in lbl_lower:
                pill_style = "background: rgba(6, 182, 212, 0.16); color: #38bdf8; border: 1px solid rgba(6, 182, 212, 0.28); border-radius: 4px; padding: 1px 6px; font-size: 9px; font-weight: 600; font-family: 'Segoe UI', sans-serif;"
            elif "rápido" in lbl_lower or "rapido" in lbl_lower:
                pill_style = "background: rgba(245, 158, 11, 0.16); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.28); border-radius: 4px; padding: 1px 6px; font-size: 9px; font-weight: 600; font-family: 'Segoe UI', sans-serif;"
            else:
                pill_style = "background: rgba(244, 63, 94, 0.16); color: #fb7185; border: 1px solid rgba(244, 63, 94, 0.28); border-radius: 4px; padding: 1px 6px; font-size: 9px; font-weight: 600; font-family: 'Segoe UI', sans-serif;"

            rpm_str = f"{int(round(rpm)):,} RPM" if rpm > 0 else "0 RPM"
            rpm_style = "color: #ffffff; font-size: 13.5px; font-weight: 800; background: transparent; border: none;" if rpm > 0 else "color: #64748b; font-size: 13.5px; font-weight: 700; background: transparent; border: none;"

            if key not in self._bento_fan_rows:
                container = QWidget()
                c_layout = QVBoxLayout(container)
                c_layout.setContentsMargins(0, 0, 0, 0)
                c_layout.setSpacing(4)

                row = QFrame()
                row.setStyleSheet("background: transparent; border: none;")
                h_box = QHBoxLayout(row)
                h_box.setContentsMargins(0, 1, 0, 1)
                h_box.setSpacing(8)

                bar = DualAccentBar(width=3.2, height=30, color_top=top_col, color_bottom=bot_col)
                h_box.addWidget(bar)

                text_col = QVBoxLayout()
                text_col.setSpacing(1)
                lbl_name = QLabel(display_name)
                lbl_name.setStyleSheet("color: #ffffff; font-size: 12px; font-weight: 700; background: transparent; border: none;")
                lbl_sub = QLabel(sub_text)
                lbl_sub.setWordWrap(True)
                lbl_sub.setStyleSheet("color: #64748b; font-size: 9.5px; font-weight: 500; background: transparent; border: none;")
                text_col.addWidget(lbl_name)
                text_col.addWidget(lbl_sub)
                h_box.addLayout(text_col, stretch=1)

                right_col = QVBoxLayout()
                right_col.setSpacing(2)
                right_col.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                lbl_rpm = QLabel(rpm_str)
                lbl_rpm.setStyleSheet(rpm_style)
                lbl_rpm.setAlignment(Qt.AlignmentFlag.AlignRight)
                lbl_badge = QLabel(speed_label)
                lbl_badge.setStyleSheet(pill_style)
                lbl_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                right_col.addWidget(lbl_rpm)
                right_col.addWidget(lbl_badge)
                h_box.addLayout(right_col)

                c_layout.addWidget(row)

                div = QFrame()
                div.setFixedHeight(1)
                div.setStyleSheet("background: rgba(255, 255, 255, 0.05); border: none;")
                c_layout.addWidget(div)

                self.bento_fans_layout.addWidget(container)
                self._bento_fan_rows[key] = {
                    "container": container,
                    "row": row,
                    "lbl_name": lbl_name,
                    "lbl_sub": lbl_sub,
                    "lbl_rpm": lbl_rpm,
                    "lbl_badge": lbl_badge,
                    "bar": bar,
                    "div": div,
                }
            else:
                row_data = self._bento_fan_rows[key]
                row_data["lbl_name"].setText(display_name)
                row_data["lbl_sub"].setText(sub_text)
                row_data["lbl_rpm"].setText(rpm_str)
                row_data["lbl_rpm"].setStyleSheet(rpm_style)
                row_data["lbl_badge"].setText(speed_label)
                row_data["lbl_badge"].setStyleSheet(pill_style)
                row_data["bar"].set_colors(top_col, bot_col)

        stale_keys = [k for k in self._bento_fan_rows if k not in current_keys]
        for k in stale_keys:
            w = self._bento_fan_rows[k]["container"]
            self.bento_fans_layout.removeWidget(w)
            w.deleteLater()
            del self._bento_fan_rows[k]

    # -----------------------------------------------------------------
    # ACTUALIZACIÓN DE PROVEEDORES AI (BENTO, CYBERPUNK, MINIMALIST)
    # -----------------------------------------------------------------
    def _cycle_card_mode(self, provider_id: str):
        """Cicla interactivo: 0: % remaining, 1: absolute count / 2da ventana, 2: reset countdown/fecha."""
        cur = self.card_display_modes.get(provider_id, 0)
        self.card_display_modes[provider_id] = (cur + 1) % 3
        data = self.cached_provider_data.get(provider_id)
        if data:
            if provider_id == "claude":
                self.update_claude(data)
            elif provider_id == "antigravity":
                self.update_antigravity(data)
            elif provider_id in self.ai_cards:
                self.update_quota_provider(provider_id, data)
            self._scale_contents()
            self.adjustSize()

    def update_claude(self, data: dict):
        self.cached_provider_data["claude"] = data
        raw = data.get("raw") or {}
        mode = self.card_display_modes.get("claude", 0)
        status = data.get("status")
        status_text = str(getattr(status, "value", status) or "").lower()
        is_live = status == ProviderStatus.OK or status_text.endswith("ok")
        is_stale = status_text == ProviderStatus.STALE.value or bool(data.get("stale"))

        if raw and (is_live or is_stale):
            five_h = raw.get("five_hour", {})
            five_h_pct = float(five_h.get("utilization", five_h.get("percent", 0.0)))
            seven_d = raw.get("seven_day", {})
            seven_d_pct = float(seven_d.get("utilization", seven_d.get("percent", 0.0)))
            rem_5h = max(0.0, min(100.0, 100.0 - five_h_pct))
            rem_7d = max(0.0, min(100.0, 100.0 - seven_d_pct))

            # Resets countdowns
            resets_at_5h = five_h.get("resets_at")
            desc_5h = ""
            if resets_at_5h:
                try:
                    rt = datetime.fromisoformat(str(resets_at_5h).replace("Z", "+00:00"))
                    if rt.tzinfo is None:
                        rt = rt.replace(tzinfo=timezone.utc)
                    delta = rt - datetime.now(timezone.utc)
                    tot_sec = max(0, int(delta.total_seconds()))
                    h = tot_sec // 3600
                    m = (tot_sec % 3600) // 60
                    desc_5h = f"{h}h {m}m" if h else f"{m}m"
                except Exception:
                    desc_5h = ""
            if not desc_5h:
                desc_5h = "5h Activa"

            resets_at_7d = seven_d.get("resets_at")
            desc_7d = ""
            if resets_at_7d:
                try:
                    rt = datetime.fromisoformat(str(resets_at_7d).replace("Z", "+00:00"))
                    if rt.tzinfo is None:
                        rt = rt.replace(tzinfo=timezone.utc)
                    delta = rt - datetime.now(timezone.utc)
                    tot_sec = max(0, int(delta.total_seconds()))
                    d = tot_sec // 86400
                    h = (tot_sec % 86400) // 3600
                    desc_7d = f"{d}d {h}h" if d else f"{h}h"
                except Exception:
                    desc_7d = ""

            # Bento View
            self.bento_gauge_claude.setVisible(True)
            self.bento_pill_claude.setVisible(True)
            self.bento_foot_claude.setVisible(True)
            self.bento_val_claude.setVisible(True)
            self.bento_sub_claude.setVisible(True)
            if mode == 1:
                # Mode 1: Weekly (7d)
                self.bento_val_claude.setText(f"{rem_7d:.0f}%")
                self.bento_sub_claude.setText("Cuota semanal (7d)")
                self.bento_gauge_claude.setValue(rem_7d)
                self.bento_pill_claude.setText(desc_7d or "7d Activa")
                self.bento_foot_claude.setText(f"5h: {rem_5h:.0f}% · {desc_5h}")
            elif mode == 2:
                # Mode 2: Account / Session
                account = raw.get("account", {})
                plan_name = account.get("organizationType") or "Claude Pro"
                self.bento_val_claude.setText(f"{rem_5h:.0f}%")
                self.bento_sub_claude.setText(f"{plan_name}")
                self.bento_gauge_claude.setValue(rem_5h)
                self.bento_pill_claude.setText("OAuth Live")
                self.bento_foot_claude.setText("Sesión sincronizada")
            else:
                # Mode 0 (default): 5h rolling window PRIMARY
                self.bento_val_claude.setText(f"{rem_5h:.0f}%")
                self.bento_sub_claude.setText("Cuota 5h")
                self.bento_gauge_claude.setValue(rem_5h)
                self.bento_pill_claude.setText(desc_5h)
                self.bento_foot_claude.setText(f"Sem {rem_7d:.0f}%" + (f" · {desc_7d}" if desc_7d else ""))

            self.bento_val_claude.setStyleSheet("color: #ffffff; font-size: 26px; font-weight: 800; border: none; background: transparent;")
            self.bento_sub_claude.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 500; border: none; background: transparent;")
            self.bento_foot_claude.setStyleSheet("color: #94a3b8; font-size: 9.5px; font-weight: 500; border: none; background: transparent;")
            self.bento_pill_claude.setStyleSheet(
                "background: rgba(0, 0, 0, 0.45); border: 1px solid rgba(255, 255, 255, 0.1); "
                "color: #fef3c7; border-radius: 8px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
            )
            self.bento_foot_claude.setWordWrap(False)
            self.bento_sub_claude.setWordWrap(False)
            self.bento_dot_claude.setStyleSheet("color: #10b981; font-size: 7px;")
            self.bento_btn_claude.setText("Sync")

            # Cyberpunk
            self.cyber_seg_claude.setValue(rem_5h)
            self.cyber_lbl_claude_val.setText(f"{rem_5h:.0f}% QUOTA (5H)")
            weekly_hint = f" · 7D: {rem_7d:.0f}%" if rem_7d != rem_5h else ""
            self.cyber_lbl_claude_reset.setText(f"5H RESET: {desc_5h}{weekly_hint}".upper())

            # Minimalist
            self.mini_bar_claude.setValue(rem_5h)
            weekly_mini = f" · 7d {rem_7d:.0f}%" if rem_7d != rem_5h else ""
            self.mini_val_claude.setText(
                f'<span style="color:#ffffff; font-weight:700;">{rem_5h:.0f}%</span> '
                f'<span style="color:#64748b;">(5h {desc_5h}{weekly_mini})</span>'
            )
            if is_stale:
                stale_error = str(data.get("error") or "Última cuota local; sin conexión").strip()
                self.bento_pill_claude.setText("Caché local")
                self.bento_foot_claude.setText(stale_error[:38])
                self.bento_card_claude.setToolTip(stale_error)
                self.cyber_lbl_claude_val.setText(f"{rem_5h:.0f}% QUOTA (5H) · CACHÉ")
                self.cyber_lbl_claude_reset.setText(f"NO LIVE: {stale_error[:34]}".upper())
                self.mini_val_claude.setText(
                    f'<span style="color:#ffffff; font-weight:700;">{rem_5h:.0f}%</span> '
                    '<span style="color:#f59e0b;">(caché local)</span>'
                )
        else:
            error = str(data.get("error") or data.get("hint") or "Sin cuota verificable").strip()
            lowered = error.lower()
            if "token" in lowered and ("expir" in lowered or "401" in lowered):
                short_error = "Token expirado"
            elif "suscrip" in lowered or "acceso no permitido" in lowered or "403" in lowered:
                short_error = "Sin suscripción"
            elif "credencial" in lowered:
                short_error = "Sin credenciales"
            else:
                short_error = error[:24]
            self.bento_gauge_claude.setValue(0.0)
            self.bento_val_claude.setText("--")
            self.bento_sub_claude.setText(short_error)
            self.bento_pill_claude.setText("Sin acceso")
            self.bento_foot_claude.setText("Sin cuota verificable")
            self.bento_dot_claude.setStyleSheet("color: #f59e0b; font-size: 7px;")
            self.bento_btn_claude.setText("Connect")
            self.bento_card_claude.setToolTip(error)

            self.cyber_seg_claude.setValue(0.0)
            self.cyber_lbl_claude_val.setText(short_error.upper())
            self.cyber_lbl_claude_reset.setText("SIN CUOTA VERIFICABLE")

            self.mini_bar_claude.setValue(0.0)
            self.mini_val_claude.setText(short_error)

    def update_antigravity(self, data: dict):
        self.cached_provider_data["antigravity"] = data
        mode = self.card_display_modes.get("antigravity", 0)
        status = data.get("status")
        usage_raw = data.get("usage_percent")
        if usage_raw is None:
            usage_raw = data.get("used_percent")
        remaining_raw = data.get("remaining_percent")
        has_quota = usage_raw is not None or remaining_raw is not None
        quota_source = str(data.get("quota_source") or "")
        is_cached = quota_source == "disk_cache" and bool(data.get("stale"))
        is_live = bool(data.get("is_live", status == ProviderStatus.OK)) and not is_cached
        has_verified_quota = has_quota and (
            status == ProviderStatus.OK
            or str(status).lower().endswith("ok")
            or is_cached
            or data.get("is_exhausted")
        )

        if has_verified_quota:
            if usage_raw is not None:
                usage_pct = float(usage_raw)
                rem_pct = float(remaining_raw) if remaining_raw is not None else 100.0 - usage_pct
            elif remaining_raw is not None:
                rem_pct = float(remaining_raw)
                usage_pct = 100.0 - rem_pct
            reset_desc = str(data.get("reset_desc", "")).strip()
            reset_label = reset_desc or "--"
            windows = data.get("windows") or {}
            five_hour = windows.get("five_hour") or {}
            five_desc = str(five_hour.get("reset_desc") or reset_desc).strip()
            weekly = windows.get("weekly") or {}
            weekly_rem = weekly.get("remaining_percent")
            weekly_desc = str(weekly.get("reset_desc") or "").strip()
            freshness = "Reinicio confirmado" if is_live else "Último dato · sin conexión"
            model_lines = []
            for model in data.get("models") or []:
                if not isinstance(model, dict) or model.get("remaining_percent") is None:
                    continue
                try:
                    model_rem = float(model["remaining_percent"])
                except (TypeError, ValueError):
                    continue
                model_label = str(model.get("label") or model.get("model_id") or "Modelo")
                model_reset = str(model.get("reset_desc") or "").strip()
                model_lines.append(
                    f"{model_label}: {model_rem:.1f}%"
                    + (f" ({model_reset})" if model_reset else "")
                )
            model_tooltip = "Antigravity · cuota real por modelo"
            if model_lines:
                model_tooltip += "\n" + "\n".join(model_lines)
            self.bento_card_ag.setToolTip(model_tooltip)
            self.cyber_card_ag.setToolTip(model_tooltip)

            # Primary display is ALWAYS the 5-hour rolling window quota
            display_rem = rem_pct
            display_desc = five_desc or reset_desc

            # Bento View
            self.bento_gauge_ag.setVisible(True)
            self.bento_pill_ag.setVisible(True)
            self.bento_foot_ag.setVisible(True)
            self.bento_val_ag.setVisible(True)
            self.bento_sub_ag.setVisible(True)
            if mode == 1:
                # Mode 1: Weekly breakdown
                shown_rem = float(weekly_rem) if weekly_rem is not None else display_rem
                self.bento_val_ag.setText(f"{shown_rem:.0f}%")
                self.bento_sub_ag.setText("Cuota semanal")
                self.bento_gauge_ag.setValue(shown_rem)
                self.bento_pill_ag.setText(weekly_desc or display_desc or "Semanal")
                self.bento_foot_ag.setText(f"5h reinicia {display_desc}" if display_desc else freshness)
            elif mode == 2:
                # Mode 2: Details / Plan info
                plan_name = data.get("plan_name") or "Antigravity"
                self.bento_val_ag.setText(f"{display_rem:.0f}%")
                self.bento_sub_ag.setText(f"{plan_name}")
                self.bento_gauge_ag.setValue(display_rem)
                self.bento_pill_ag.setText(display_desc if display_desc else "5h")
                self.bento_foot_ag.setText(freshness)
            else:
                # Mode 0 (default): 5h rolling window PRIMARY
                self.bento_val_ag.setText(f"{display_rem:.0f}%")
                self.bento_sub_ag.setText("Cuota 5h")
                self.bento_gauge_ag.setValue(display_rem)
                self.bento_pill_ag.setText(display_desc if display_desc else "5h Activa")
                if weekly_rem is not None and weekly_desc:
                    self.bento_foot_ag.setText(f"Sem {float(weekly_rem):.0f}% · {weekly_desc}")
                elif weekly_rem is not None:
                    self.bento_foot_ag.setText(f"Sem {float(weekly_rem):.0f}%")
                else:
                    self.bento_foot_ag.setText(f"5h reinicia {five_desc}" if five_desc else freshness)

            self.bento_foot_ag.setWordWrap(False)
            self.bento_sub_ag.setWordWrap(False)
            self.bento_card_ag.setToolTip(model_tooltip)
            self.bento_pill_ag.setStyleSheet(
                "background: rgba(0, 0, 0, 0.45); border: 1px solid rgba(255, 255, 255, 0.1); "
                "color: #fef3c7; border-radius: 8px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
            )
            self.bento_dot_ag.setVisible(False)

            # Cyberpunk
            self.cyber_seg_ag.setValue(display_rem)
            self.cyber_lbl_ag_val.setText(f"{display_rem:.0f}% CUOTA (5H)")
            reset_parts = []
            if display_desc:
                reset_parts.append(f"5H RESET {display_desc}")
            if weekly_rem is not None and weekly_desc:
                reset_parts.append(f"SEM {weekly_desc}")
            self.cyber_lbl_ag_reset.setText(" · ".join(reset_parts).upper() or "RESET SIN DATOS")

            # Minimalist
            self.mini_bar_ag.setValue(display_rem)
            suffix_parts = []
            if display_desc:
                suffix_parts.append(f"5h {display_desc}")
            if weekly_rem is not None and weekly_desc:
                suffix_parts.append(f"sem {weekly_desc}")
            suffix = f"({' · '.join(suffix_parts)})" if suffix_parts else f"({freshness.lower()})"
            self.mini_val_ag.setText(
                f'<span style="color:#ffffff; font-weight:700;">{display_rem:.0f}%</span> '
                f'<span style="color:#64748b;">{suffix}</span>'
            )
        else:
            windows = data.get("windows") or {}
            five_desc = str((windows.get("five_hour") or {}).get("reset_desc") or "").strip()
            self.bento_gauge_ag.setValue(0.0)
            self.bento_val_ag.setText("--")
            self.bento_sub_ag.setText("Cuota no publicada")
            self.bento_foot_ag.setText(f"5h reinicia {five_desc}" if five_desc else "Sin cuota verificable")
            self.bento_pill_ag.setText("--")
            self.bento_dot_ag.setVisible(False)

            self.cyber_seg_ag.setValue(0.0)
            self.cyber_lbl_ag_val.setText("CUOTA NO PUBLICADA")
            self.cyber_lbl_ag_reset.setText(f"5H RESET {five_desc}".upper() if five_desc else "SIN CUOTA VERIFICABLE")

            self.mini_bar_ag.setValue(0.0)
            self.mini_val_ag.setText("Sin datos")

    def update_quota_provider(self, provider_name: str, data: dict):
        if provider_name in self._EXTENDED_PROVIDER_DEFS and provider_name not in self.bento_ai_cards:
            self._ensure_ai_card(provider_name)
            self._apply_ai_visibility()

        self.cached_provider_data[provider_name] = data
        bento_item = self.bento_ai_cards.get(provider_name)
        if bento_item:
            # Compact cards must stay compact at 60–80%; values are already shortened below.
            bento_item["foot"].setWordWrap(False)
            bento_item["subtitle"].setWordWrap(False)
        cyber_item = self.cyber_ai_cards.get(provider_name)
        mini_item = self.mini_ai_rows.get(provider_name)

        mode = self.card_display_modes.get(provider_name, 0)
        status = data.get("status")
        ok = status == ProviderStatus.OK or str(status).lower().endswith("ok")

        if not ok:
            status_text = str(getattr(status, "value", status) or "").lower()
            loading = status_text == ProviderStatus.LOADING.value
            stale = status_text == ProviderStatus.STALE.value
            error = "Actualizando" if loading else str(data.get("error") or "No disponible")
            error_lower = error.lower()
            if loading:
                visible_error = error
            elif "no configur" in error_lower and ("api key" in error_lower or "token" in error_lower):
                visible_error = "Sin API key"
            elif "token" in error_lower and "expir" in error_lower:
                visible_error = "Token expirado"
            elif "suscrip" in error_lower:
                visible_error = "Sin suscripción"
            else:
                visible_error = error[:22]
            if bento_item:
                bento_item["card"].setToolTip(error)
                bento_item["gauge"].setValue(0.0)
                bento_item["gauge"].setVisible(False)
                bento_item["value"].setText("--")
                bento_item["value"].setVisible(True)
                bento_item["subtitle"].setText(visible_error)
                bento_item["foot"].setText("Sin verificar" if stale else "")
                bento_item["foot"].setVisible(stale)
                bento_item["pill"].setText("Error")
                bento_item["pill"].setVisible(False)
                bento_item["setup"].setText("Config")
                bento_item["setup"].setVisible(not loading)
                bento_item["dot"].setVisible(False)
            if cyber_item:
                cyber_item["card"].setToolTip(error)
                cyber_item["seg"].setValue(0.0)
                if cyber_item.get("status") is not None:
                    cyber_item["status"].setText("SIN DATOS")
                cyber_item["val"].setText("--" if loading else ("SIN VERIFICAR" if stale else "OFFLINE"))
                cyber_item["reset"].setText(visible_error if (loading or stale) else f"ERR: {visible_error[:16]}")
            if mini_item:
                mini_item["row"].setToolTip(error)
                mini_item["bar"].setValue(0.0)
                mini_item["val"].setText("Actualizando" if loading else ("Sin verificar" if stale else visible_error))
            return

        used = float(data.get("used_percent", 0.0))
        remaining = float(data.get("remaining_percent", 100.0 - used))
        label = str(data.get("primary_label") or "Cuota")
        secondary = data.get("secondary_used_percent")
        secondary_label = str(data.get("secondary_label") or "")
        reset_desc = str(data.get("reset_desc") or "")
        count_rem = data.get("count_remaining")
        count_tot = data.get("count_total")
        count_used = data.get("count_used")
        if count_used is None and count_rem is not None and count_tot is not None:
            try:
                count_used = max(0.0, float(count_tot) - float(count_rem))
            except (TypeError, ValueError):
                count_used = None
        is_unlimited = bool(data.get("is_unlimited", False))

        windows = data.get("windows") or {}
        sec_window = windows.get("secondary", {})
        sec_rem = sec_window.get("remaining_percent")
        sec_desc = sec_window.get("reset_desc", "")
        weekly_window = windows.get("weekly") or (sec_window if provider_name == "codex" else {})
        weekly_rem = weekly_window.get("remaining_percent")
        weekly_desc = str(weekly_window.get("reset_desc") or "")

        # --- 1. Bento Glass View ---
        if bento_item:
            if is_unlimited:
                bento_item["value"].setText("")
                bento_item["value"].setVisible(False)
                bento_item["subtitle"].setText("Unlimited Web")
                bento_item["subtitle"].setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: 500; border: none; background: transparent;")
                bento_item["foot"].setText("")
                bento_item["foot"].setVisible(False)
                bento_item["pill"].setText("")
                bento_item["pill"].setVisible(False)
                bento_item["gauge"].setVisible(False)
                bento_item["setup"].setVisible(False)
                bento_item["dot"].setVisible(False)
            elif provider_name == "copilot" and count_rem is not None and count_tot is not None:
                short_reset = reset_desc.replace(" 2026", "").replace(" 2025", "") if reset_desc else "1 Oct"
                shown_used = float(count_used) if count_used is not None else max(0.0, float(count_tot) - float(count_rem))
                bento_item["value"].setText(f"{shown_used:g}/{float(count_tot):g}")
                bento_item["value"].setStyleSheet("color: #ffffff; font-size: 22px; font-weight: 800; border: none; background: transparent;")
                bento_item["subtitle"].setText("premium used")
                bento_item["subtitle"].setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 500; border: none; background: transparent;")
                bento_item["foot"].setText(short_reset)
                bento_item["foot"].setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 500; border: none; background: transparent;")
                bento_item["value"].setVisible(True)
                bento_item["subtitle"].setVisible(True)
                bento_item["foot"].setVisible(True)
                bento_item["pill"].setVisible(False)
                bento_item["gauge"].setVisible(True)
                bento_item["gauge"].setCustomColor("#f59e0b")
                bento_item["gauge"].setValue((shown_used / float(count_tot)) * 100.0 if count_tot else 0.0)
                bento_item["setup"].setVisible(False)
                bento_item["dot"].setVisible(False)
            elif provider_name == "codex":
                p_win = windows.get("primary") or {}
                rem_5h = float(p_win.get("remaining_percent", remaining))
                desc_5h = str(p_win.get("reset_desc") or reset_desc or "4h 50m").strip()
                w_win = weekly_window or {}
                rem_wk = w_win.get("remaining_percent")
                desc_wk = str(w_win.get("reset_desc") or "").strip()

                bento_item["value"].setVisible(True)
                bento_item["subtitle"].setVisible(True)
                bento_item["gauge"].setVisible(True)
                bento_item["pill"].setVisible(True)
                bento_item["foot"].setVisible(True)

                if mode == 1:
                    # Mode 1: Weekly Quota
                    shown_pct = float(rem_wk) if rem_wk is not None else rem_5h
                    bento_item["value"].setText(f"{shown_pct:.0f}%")
                    bento_item["subtitle"].setText("Cuota semanal")
                    bento_item["gauge"].setValue(shown_pct)
                    bento_item["pill"].setText(desc_wk or "--")
                    bento_item["foot"].setText(f"5h: {rem_5h:.0f}% · {desc_5h}")
                elif mode == 2:
                    # Mode 2: Details
                    bento_item["value"].setText(f"{rem_5h:.0f}%")
                    bento_item["subtitle"].setText("Codex Plus")
                    bento_item["gauge"].setValue(rem_5h)
                    bento_item["pill"].setText(desc_5h)
                    bento_item["foot"].setText(f"Plan: {data.get('plan') or 'Plus'}")
                else:
                    # Mode 0 (default): 5h rolling window PRIMARY
                    bento_item["value"].setText(f"{rem_5h:.0f}%")
                    bento_item["subtitle"].setText("Cuota 5h")
                    bento_item["gauge"].setValue(rem_5h)
                    bento_item["pill"].setText(desc_5h)
                    if rem_wk is not None and desc_wk:
                        bento_item["foot"].setText(f"Sem {float(rem_wk):.0f}% · {desc_wk}")
                    elif rem_wk is not None:
                        bento_item["foot"].setText(f"Sem {float(rem_wk):.0f}%")
                    else:
                        bento_item["foot"].setText("Reinicio confirmado")

                bento_item["value"].setStyleSheet("color: #ffffff; font-size: 26px; font-weight: 800; border: none; background: transparent;")
                bento_item["subtitle"].setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 500; border: none; background: transparent;")
                bento_item["foot"].setStyleSheet("color: #94a3b8; font-size: 9.5px; font-weight: 500; border: none; background: transparent;")
                bento_item["pill"].setStyleSheet(
                    "background: rgba(0, 0, 0, 0.45); border: 1px solid rgba(255, 255, 255, 0.1); "
                    "color: #fef3c7; border-radius: 8px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
                )
                bento_item["setup"].setVisible(False)
                bento_item["dot"].setVisible(False)
            elif provider_name == "gemini":
                gemini_remaining = float(weekly_rem) if weekly_rem is not None else remaining
                gemini_reset = weekly_desc or reset_desc or "pendiente"
                bento_item["value"].setVisible(True)
                bento_item["subtitle"].setVisible(True)
                bento_item["foot"].setVisible(True)
                bento_item["value"].setText(f"{gemini_remaining:.0f}%")
                bento_item["value"].setStyleSheet("color: #ffffff; font-size: 26px; font-weight: 800; border: none; background: transparent;")
                bento_item["subtitle"].setText("Cuota semanal" if weekly_rem is not None else "Remaining quota")
                bento_item["subtitle"].setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 500; border: none; background: transparent;")
                bento_item["foot"].setText(f"reinicia {gemini_reset}")
                bento_item["foot"].setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 500; border: none; background: transparent;")
                bento_item["pill"].setVisible(False)
                bento_item["gauge"].setVisible(True)
                bento_item["gauge"].setValue(gemini_remaining)
                bento_item["setup"].setVisible(False)
                bento_item["dot"].setVisible(False)
            elif provider_name == "cursor":
                fast_txt = f"{count_rem}/{count_tot}" if (count_rem is not None and count_tot is not None) else f"{remaining:.0f}%"
                bento_item["value"].setVisible(True)
                bento_item["subtitle"].setVisible(True)
                bento_item["foot"].setVisible(True)
                bento_item["value"].setText(fast_txt)
                bento_item["value"].setStyleSheet("color: #ffffff; font-size: 22px; font-weight: 800; border: none; background: transparent;")
                bento_item["subtitle"].setText("fast requests")
                bento_item["subtitle"].setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 500; border: none; background: transparent;")
                bento_item["foot"].setText(f"resets {reset_desc}" if reset_desc else "reset sin datos")
                bento_item["foot"].setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 500; border: none; background: transparent;")
                bento_item["pill"].setVisible(False)
                bento_item["gauge"].setVisible(True)
                bento_item["gauge"].setCustomColor("#8b5cf6")
                bento_item["gauge"].setValue((float(count_rem) / float(count_tot) * 100.0) if (count_rem is not None and count_tot) else remaining)
                bento_item["setup"].setVisible(False)
                bento_item["dot"].setVisible(False)
            elif provider_name in ("openrouter", "deepseek", "kimi"):
                sub_label = "API Balance" if provider_name != "openrouter" else "Credits Balance"
                if mode == 1:
                    if provider_name == "openrouter" and secondary_label:
                        bento_item["value"].setText(secondary_label.replace(" used", ""))
                        bento_item["subtitle"].setText("Total Usage")
                        bento_item["foot"].setText(f"Bal: {label}")
                    elif sec_window.get("value"):
                        bento_item["value"].setText(label)
                        bento_item["subtitle"].setText(sec_window.get("label", "Breakdown")[:18])
                        bento_item["foot"].setText(sec_window.get("value", "")[:20])
                    else:
                        bento_item["value"].setText(label)
                        bento_item["subtitle"].setText(sub_label)
                        bento_item["foot"].setText(secondary_label or "Active")
                elif mode == 2:
                    bento_item["value"].setText("Active")
                    bento_item["subtitle"].setText(provider_name.title())
                    bento_item["foot"].setText(reset_desc or "Prepaid")
                else:
                    bento_item["value"].setText(label)
                    bento_item["subtitle"].setText(sub_label)
                    r_foot = f"used {secondary_label}" if secondary_label else (reset_desc if reset_desc else "Active")
                    bento_item["foot"].setText(r_foot)

                bento_item["value"].setStyleSheet("color: #ffffff; font-size: 22px; font-weight: 800; border: none; background: transparent;")
                bento_item["subtitle"].setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 500; border: none; background: transparent;")
                bento_item["foot"].setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 500; border: none; background: transparent;")
                bento_item["pill"].setVisible(False)
                bento_item["gauge"].setVisible(True)
                bento_item["gauge"].setValue(remaining if used > 0 else 100.0)
                bento_item["setup"].setVisible(False)
                bento_item["dot"].setVisible(False)
            elif provider_name == "perplexity":
                if mode == 1:
                    bento_item["value"].setText("Search")
                    bento_item["subtitle"].setText("Pro Search")
                    bento_item["foot"].setText("Unlimited")
                elif mode == 2:
                    bento_item["value"].setText("Active")
                    bento_item["subtitle"].setText("Subscription")
                    bento_item["foot"].setText("Perplexity AI")
                else:
                    bento_item["value"].setText(label)
                    bento_item["subtitle"].setText("Perplexity Pro")
                    bento_item["foot"].setText(reset_desc if reset_desc else "Active Subscription")
                bento_item["value"].setStyleSheet("color: #ffffff; font-size: 22px; font-weight: 800; border: none; background: transparent;")
                bento_item["pill"].setVisible(False)
                bento_item["gauge"].setVisible(False)
                bento_item["setup"].setVisible(False)
                bento_item["dot"].setVisible(False)
            else:
                bento_item["value"].setVisible(True)
                bento_item["foot"].setVisible(True)
                bento_item["gauge"].setVisible(True)
                bento_item["value"].setText(f"{remaining:.0f}%")
                bento_item["subtitle"].setText("Remaining quota")
                bento_item["foot"].setText(f"resets {reset_desc}" if reset_desc else "resets in")
                bento_item["pill"].setVisible(False)
                bento_item["gauge"].setValue(remaining)
                bento_item["setup"].setVisible(False)
                bento_item["dot"].setVisible(False)

        # --- 2. Cyberpunk HUD View ---
        if cyber_item:
            status_w = cyber_item.get("status")
            if provider_name == "codex":
                p_win = windows.get("primary") or {}
                rem_5h = float(p_win.get("remaining_percent", remaining))
                desc_5h = str(p_win.get("reset_desc") or reset_desc or "PENDING").strip()
                w_win = weekly_window or {}
                rem_wk = w_win.get("remaining_percent")
                desc_wk = str(w_win.get("reset_desc") or "").strip()

                cyber_item["seg"].setVisible(True)
                cyber_item["seg"].setValue(rem_5h)
                if cyber_item.get("status") is not None:
                    cyber_item["status"].setVisible(False)
                cyber_item["val"].setText(f"{rem_5h:.0f}% QUOTA (5H)")
                weekly_hint = f" · SEM: {float(rem_wk):.0f}% / {desc_wk}" if (rem_wk is not None and desc_wk) else (f" · SEM: {float(rem_wk):.0f}%" if rem_wk is not None else "")
                cyber_item["reset"].setText(f"RESET 5H: {desc_5h}{weekly_hint}".upper())
            elif provider_name == "gemini":
                gemini_pct = float(weekly_rem) if weekly_rem is not None else remaining
                cyber_item["seg"].setValue(gemini_pct)
                cyber_item["val"].setText(f"QUOTA: {gemini_pct:.0f}% SEMANAL" if weekly_rem is not None else f"QUOTA: {gemini_pct:.0f}% LEFT")
                cyber_item["reset"].setText(f"RESET: {(weekly_desc or reset_desc or 'PENDING')}")
            elif provider_name == "copilot":
                if count_rem is not None and count_tot is not None:
                    shown_used = float(count_used) if count_used is not None else max(0.0, float(count_tot) - float(count_rem))
                    used_p = (shown_used / float(count_tot) * 100.0)
                    cyber_item["seg"].setValue(used_p)
                    cyber_item["val"].setText(f"QUOTA: {shown_used:g}/{float(count_tot):g} ({used_p:.0f}% USED)")
                else:
                    cyber_item["seg"].setValue(used)
                    cyber_item["val"].setText(f"QUOTA: {used:.0f}% USED")
                r_date = reset_desc if reset_desc else "1 OCT 2026"
                cyber_item["reset"].setText(f"RESET DATE: {r_date}".upper())
            elif provider_name == "grok":
                if status_w:
                    status_w.setText("ACTIVE" if ok else "OFFLINE")
                cyber_item["seg"].setVisible(not is_unlimited)
                if is_unlimited:
                    cyber_item["val"].setText("PLAN: FREE WEB")
                    cyber_item["reset"].setText("RESET: ACTIVE")
                else:
                    cyber_item["seg"].setValue(remaining)
                    cyber_item["val"].setText(f"QUOTA: {remaining:.0f}% LEFT")
                    r_date = reset_desc if reset_desc else "PENDING"
                    cyber_item["reset"].setText(f"RESET DATE: {r_date}".upper())
            elif provider_name == "cursor":
                if status_w:
                    status_w.setText("ACTIVE" if ok else "OFFLINE")
                    status_w.setStyleSheet("color: #a855f7; font-size: 15px; font-weight: 800; font-family: monospace;")
                calc_rem = (float(count_rem) / float(count_tot) * 100.0) if (count_rem is not None and count_tot) else remaining
                cyber_item["seg"].setValue(calc_rem)
                req_txt = f"{count_rem}/{count_tot}" if (count_rem is not None and count_tot is not None) else f"{remaining:.0f}%"
                cyber_item["val"].setText(f"FAST: {req_txt} ({calc_rem:.0f}%)")
                r_desc = reset_desc if reset_desc else "--"
                cyber_item["reset"].setText(f"RESET: {r_desc}".upper())
            elif provider_name in ("openrouter", "deepseek", "kimi"):
                cyber_item["seg"].setValue(remaining if used > 0 else 100.0)
                if mode == 1 and secondary_label:
                    cyber_item["val"].setText(f"USED: {secondary_label}".upper())
                    cyber_item["reset"].setText(f"BAL: {label}".upper())
                elif mode == 2:
                    cyber_item["val"].setText(f"PLAN: {provider_name.upper()}")
                    cyber_item["reset"].setText(f"TIER: PREPAID ({label})".upper())
                else:
                    cyber_item["val"].setText(f"BAL: {label}")
                    cyber_item["reset"].setText(f"STATUS: ONLINE ({secondary_label})" if secondary_label else "STATUS: ONLINE")
            elif provider_name == "perplexity":
                cyber_item["seg"].setValue(100.0)
                if mode == 1:
                    cyber_item["val"].setText("PRO SEARCH")
                    cyber_item["reset"].setText("TIER: UNLIMITED")
                elif mode == 2:
                    cyber_item["val"].setText("PERPLEXITY PRO")
                    cyber_item["reset"].setText("STATUS: ONLINE")
                else:
                    cyber_item["val"].setText("PRO ACTIVE")
                    cyber_item["reset"].setText("SEARCH: UNLIMITED")
            else:
                cyber_item["seg"].setValue(remaining)
                if is_unlimited:
                    cyber_item["val"].setText("UNLIMITED WEB")
                    cyber_item["reset"].setText("RESET: ACTIVE")
                else:
                    cyber_item["val"].setText(f"{remaining:.0f}% REMAINING")
                    cyber_item["reset"].setText(f"RESET: {reset_desc}".upper() if reset_desc else "ACTIVE")

        # --- 3. Minimalist Compact View ---
        if mini_item:
            if is_unlimited:
                mini_item["bar"].setVisible(False)
                r_str = f" (Resets {reset_desc})" if reset_desc else ""
                mini_item["val"].setText(f'<span style="color:#64748b; font-weight:500;">Free Web{r_str}</span>')
            elif provider_name == "copilot":
                mini_item["bar"].setVisible(True)
                shown_used = float(count_used) if count_used is not None else (
                    max(0.0, float(count_tot) - float(count_rem))
                    if count_rem is not None and count_tot is not None else used
                )
                used_val = (shown_used / float(count_tot) * 100.0) if count_tot else used
                mini_item["bar"].setValue(used_val)
                req_txt = f"{shown_used:g}/{float(count_tot):g}" if count_tot is not None else f"{used:.0f}%"
                mini_item["val"].setText(f'<span style="color:#ffffff; font-weight:700;">{req_txt}</span> <span style="color:#64748b;">(used)</span>')
            elif provider_name == "codex":
                p_win = windows.get("primary") or {}
                rem_5h = float(p_win.get("remaining_percent", remaining))
                desc_5h = str(p_win.get("reset_desc") or reset_desc or "pendiente").strip()
                w_win = weekly_window or {}
                rem_wk = w_win.get("remaining_percent")
                desc_wk = str(w_win.get("reset_desc") or "").strip()

                mini_item["bar"].setVisible(True)
                mini_item["bar"].setValue(rem_5h)
                primary_color = "#ef4444" if rem_5h <= 0 else "#ffffff"
                weekly_hint = f" · sem {float(rem_wk):.0f}%/{desc_wk}" if (rem_wk is not None and desc_wk) else (f" · sem {float(rem_wk):.0f}%" if rem_wk is not None else "")
                reset_hint = f"5h {desc_5h}{weekly_hint}"
                mini_item["val"].setText(f'<span style="color:{primary_color}; font-weight:700;">{rem_5h:.0f}%</span> <span style="color:#64748b;">({reset_hint})</span>')
            elif provider_name == "gemini":
                gemini_remaining = float(weekly_rem) if weekly_rem is not None else remaining
                mini_item["bar"].setVisible(True)
                mini_item["bar"].setValue(gemini_remaining)
                gemini_reset = weekly_desc or reset_desc
                suffix = f"(semanal · {gemini_reset})" if gemini_reset else "(semanal)"
                mini_item["val"].setText(f'<span style="color:#ffffff; font-weight:700;">{gemini_remaining:.0f}%</span> <span style="color:#64748b;">{suffix}</span>')
            elif provider_name == "cursor":
                mini_item["bar"].setVisible(True)
                rem_val = (float(count_rem) / float(count_tot) * 100.0) if (count_rem is not None and count_tot) else remaining
                mini_item["bar"].setValue(rem_val)
                req_txt = f"{count_rem}/{count_tot}" if (count_rem is not None and count_tot is not None) else f"{remaining:.0f}%"
                r_desc = f" ({reset_desc})" if reset_desc else " (Fast)"
                mini_item["val"].setText(f'<span style="color:#ffffff; font-weight:700;">{req_txt}</span> <span style="color:#64748b;">{r_desc}</span>')
            elif provider_name in ("openrouter", "deepseek", "kimi"):
                mini_item["bar"].setVisible(True)
                mini_item["bar"].setValue(remaining if used > 0 else 100.0)
                mini_item["val"].setText(f'<span style="color:#ffffff; font-weight:700;">{label}</span> <span style="color:#64748b;">(Bal)</span>')
            elif provider_name == "perplexity":
                mini_item["bar"].setVisible(False)
                mini_item["val"].setText('<span style="color:#06b6d4; font-weight:700;">Pro</span> <span style="color:#64748b;">(Active)</span>')
            else:
                mini_item["bar"].setVisible(True)
                mini_item["bar"].setValue(remaining)
                mini_item["val"].setText(f'<span style="color:#ffffff; font-weight:700;">{remaining:.0f}%</span> <span style="color:#64748b;">({reset_desc})</span>' if reset_desc else f'<span style="color:#ffffff; font-weight:700;">{remaining:.0f}%</span>')

    def _provider_action(self, provider_name: str):
        controls = self.bento_ai_cards.get(provider_name)
        if controls and controls["setup"].text() == "Actualizar":
            controls["setup"].setEnabled(False)
            controls["setup"].setText("…")
            self.reload_requested.emit()
        else:
            self.provider_setup_requested.emit(provider_name)

    def _claude_action(self):
        if self.bento_btn_claude.text() == "Sync":
            self.reload_requested.emit()
        else:
            self._open_claude_dialog()

    def _open_claude_dialog(self):
        if self.claude_provider:
            dlg = ClaudeConnectDialog(self.claude_provider, self)
            dlg.credentials_updated.connect(self.reload_requested.emit)
            dlg.exec()

    def _open_hotkey_dialog(self):
        dlg = HotkeyBindDialog(self.hotkey_config, self)
        dlg.hotkey_saved.connect(self._on_hotkey_saved)
        dlg.exec()

    def _on_hotkey_saved(self, new_config: dict):
        self.hotkey_config = new_config
        txt = format_hotkey_display(new_config.get("modifiers", ["ctrl"]), new_config.get("key", "period"))
        self.hotkey_badge.setText(txt)
        self.hotkey_changed.emit(new_config)

    def _toggle_ai_module(self, key: str):
        provider_id = key.replace("show_", "")
        current = self.ai_modules.get(
            key,
            True if provider_id in ("antigravity", "codex", "copilot", "grok", "cursor") else False
        )
        new_val = not current
        self.ai_modules[key] = new_val
        if new_val and provider_id in self._EXTENDED_PROVIDER_DEFS:
            self._ensure_ai_card(provider_id)
        self._apply_ai_visibility()
        self.apply_scale(self.ui_scale, save=False)
        self.ai_modules_changed.emit(dict(self.ai_modules))

    def _on_close_clicked(self):
        self.btn_close.setEnabled(False)
        self.close_requested.emit()

    # -----------------------------------------------------------------
    # RENDERIZADO DEL FONDO SEGÚN EL TEMA
    # -----------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)

        if self.theme_style == "cyberpunk_hud":
            # Cyberpunk HUD: esquinas angulares, fondo deep cyber y borde neón cyan
            path = QPainterPath()
            path.addRoundedRect(rect, 4, 4)
            painter.fillPath(path, QColor(7, 11, 18, 248))

            pen = QPen(QColor(6, 182, 212, 190))
            pen.setWidthF(1.2)
            painter.setPen(pen)
            painter.drawPath(path)

            # Corchetes tácticos en las 4 esquinas
            accent_pen = QPen(QColor(6, 182, 212, 255))
            accent_pen.setWidthF(2.5)
            painter.setPen(accent_pen)
            # Top-left
            painter.drawLine(rect.left(), rect.top() + 14, rect.left(), rect.top())
            painter.drawLine(rect.left(), rect.top(), rect.left() + 14, rect.top())
            # Top-right
            painter.drawLine(rect.right() - 14, rect.top(), rect.right(), rect.top())
            painter.drawLine(rect.right(), rect.top(), rect.right(), rect.top() + 14)
            # Bottom-left
            painter.drawLine(rect.left(), rect.bottom() - 14, rect.left(), rect.bottom())
            painter.drawLine(rect.left(), rect.bottom(), rect.left() + 14, rect.bottom())
            # Bottom-right
            painter.drawLine(rect.right() - 14, rect.bottom(), rect.right(), rect.bottom())
            painter.drawLine(rect.right(), rect.bottom(), rect.right(), rect.bottom() - 14)

        elif self.theme_style == "minimalist_compact":
            # Minimalist Compact: acabado mate oscuro suizo y sutil borde
            path = QPainterPath()
            path.addRoundedRect(rect, 8, 8)
            painter.fillPath(path, QColor(16, 18, 24, 252))

            pen = QPen(QColor(38, 43, 58, 200))
            pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.drawPath(path)

        else:
            # Bento Glassmorphism: Frosted Glass con degradado profundo y borde cristal especular
            path = QPainterPath()
            path.addRoundedRect(rect, 22, 22)

            grad = QLinearGradient(0, 0, self.width(), self.height())
            grad.setColorAt(0.0, QColor(26, 32, 44, 240))
            grad.setColorAt(0.5, QColor(18, 22, 30, 244))
            grad.setColorAt(1.0, QColor(12, 16, 22, 248))
            painter.fillPath(path, grad)

            pen = QPen(QColor(255, 255, 255, 26))
            pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.drawPath(path)

        painter.end()

    # -----------------------------------------------------------------
    # GESTIÓN DEL RATÓN Y MENÚ CONTEXTUAL
    # -----------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if self._drag_pos is not None:
            self._drag_pos = None
            pos = self.pos()
            self.position_changed.emit(pos.x(), pos.y())
        event.accept()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #121218;
                color: #e2e8f0;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
                padding: 4px;
                font-family: 'Segoe UI', Inter, sans-serif;
                font-size: 11px;
            }
            QMenu::item {
                padding: 6px 14px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #2563eb;
                color: #FFFFFF;
            }
            QMenu::separator {
                height: 1px;
                background: rgba(255, 255, 255, 0.08);
                margin: 4px 6px;
            }
        """)

        # Selector de Tema Visual
        theme_menu = menu.addMenu("Estilo Visual / Theme")
        theme_menu.setStyleSheet(menu.styleSheet())
        themes = [
            ("bento_glass", "Bento Glassmorphism (Default)"),
            ("cyberpunk_hud", "Cyberpunk HUD"),
            ("minimalist_compact", "Minimalist Compact"),
        ]
        for t_id, t_lbl in themes:
            act = QAction(f"{'● ' if self.theme_style == t_id else '   '}{t_lbl}", self)
            act.triggered.connect(lambda chk=False, target=t_id: self.set_theme(target))
            theme_menu.addAction(act)

        menu.addSeparator()

        hotkey_str = format_hotkey_display(
            self.hotkey_config.get("modifiers", ["ctrl"]),
            self.hotkey_config.get("key", "period")
        )
        hide_act = QAction(f"Ocultar Overlay ({hotkey_str})", self)
        hide_act.triggered.connect(self.hide_requested.emit)
        menu.addAction(hide_act)

        hotkey_act = QAction("Configurar Atajo Global...", self)
        hotkey_act.triggered.connect(self._open_hotkey_dialog)
        menu.addAction(hotkey_act)

        self.add_content_menu(menu)
        self.add_scale_menu(menu)

        ai_menu = menu.addMenu("Mostrar Proveedores")
        ai_menu.setStyleSheet(menu.styleSheet())
        provider_labels = {
            "claude": "Claude Code",
            "antigravity": "Antigravity",
            "codex": "Codex Plus",
            "gemini": "Gemini CLI",
            "copilot": "GitHub Copilot",
            "grok": "Grok",
            "cursor": "Cursor AI",
            "openrouter": "OpenRouter",
            "deepseek": "DeepSeek",
            "kimi": "Kimi K2 (Moonshot)",
            "perplexity": "Perplexity",
        }
        all_candidate_ids = (
            "claude", "antigravity", "codex", "gemini", "copilot", "grok", "cursor",
            "openrouter", "deepseek", "kimi", "perplexity"
        )
        for provider_id in all_candidate_ids:
            key = f"show_{provider_id}"
            default_show = True if provider_id in ("antigravity", "codex", "copilot", "grok", "cursor") else False
            shown = self.ai_modules.get(key, default_show)
            label = provider_labels.get(provider_id, provider_id.title())
            action = QAction(f"{'✓ ' if shown else '   '}{label}", self)
            action.triggered.connect(lambda checked=False, key=key: self._toggle_ai_module(key))
            ai_menu.addAction(action)

        reload_act = QAction("Actualizar Telemetría", self)
        reload_act.triggered.connect(self.reload_requested.emit)
        menu.addAction(reload_act)

        menu.addSeparator()

        quit_act = QAction("Salir de Widget OSD", self)
        quit_act.triggered.connect(self.close_requested.emit)
        menu.addAction(quit_act)

        menu.exec(event.globalPos())
