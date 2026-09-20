"""
hotkey_dialog.py — Diálogo modal para captura y reasignación de atajos de teclado globales.
Estilo de diseño industrial sobrio y elegante (Raycast / Linear keybinder).
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QKeyEvent
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


def format_hotkey_display(modifiers: list[str], key: str) -> str:
    """Convierte la estructura de configuración en un texto limpio de atajo de teclado."""
    parts = []
    mod_map = {
        "ctrl": "Ctrl",
        "control": "Ctrl",
        "alt": "Alt",
        "shift": "Shift",
        "win": "Win",
        "meta": "Win"
    }
    for m in modifiers:
        parts.append(mod_map.get(m.lower(), m.capitalize()))

    key_map = {
        "period": ".",
        "numpad_decimal": ".",
        "comma": ",",
        "minus": "-",
        "plus": "+",
        "space": "Space",
        "tab": "Tab",
        "grave": "`",
        "slash": "/",
        "backslash": "\\"
    }
    k_disp = key_map.get(key.lower(), key.upper())
    parts.append(k_disp)
    return " + ".join(parts)


class KeyRecordButton(QPushButton):
    """Control de captura interactivo con estética Keycap."""
    hotkey_captured = Signal(list, str)

    def __init__(self, current_modifiers: list[str], current_key: str, parent=None):
        super().__init__(parent)
        self.modifiers = list(current_modifiers)
        self.key = current_key
        self.recording = False

        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFixedHeight(46)
        self.update_style()
        self.clicked.connect(self.start_recording)

    def update_style(self):
        if self.recording:
            self.setText("Press combination (e.g. Ctrl + . or F9)...")
            self.setStyleSheet("""
                QPushButton {
                    background-color: rgba(37, 99, 235, 0.12);
                    color: #60a5fa;
                    border: 1px solid #3b82f6;
                    border-radius: 8px;
                    font-size: 12px;
                    font-weight: 600;
                    font-family: 'Segoe UI', Inter, sans-serif;
                }
            """)
        else:
            txt = format_hotkey_display(self.modifiers, self.key)
            self.setText(txt)
            self.setStyleSheet("""
                QPushButton {
                    background-color: rgba(255, 255, 255, 0.04);
                    color: #f8fafc;
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    border-radius: 8px;
                    font-size: 14px;
                    font-weight: 700;
                    font-family: 'Segoe UI', Inter, sans-serif;
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 0.08);
                    border-color: #3b82f6;
                    color: #ffffff;
                }
            """)

    def start_recording(self):
        self.recording = True
        self.update_style()
        self.setFocus()

    def set_hotkey(self, modifiers: list[str], key: str):
        self.modifiers = list(modifiers)
        self.key = key
        self.recording = False
        self.update_style()
        self.hotkey_captured.emit(self.modifiers, self.key)

    def keyPressEvent(self, event: QKeyEvent):
        if not self.recording:
            super().keyPressEvent(event)
            return

        key = event.key()

        if key == Qt.Key.Key_Escape:
            self.recording = False
            self.update_style()
            event.accept()
            return

        mods = []
        qt_mods = event.modifiers()
        if qt_mods & Qt.KeyboardModifier.ControlModifier:
            mods.append("ctrl")
        if qt_mods & Qt.KeyboardModifier.AltModifier:
            mods.append("alt")
        if qt_mods & Qt.KeyboardModifier.ShiftModifier:
            mods.append("shift")
        if qt_mods & Qt.KeyboardModifier.MetaModifier:
            mods.append("win")

        if key in (Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift, Qt.Key.Key_Meta):
            event.accept()
            return

        key_str = None
        if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
            f_num = key - Qt.Key.Key_F1 + 1
            key_str = f"f{f_num}"
        elif Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            key_str = chr(key).lower()
        elif Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            key_str = chr(key)
        elif key in (Qt.Key.Key_Period, Qt.Key.Key_PeriodCentered):
            key_str = "period"
        elif key == Qt.Key.Key_Comma:
            key_str = "comma"
        elif key in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            key_str = "minus"
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            key_str = "plus"
        elif key == Qt.Key.Key_Space:
            key_str = "space"
        elif key == Qt.Key.Key_Tab:
            key_str = "tab"
        elif key == Qt.Key.Key_QuoteLeft:
            key_str = "grave"
        elif key == Qt.Key.Key_Slash:
            key_str = "slash"
        elif key == Qt.Key.Key_Backslash:
            key_str = "backslash"
        elif key == Qt.Key.Key_Insert:
            key_str = "insert"
        elif key == Qt.Key.Key_Delete:
            key_str = "delete"
        elif key == Qt.Key.Key_Home:
            key_str = "home"
        elif key == Qt.Key.Key_End:
            key_str = "end"
        elif key == Qt.Key.Key_PageUp:
            key_str = "pageup"
        elif key == Qt.Key.Key_PageDown:
            key_str = "pagedown"
        else:
            text = event.text().strip()
            if text:
                key_str = text.lower()

        if key_str:
            if not mods and not key_str.startswith("f"):
                mods = ["ctrl"]

            self.modifiers = mods
            self.key = key_str
            self.recording = False
            self.update_style()
            self.hotkey_captured.emit(self.modifiers, self.key)
            event.accept()
            return

        event.accept()


class HotkeyBindDialog(QDialog):
    """Diálogo modal para configurar el atajo de teclado de Widget OSD."""
    hotkey_saved = Signal(dict)

    def __init__(self, current_hotkey_config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Global Hotkey")
        self.setFixedSize(400, 290)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self.current_modifiers = list(current_hotkey_config.get("modifiers", ["ctrl"]))
        self.current_key = current_hotkey_config.get("key", "period")

        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #0e0e12;
                color: #e2e8f0;
                font-family: 'Segoe UI', Inter, sans-serif;
            }
            QLabel {
                color: #94a3b8;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Cabecera
        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        lbl_title = QLabel("Global Hotkey Configuration")
        lbl_title.setStyleSheet("color: #F8FAFC; font-size: 14px; font-weight: 700;")
        lbl_desc = QLabel("Click the field below and press your desired shortcut to toggle the overlay:")
        lbl_desc.setStyleSheet("color: #64748b; font-size: 11px;")
        lbl_desc.setWordWrap(True)
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_desc)
        layout.addLayout(title_box)

        # Control de grabación
        self.record_btn = KeyRecordButton(self.current_modifiers, self.current_key)
        layout.addWidget(self.record_btn)

        # Presets rápidos
        presets_layout = QVBoxLayout()
        presets_layout.setSpacing(6)
        lbl_presets = QLabel("Quick Presets:")
        lbl_presets.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700; text-transform: uppercase;")
        presets_layout.addWidget(lbl_presets)

        btns_box = QHBoxLayout()
        btns_box.setSpacing(8)

        presets = [
            (["ctrl"], "period", "Ctrl + ."),
            (["ctrl", "shift"], "o", "Ctrl + Shift + O"),
            ([], "f9", "F9"),
            (["alt"], "w", "Alt + W"),
        ]

        for p_mods, p_key, p_label in presets:
            btn_p = QPushButton(p_label)
            btn_p.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn_p.setStyleSheet("""
                QPushButton {
                    background-color: rgba(255, 255, 255, 0.04);
                    color: #94a3b8;
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 5px;
                    padding: 4px 8px;
                    font-size: 10px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 0.08);
                    color: #f1f5f9;
                    border-color: #3b82f6;
                }
            """)
            btn_p.clicked.connect(lambda checked=False, m=p_mods, k=p_key: self.record_btn.set_hotkey(m, k))
            btns_box.addWidget(btn_p)

        presets_layout.addLayout(btns_box)
        layout.addLayout(presets_layout)

        layout.addStretch()

        # Botones de Acción
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(10)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_cancel.setFixedHeight(34)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.04);
                color: #94a3b8;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                font-size: 11px;
                font-weight: 600;
                padding: 0 16px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.08);
                color: #FFFFFF;
            }
        """)
        btn_cancel.clicked.connect(self.reject)
        actions_layout.addWidget(btn_cancel)

        btn_save = QPushButton("Save Hotkey")
        btn_save.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_save.setFixedHeight(34)
        btn_save.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #FFFFFF;
                border: 1px solid #3b82f6;
                border-radius: 6px;
                font-size: 11px;
                font-weight: 700;
                padding: 0 18px;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
        """)
        btn_save.clicked.connect(self._save_and_close)
        actions_layout.addWidget(btn_save)

        layout.addLayout(actions_layout)

    def _save_and_close(self):
        new_config = {
            "modifiers": self.record_btn.modifiers,
            "key": self.record_btn.key
        }
        self.hotkey_saved.emit(new_config)
        self.accept()
