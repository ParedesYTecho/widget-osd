"""
claude_connect_dialog.py — Diálogo modal seguro para configuración y autenticación de Claude Code.
Blindaje de seguridad: resolución canónica de intérpretes de sistema (Anti-Path Hijacking),
enmascaramiento de tokens y sanitización de excepciones.
"""

import os
import subprocess

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


def _get_secure_comspec() -> str:
    """Devuelve la ruta canónica absoluta al intérprete cmd.exe del sistema."""
    comspec = os.environ.get("COMSPEC")
    if comspec and os.path.isfile(comspec):
        return comspec
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    fallback = os.path.join(system_root, "System32", "cmd.exe")
    if os.path.isfile(fallback):
        return fallback
    return "cmd.exe"


class ClaudeConnectDialog(QDialog):
    credentials_updated = Signal()

    def __init__(self, claude_provider, parent=None):
        super().__init__(parent)
        self.provider = claude_provider
        self.setWindowTitle("Claude Code Authentication")
        self.setFixedWidth(420)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

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
            QLineEdit {
                background-color: rgba(255, 255, 255, 0.04);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                padding: 8px 10px;
                font-size: 11px;
                selection-background-color: #3b82f6;
            }
            QLineEdit:focus {
                border: 1px solid #3b82f6;
                background-color: rgba(255, 255, 255, 0.06);
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # 1. Cabecera
        header = QHBoxLayout()
        title = QLabel("Claude Code Authentication")
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #f8fafc;")
        header.addWidget(title)
        header.addStretch()

        btn_close_header = QPushButton("✕")
        btn_close_header.setFixedSize(22, 22)
        btn_close_header.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_close_header.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                color: #64748b;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                color: #ef4444;
            }
        """)
        btn_close_header.clicked.connect(self.accept)
        header.addWidget(btn_close_header)
        layout.addLayout(header)

        subtitle = QLabel("Authenticate your OAuth session or provide an access token to monitor quotas and active limits:")
        subtitle.setStyleSheet("color: #64748b; font-size: 11px; line-height: 1.3;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # 2. Acciones automáticas
        auto_box = QVBoxLayout()
        auto_box.setSpacing(6)

        lbl_auto = QLabel("AUTOMATED METHODS:")
        lbl_auto.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700;")
        auto_box.addWidget(lbl_auto)

        btn_login = QPushButton("Launch Login (claude auth login)")
        btn_login.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_login.setFixedHeight(34)
        btn_login.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #FFFFFF;
                border: 1px solid #3b82f6;
                border-radius: 6px;
                font-size: 11px;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
        """)
        btn_login.clicked.connect(self._run_claude_login)
        auto_box.addWidget(btn_login)

        layout.addLayout(auto_box)

        # 3. Token Manual
        manual_box = QVBoxLayout()
        manual_box.setSpacing(6)

        lbl_manual = QLabel("OR ENTER TOKEN MANUALLY:")
        lbl_manual.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700;")
        manual_box.addWidget(lbl_manual)

        self.txt_token = QLineEdit()
        self.txt_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_token.setPlaceholderText("Paste CLAUDE_CODE_OAUTH_TOKEN here...")
        curr_token = self.provider._get_token() if hasattr(self.provider, "_get_token") else ""
        if curr_token:
            self.txt_token.setText(curr_token)
        manual_box.addWidget(self.txt_token)

        token_actions = QHBoxLayout()
        token_actions.setSpacing(8)

        btn_save = QPushButton("Save Token")
        btn_save.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_save.setFixedHeight(32)
        btn_save.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.04);
                color: #e2e8f0;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.08);
                color: #ffffff;
            }
        """)
        btn_save.clicked.connect(self._save_token)
        token_actions.addWidget(btn_save)

        btn_test = QPushButton("Test Connection")
        btn_test.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_test.setFixedHeight(32)
        btn_test.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.04);
                color: #e2e8f0;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.08);
                color: #ffffff;
            }
        """)
        btn_test.clicked.connect(self._test_connection)
        token_actions.addWidget(btn_test)

        manual_box.addLayout(token_actions)
        layout.addLayout(manual_box)

        # 4. Estado / Feedback
        self.lbl_feedback = QLabel("")
        self.lbl_feedback.setStyleSheet("font-size: 10px; padding: 4px; border-radius: 4px;")
        self.lbl_feedback.setWordWrap(True)
        self.lbl_feedback.setVisible(False)
        layout.addWidget(self.lbl_feedback)

        layout.addStretch()

        # Botón Cerrar
        btn_done = QPushButton("Close")
        btn_done.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_done.setFixedHeight(34)
        btn_done.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.04);
                color: #94a3b8;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.08);
                color: #FFFFFF;
            }
        """)
        btn_done.clicked.connect(self.accept)
        layout.addWidget(btn_done)

    def _run_claude_login(self):
        try:
            cmd_exe = _get_secure_comspec()
            subprocess.Popen([cmd_exe, "/c", "start", cmd_exe, "/k", "claude auth login"])
            self._set_feedback("Login terminal launched. Complete the browser flow, then click 'Test Connection'.", "#f59e0b")
        except Exception:
            self._set_feedback("Error launching system terminal.", "#ef4444")

    def _save_token(self):
        token = self.txt_token.text().strip()
        if not token:
            self._set_feedback("Please enter a valid token string.", "#f59e0b")
            return

        from core.keyring_manager import KeyringManager
        ok = KeyringManager.set_claude_token(token)
        if ok:
            if hasattr(self.provider, "_manual_token"):
                self.provider._manual_token = token
            self._set_feedback("Token guardado con éxito en Windows Credential Locker (DPAPI).", "#10b981")
            self.credentials_updated.emit()
            self._test_connection()
        else:
            self._set_feedback("Error guardando token en el almacén seguro de Windows.", "#ef4444")

    def _test_connection(self):
        token = self.txt_token.text().strip()
        if hasattr(self.provider, "test_token"):
            ok, msg, data = self.provider.test_token(token or None)
            if ok:
                extra = ""
                if data and "five_hour" in data:
                    five_h = data["five_hour"].get("utilization", data["five_hour"].get("percent", 0.0))
                    seven_d = data.get("seven_day", {}).get("utilization", data.get("seven_day", {}).get("percent", 0.0))
                    extra = f" (Usage: {five_h:.0f}% 5h | {seven_d:.0f}% 7d)"
                self._set_feedback(f"Connection verified successfully with Anthropic{extra}!", "#10b981")
                self.credentials_updated.emit()
            else:
                self._set_feedback(f"Connection failed: {msg}", "#ef4444")
        else:
            self._set_feedback("Checking connection...", "#f59e0b")

    def _set_feedback(self, text: str, color_hex: str):
        self.lbl_feedback.setText(text)
        self.lbl_feedback.setStyleSheet(f"color: {color_hex}; font-size: 10px; font-weight: 600; padding: 4px;")
        self.lbl_feedback.setVisible(True)
