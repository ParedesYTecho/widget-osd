"""
main_v3.py — Entrada principal de Widget OSD v3 (Bento Glass Engine).
Blindaje de ciberseguridad, animación ultra-ligera de 90ms,
posicionamiento Drag & Drop con submenú en el Tray y autoinicio en segundo plano.
"""

import sys
import os
import time
import threading
import shutil
import subprocess
import ctypes
import ctypes.wintypes as wintypes
import webbrowser

if getattr(sys, "frozen", False):
    _qt_dll_dir = os.path.join(sys._MEIPASS, "PySide6")
    os.add_dll_directory(_qt_dll_dir)
    os.environ["PATH"] = _qt_dll_dir + os.pathsep + os.environ.get("PATH", "")

_MUTEX_NAME = "Local\\WidgetOSD_v3_SingleInstance"
_EXIT_EVENT_NAME = "Local\\WidgetOSD_v3_Exit"
_TOGGLE_EVENT_NAME = "Local\\WidgetOSD_v3_Toggle"
_SHOW_EVENT_NAME = "Local\\WidgetOSD_v3_Show"
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateMutexW.restype = wintypes.HANDLE
_k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
_k32.CreateEventW.restype = wintypes.HANDLE
_k32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_k32.OpenEventW.restype = wintypes.HANDLE
_k32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_k32.SetEvent.argtypes = [wintypes.HANDLE]
_k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]


def _signal_named_event(name: str) -> bool:
    handle = _k32.OpenEventW(0x0002, False, name)
    if not handle:
        return False
    try:
        return bool(_k32.SetEvent(handle))
    finally:
        _k32.CloseHandle(handle)


if __name__ == "__main__" and len(sys.argv) > 1:
    if sys.argv[1] == "--kill":
        os._exit(0 if _signal_named_event(_EXIT_EVENT_NAME) else 1)
    if sys.argv[1] == "--show":
        # Existing instance: reveal it. No instance: continue into normal startup.
        if _signal_named_event(_SHOW_EVENT_NAME):
            os._exit(0)

_EARLY_MUTEX = 0
_EARLY_EXIT_EVENT = 0
_EARLY_TOGGLE_EVENT = 0
_EARLY_SHOW_EVENT = 0
if __name__ == "__main__":
    _EARLY_MUTEX = _k32.CreateMutexW(None, False, _MUTEX_NAME)
    if ctypes.get_last_error() == 183:
        _signal_named_event(_SHOW_EVENT_NAME)
        _k32.CloseHandle(_EARLY_MUTEX)
        os._exit(0)
    # Expose control events before slow Qt/provider imports finish.
    _EARLY_EXIT_EVENT = _k32.CreateEventW(None, True, False, _EXIT_EVENT_NAME)
    _EARLY_TOGGLE_EVENT = _k32.CreateEventW(None, False, False, _TOGGLE_EVENT_NAME)
    _EARLY_SHOW_EVENT = _k32.CreateEventW(None, False, False, _SHOW_EVENT_NAME)

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QStyle
from PySide6.QtGui import QIcon, QAction, QFont
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPropertyAnimation, QEasingCurve

# Asegurar path base
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
sys.path.insert(0, BASE_DIR)

from ui.bento_window import BentoWindow
from core.config_manager import ConfigManager
from core.logger import get_log_path, install_exception_hooks, logger
from core import autostart
from providers.claude_provider import ClaudeProvider
from providers.antigravity_provider import AntigravityProvider
from providers.lhm_provider import LHMProvider
from providers.ai_usage_providers import (
    CodexProvider, ChatGPTWebProvider, GeminiProvider, CopilotProvider, GrokProvider, CursorProvider,
    OpenRouterProvider, DeepSeekProvider, KimiProvider, PerplexityProvider,
)
from providers.base import ProviderStatus
import pynput

install_exception_hooks(logger)

class TelemetryThread(QThread):
    data_ready = Signal(str, dict)

    def __init__(self, provider, parent=None):
        super().__init__(parent)
        self.provider = provider
        self.running = True
        self.enabled = True

    def run(self):
        p_name = self.provider.get_name()
        stagger_ms = {"system": 0, "antigravity": 250, "claude": 500}.get(p_name, 0)
        if stagger_ms > 0:
            self.msleep(stagger_ms)

        while self.running:
            if not self.enabled:
                self.msleep(200)
                continue
            try:
                data = self.provider.fetch()
                if self.running and self.enabled:
                    self.data_ready.emit(self.provider.get_name(), data)
            except Exception as e:
                logger.warning(f"Error en fetch de {self.provider.get_name()}: {e}")
                if self.running:
                    self.data_ready.emit(self.provider.get_name(), {"status": ProviderStatus.ERROR, "error": str(e)})

            interval = max(1.0, float(self.provider.get_interval()))
            steps = max(1, int(interval / 0.2))
            for _ in range(steps):
                if not self.running or not self.enabled:
                    break
                self.msleep(200)

    def stop(self):
        self.running = False
        self.wait(100)


def get_vk_codes_for_key(key_name: str) -> list[int]:
    k = str(key_name).lower().strip()
    special = {
        "period": [0xBE, 0x6E],
        ".": [0xBE, 0x6E],
        "comma": [0xBC],
        ",": [0xBC],
        "minus": [0xBD, 0x6D],
        "-": [0xBD, 0x6D],
        "plus": [0xBB, 0x6B],
        "+": [0xBB, 0x6B],
        "space": [0x20],
        "tab": [0x09],
        "grave": [0xC0],
        "`": [0xC0],
        "slash": [0xBF, 0x6F],
        "/": [0xBF, 0x6F],
        "backslash": [0xDC],
        "\\": [0xDC],
        "insert": [0x2D],
        "delete": [0x2E],
        "home": [0x24],
        "end": [0x23],
        "pageup": [0x21],
        "pagedown": [0x22],
    }
    if k in special:
        return special[k]

    if k.startswith("f") and k[1:].isdigit():
        f_num = int(k[1:])
        if 1 <= f_num <= 12:
            return [0x70 + (f_num - 1)]

    if len(k) == 1 and k.isalpha():
        return [ord(k.upper())]

    if len(k) == 1 and k.isdigit():
        return [ord(k), 0x60 + int(k)]

    return [0xBE, 0x6E]


def get_mod_flags(modifiers: list[str]) -> int:
    flags = 0
    for m in modifiers:
        ml = str(m).lower().strip()
        if ml in ("ctrl", "control"):
            flags |= 0x0002
        elif ml == "alt":
            flags |= 0x0001
        elif ml == "shift":
            flags |= 0x0004
        elif ml in ("win", "meta"):
            flags |= 0x0008
    return flags


class GlobalHotkeyThread(QThread):
    activated = Signal()

    def __init__(self, hotkey_config: dict | None = None, parent=None):
        super().__init__(parent)
        self.running = True
        self.hotkey_config = hotkey_config or {"modifiers": ["ctrl"], "key": "period"}
        self._native_thread_id = 0

    def run(self):
        registered_ids = []
        user32 = None
        try:
            import ctypes
            import ctypes.wintypes
            user32 = ctypes.windll.user32
            self._native_thread_id = ctypes.windll.kernel32.GetCurrentThreadId()

            MOD_NOREPEAT = 0x4000
            mods = get_mod_flags(self.hotkey_config.get("modifiers", ["ctrl"]))
            vks = get_vk_codes_for_key(self.hotkey_config.get("key", "period"))

            for idx, vk in enumerate(vks):
                hid = 9000 + idx + 1
                res = user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk)
                if not res:
                    res = user32.RegisterHotKey(None, hid, mods, vk)
                if res:
                    registered_ids.append(hid)

            msg = ctypes.wintypes.MSG()
            while self.running and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == 0x0312:
                    self.activated.emit()
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

        except Exception as exc:
            logger.warning(f"Excepción en bucle de atajos globales: {exc}")
        finally:
            self._native_thread_id = 0
            if user32:
                for hid in registered_ids:
                    try:
                        user32.UnregisterHotKey(None, hid)
                    except Exception:
                        pass

    def stop(self):
        self.running = False
        try:
            if self._native_thread_id:
                ctypes.windll.user32.PostThreadMessageW(self._native_thread_id, 0x0012, 0, 0)
        except Exception:
            pass
        return self.wait(1000)


class WidgetApp:
    def __init__(self, app: QApplication, mutex_handle: int, start_minimized: bool = False):
        self.app = app
        self.mutex_handle = mutex_handle
        self.app.setQuitOnLastWindowClosed(False)

        font = QFont("Segoe UI", 10)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        self.app.setFont(font)

        config_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(config_dir, "config.json")
        self.config = ConfigManager(config_path)

        # Iniciar Proveedores de Datos
        self.lhm = LHMProvider()
        self.claude = ClaudeProvider(self.config.claude_config)
        self.antigravity = AntigravityProvider(self.config.antigravity_config)
        provider_types = (
            CodexProvider, ChatGPTWebProvider, GeminiProvider, CopilotProvider, GrokProvider, CursorProvider,
            OpenRouterProvider, DeepSeekProvider, KimiProvider, PerplexityProvider,
        )
        self.ai_providers = [
            provider_type(self.config.provider_config(provider_type.name))
            for provider_type in provider_types
            if self.config.ai_modules_config.get(
                f"show_{provider_type.name}",
                True if provider_type.name in ("codex", "chatgpt_web", "copilot", "grok", "cursor") else False,
            )
        ]

        # Crear ventana principal
        self.window = BentoWindow(
            fan_aliases=self.config.fan_aliases,
            claude_provider=self.claude,
            ui_scale=self.config.ui_scale,
            ai_modules=self.config.ai_modules_config,
            hotkey_config=self.config.hotkey_config,
            theme_style=self.config.theme_style,
            content_mode=self.config.get("content_mode", default="all"),
        )
        self.is_visible = not start_minimized

        self._init_position()

        # Animación ultra-ligera de opacidad (90ms, tipo MSI Afterburner)
        self.anim = QPropertyAnimation(self.window, b"windowOpacity")
        self.anim.setDuration(90)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.finished.connect(self._on_animation_finished)

        # Conectar señales de la UI
        self.window.close_requested.connect(self.quit)
        self.window.hide_requested.connect(self.hide_window)
        self.window.reload_requested.connect(self.reload_data)
        self.window.scale_changed.connect(self.config.set_ui_scale)
        self.window.hotkey_changed.connect(self._on_hotkey_changed)
        self.window.position_changed.connect(self._on_window_dragged)
        self.window.provider_setup_requested.connect(self._setup_provider)
        self.window.ai_modules_changed.connect(self._on_ai_modules_changed)
        self.window.theme_changed.connect(self._on_theme_changed)
        self.window.content_mode_changed.connect(self._on_content_mode_changed)
        self.window.size_changed.connect(lambda: QTimer.singleShot(0, self._ensure_on_screen))
        self.app.screenRemoved.connect(lambda _screen: QTimer.singleShot(0, self._ensure_on_screen))
        self.app.screenAdded.connect(self._watch_screen)
        for screen in self.app.screens():
            self._watch_screen(screen)

        self._setup_tray()

        self.threads = []
        self.start_provider(self.lhm)
        if self.config.ai_modules_config.get("show_claude", True):
            self.start_provider(self.claude)
        if self.config.ai_modules_config.get("show_antigravity", True):
            self.start_provider(self.antigravity)
        for provider in self.ai_providers:
            self.start_provider(provider)
        self._sync_provider_visibility()

        self._setup_hotkey()

        self._setup_native_events()
        self._active_refreshes = set()
        self._refresh_lock = threading.Lock()

        if not start_minimized:
            self.show_window()
        else:
            self.window.setWindowOpacity(0.0)
            self.window.hide()

        logger.info("Widget OSD v3 iniciado con éxito.")

    def _init_position(self):
        screens = self.app.screens()
        index = self.config.display_config.get("monitor", 1) - 1
        target = screens[index] if 0 <= index < len(screens) else self.app.primaryScreen()
        screen = target.availableGeometry()
        corner = self.config.display_config.get("corner", "top-right")
        offset_x = self.config.display_config.get("offset_x", 30)
        offset_y = self.config.display_config.get("offset_y", 30)
        w = self.window.width()
        h = self.window.height()

        # Older builds persisted absolute coordinates as preset margins.
        if corner != "custom":
            offset_x = offset_x if 0 <= offset_x < screen.width() // 2 else 30
            offset_y = offset_y if 0 <= offset_y < screen.height() // 2 else 30

        if corner == "custom":
            self.window.move(offset_x, offset_y)
        elif corner == "top-right":
            self.window.move(screen.right() - w - offset_x, screen.top() + offset_y)
        elif corner == "top-left":
            self.window.move(screen.left() + offset_x, screen.top() + offset_y)
        elif corner == "bottom-right":
            self.window.move(screen.right() - w - offset_x, screen.bottom() - h - offset_y)
        elif corner == "bottom-left":
            self.window.move(screen.left() + offset_x, screen.bottom() - h - offset_y)
        else:
            self.window.move(screen.right() - w - 30, screen.top() + 30)
        self._ensure_on_screen()

    def _watch_screen(self, screen):
        screen.availableGeometryChanged.connect(lambda _rect: self._ensure_on_screen())
        screen.geometryChanged.connect(lambda _rect: self._ensure_on_screen())
        self._ensure_on_screen()

    def _ensure_on_screen(self):
        """Keep the complete overlay inside an active monitor's work area."""
        areas = [screen.availableGeometry() for screen in self.app.screens()]
        if not areas:
            return
        frame = self.window.frameGeometry()
        area = max(areas, key=lambda rect: rect.intersected(frame).width() * rect.intersected(frame).height())
        if not area.intersects(frame):
            area = self.app.primaryScreen().availableGeometry()
        for _ in range(4):
            fit = min(1.0, area.width() / max(1, frame.width()), area.height() / max(1, frame.height()))
            if fit >= 1.0 or self.window.ui_scale <= 0.6:
                break
            next_scale = max(0.6, round(self.window.ui_scale * fit - 0.01, 2))
            if next_scale >= self.window.ui_scale:
                next_scale = max(0.6, round(self.window.ui_scale - 0.01, 2))
            self.window.apply_scale(next_scale, save=False)
            frame = self.window.frameGeometry()
        x = max(area.left(), min(frame.x(), area.right() - frame.width() + 1))
        y = max(area.top(), min(frame.y(), area.bottom() - frame.height() + 1))
        if (x, y) != (frame.x(), frame.y()):
            self.window.move(x, y)
            self.config.set_position(x, y, "custom")

    def set_preset_position(self, corner: str):
        """Fija la posición de la ventana en una esquina predeterminada."""
        screen = self.app.primaryScreen().availableGeometry()
        w = self.window.width()
        h = self.window.height()
        offset = 30

        if corner == "top-right":
            nx, ny = screen.right() - w - offset, screen.top() + offset
        elif corner == "top-left":
            nx, ny = screen.left() + offset, screen.top() + offset
        elif corner == "bottom-right":
            nx, ny = screen.right() - w - offset, screen.bottom() - h - offset
        elif corner == "bottom-left":
            nx, ny = screen.left() + offset, screen.bottom() - h - offset
        else:
            nx, ny = screen.right() - w - offset, screen.top() + offset
            corner = "top-right"

        self.window.move(nx, ny)
        self.config.set_position(offset, offset, corner)
        self._ensure_on_screen()
        logger.info(f"Posición del widget fijada a preset: {corner} ({nx}, {ny})")

    def _on_window_dragged(self, x: int, y: int):
        self.config.set_position(x, y, "custom")
        self._ensure_on_screen()

    def start_provider(self, provider):
        thread = TelemetryThread(provider)
        thread.enabled = (
            self.window.content_mode != "quotas" if provider.get_name() == "system"
            else self.window._is_provider_visible(provider.get_name())
        )
        thread.data_ready.connect(self.update_ui)
        self.threads.append(thread)
        thread.start()

    def update_ui(self, provider_name: str, data: dict):
        if provider_name == "system":
            self.window.update_hardware(data)
        elif provider_name == "claude":
            self.window.update_claude(data)
        elif provider_name == "antigravity":
            self.window.update_antigravity(data)
        elif provider_name in self.window.ai_cards:
            self.window.update_quota_provider(provider_name, data)
        self.window._scale_contents()
        self.window.adjustSize()

    def reload_data(self):
        def _safe_fetch(provider, name):
            with self._refresh_lock:
                if name in self._active_refreshes:
                    return
                self._active_refreshes.add(name)
            try:
                data = provider.fetch()
                QTimer.singleShot(0, self.window, lambda d=data, n=name: self.update_ui(n, d))
            except Exception as err:
                QTimer.singleShot(
                    0, self.window,
                    lambda e=str(err), n=name: self.update_ui(n, {"status": ProviderStatus.ERROR, "error": e}),
                )
            finally:
                with self._refresh_lock:
                    self._active_refreshes.discard(name)

        for thread in self.threads:
            if not thread.enabled:
                continue
            provider = thread.provider
            threading.Thread(
                target=_safe_fetch, args=(provider, provider.get_name()), daemon=True
            ).start()

    def _setup_provider(self, name: str):
        grok_exe = shutil.which("grok") or os.path.join(os.path.expanduser("~"), ".grok", "bin", "grok.exe")
        process_actions = {
            "codex": ([shutil.which("codex") or "codex", "login"] if shutil.which("codex") else None),
            "copilot": ([shutil.which("gh") or "gh", "auth", "login"] if shutil.which("gh") else None),
            "grok": ([grok_exe, "login"] if os.path.isfile(grok_exe) else None),
            "gemini": ([shutil.which("gemini") or "gemini"] if shutil.which("gemini") else None),
        }
        urls = {
            "codex": "https://developers.openai.com/codex/",
            "chatgpt_web": "https://chatgpt.com/codex/settings/usage",
            "copilot": "https://github.com/cli/cli",
            "grok": "https://x.ai/",
            "gemini": "https://github.com/google-gemini/gemini-cli",
            "cursor": "https://cursor.com/settings",
            "openrouter": "https://openrouter.ai/keys",
            "deepseek": "https://platform.deepseek.com/api_keys",
            "kimi": "https://platform.moonshot.cn/console/api-keys",
            "perplexity": "https://www.perplexity.ai/settings/api",
        }
        if name not in urls:
            return
        try:
            command = process_actions.get(name)
            if command:
                subprocess.Popen(command, creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
            else:
                webbrowser.open(urls[name], new=2)
        except OSError as exc:
            logger.warning(f"No se pudo abrir configuración de {name}: {exc}")

    def _on_ai_modules_changed(self, modules: dict):
        self.config.set_ai_modules(modules)
        active_names = {t.provider.get_name() for t in self.threads if getattr(t, "provider", None)}
        all_p_types = {
            "claude": ClaudeProvider, "antigravity": AntigravityProvider,
            "codex": CodexProvider, "gemini": GeminiProvider, "copilot": CopilotProvider,
            "chatgpt_web": ChatGPTWebProvider,
            "grok": GrokProvider, "cursor": CursorProvider, "openrouter": OpenRouterProvider,
            "deepseek": DeepSeekProvider, "kimi": KimiProvider, "perplexity": PerplexityProvider,
        }
        for name, p_cls in all_p_types.items():
            if modules.get(f"show_{name}", False) and name not in active_names:
                if name in ("claude", "antigravity"):
                    p_inst = getattr(self, name)
                else:
                    p_inst = p_cls(self.config.provider_config(name))
                    self.ai_providers.append(p_inst)
                self.start_provider(p_inst)
        self._sync_provider_visibility()

    def _on_content_mode_changed(self, mode: str):
        self.config.set_content_mode(mode)
        self._sync_provider_visibility()

    def _sync_provider_visibility(self):
        for thread in self.threads:
            name = thread.provider.get_name()
            thread.enabled = (
                self.window.content_mode != "quotas" if name == "system"
                else self.window._is_provider_visible(name)
            )

    def _on_theme_changed(self, theme_style: str):
        self.config.set_theme_style(theme_style)

    def _set_theme_preset(self, theme_style: str):
        self.config.set_theme_style(theme_style)
        self.window.set_theme(theme_style)

    def _setup_tray(self):
        self.tray = QSystemTrayIcon()

        icon_path = os.path.join(BASE_DIR, "app_icon.ico")
        if os.path.exists(icon_path):
            self.tray.setIcon(QIcon(icon_path))
        else:
            self.tray.setIcon(self.app.style().standardIcon(QStyle.SP_ComputerIcon))

        self.tray.setToolTip("Widget OSD v3")

        menu = QMenu()
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

        toggle_act = QAction("Toggle Overlay", menu)
        toggle_act.triggered.connect(self.toggle_visibility)
        menu.addAction(toggle_act)
        self.window.add_content_menu(menu)
        self.window.add_scale_menu(menu)
        recover_act = menu.addAction("Recuperar en pantalla principal")
        recover_act.triggered.connect(lambda: (self.set_preset_position("top-right"), self.show_window()))

        # Submenú de Estilo Visual / Themes
        theme_menu = menu.addMenu("Design / Theme")
        theme_menu.setStyleSheet(menu.styleSheet())
        for t_id, t_lbl in [
            ("bento_glass", "Bento Glassmorphism (Default)"),
            ("cyberpunk_hud", "Cyberpunk HUD"),
            ("minimalist_compact", "Minimalist Compact"),
        ]:
            act = QAction(t_lbl, self.tray)
            act.triggered.connect(lambda chk=False, target=t_id: self._set_theme_preset(target))
            theme_menu.addAction(act)

        # Submenú de Posicionamiento Rápido
        pos_menu = menu.addMenu("Position")
        pos_menu.setStyleSheet(menu.styleSheet())

        for p_id, p_lbl in [
            ("top-right", "Top-Right (Default)"),
            ("top-left", "Top-Left"),
            ("bottom-right", "Bottom-Right"),
            ("bottom-left", "Bottom-Left"),
        ]:
            act = QAction(p_lbl, self.tray)
            act.triggered.connect(lambda chk=False, corner=p_id: self.set_preset_position(corner))
            pos_menu.addAction(act)

        # Autostart con Windows (Checkbox)
        autostart_act = QAction("Start with Windows", menu)
        autostart_act.setCheckable(True)
        autostart_act.setChecked(autostart.is_autostart_enabled())
        autostart_act.toggled.connect(self._on_autostart_toggled)
        menu.addAction(autostart_act)

        reload_act = QAction("Refresh Telemetry", menu)
        reload_act.triggered.connect(self.reload_data)
        menu.addAction(reload_act)

        logs_act = QAction("Open Diagnostic Logs", menu)
        logs_act.triggered.connect(self._open_logs)
        menu.addAction(logs_act)

        config_act = QAction("Open Advanced Configuration", menu)
        config_act.triggered.connect(self._open_config)
        menu.addAction(config_act)

        menu.addSeparator()

        exit_act = QAction("Exit Widget OSD", menu)
        exit_act.triggered.connect(self.quit)
        menu.addAction(exit_act)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.setVisible(True)

    def _on_autostart_toggled(self, checked: bool):
        autostart.set_autostart(checked)
        self.config.set_autostart(checked)

    def _open_logs(self):
        folder = os.path.dirname(get_log_path())
        try:
            os.makedirs(folder, exist_ok=True)
            os.startfile(folder)
        except OSError as exc:
            logger.warning(f"No se pudo abrir carpeta de logs: {exc}")

    def _open_config(self):
        try:
            if not os.path.isfile(self.config.path):
                self.config.save(self.config._config)
            os.startfile(self.config.path)
        except OSError as exc:
            logger.warning(f"No se pudo abrir configuración: {exc}")

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_visibility()

    def _setup_hotkey(self):
        if hasattr(self, 'hotkey_thread') and self.hotkey_thread:
            try:
                self.hotkey_thread.stop()
                if self.hotkey_thread in self.threads:
                    self.threads.remove(self.hotkey_thread)
            except Exception:
                pass

        try:
            self.hotkey_thread = GlobalHotkeyThread(self.config.hotkey_config)
            self.hotkey_thread.activated.connect(self.toggle_visibility)
            self.hotkey_thread.start()
            self.threads.append(self.hotkey_thread)
        except Exception as e:
            logger.error(f"Error al iniciar GlobalHotkeyThread: {e}")

    def _on_hotkey_changed(self, new_config: dict):
        self.config.set_hotkey(new_config.get("modifiers", ["ctrl"]), new_config.get("key", "period"))
        self._setup_hotkey()
        from ui.hotkey_dialog import format_hotkey_display
        txt = format_hotkey_display(new_config.get("modifiers", ["ctrl"]), new_config.get("key", "period"))
        self.tray.setToolTip(f"Widget OSD v3 ({txt})")

    def _setup_native_events(self):
        self.exit_event = _EARLY_EXIT_EVENT or _k32.CreateEventW(None, True, False, _EXIT_EVENT_NAME)
        self.toggle_event = _EARLY_TOGGLE_EVENT or _k32.CreateEventW(None, False, False, _TOGGLE_EVENT_NAME)
        self.show_event = _EARLY_SHOW_EVENT or _k32.CreateEventW(None, False, False, _SHOW_EVENT_NAME)
        self.event_timer = QTimer(self.window)
        self.event_timer.timeout.connect(self._poll_native_events)
        self.event_timer.start(150)

    def _poll_native_events(self):
        if _k32.WaitForSingleObject(self.exit_event, 0) == 0:
            self.quit()
            return
        if _k32.WaitForSingleObject(self.toggle_event, 0) == 0:
            self.toggle_visibility()
        if _k32.WaitForSingleObject(self.show_event, 0) == 0:
            self.show_window()

    def _on_animation_finished(self):
        if not self.is_visible:
            self.window.hide()

    def hide_window(self):
        self.anim.stop()

        self.anim.setStartValue(self.window.windowOpacity())
        self.anim.setEndValue(0.0)
        self.anim.start()
        self.is_visible = False

    def show_window(self):
        self.anim.stop()

        self._ensure_on_screen()
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

        self.anim.setStartValue(self.window.windowOpacity())
        self.anim.setEndValue(1.0)
        self.anim.start()
        self.is_visible = True

    def toggle_visibility(self):
        if self.is_visible:
            self.hide_window()
        else:
            self.show_window()

    def quit(self):
        # 1. Ocultar inmediatamente ventana y tray para feedback visual instantáneo (0ms)
        if hasattr(self, 'window') and self.window:
            self.window.hide()
        if hasattr(self, 'tray') and self.tray:
            self.tray.hide()
        self.is_visible = False

        # 2. Pedir parada a todos los hilos antes de destruir Qt/handles.
        threads = list(getattr(self, 'threads', []))
        for thread in threads:
            if hasattr(thread, 'running'):
                thread.running = False
        if getattr(self, "hotkey_thread", None) in threads:
            try:
                self.hotkey_thread.stop()
            except Exception as exc:
                logger.warning(f"No se pudo detener hotkey thread limpiamente: {exc}")

        deadline = time.monotonic() + 2.0
        for thread in threads:
            if thread is getattr(self, "hotkey_thread", None):
                continue
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            if remaining_ms <= 0:
                break
            thread.wait(remaining_ms)

        # 3. Liberar handles nativos.
        for handle_name in ("exit_event", "toggle_event", "show_event", "mutex_handle"):
            handle = getattr(self, handle_name, 0)
            if handle:
                _k32.CloseHandle(handle)
                setattr(self, handle_name, 0)

        # 4. Salida limpia cuando todos terminaron; fallback duro solo si una API quedó bloqueada.
        stuck = [thread for thread in threads if thread.isRunning()]
        if stuck:
            logger.warning(f"Salida forzada: {len(stuck)} hilo(s) no respondieron en 2s")
        else:
            logger.info("Widget OSD detenido limpiamente.")
        for handler in logger.handlers:
            try:
                handler.flush()
            except Exception:
                pass
        self.app.quit()
        if stuck:
            os._exit(0)


if __name__ == "__main__":
    app_qt = QApplication(sys.argv)

    start_minimized = ("--tray" in sys.argv or "--minimized" in sys.argv)

    app_instance = WidgetApp(app_qt, _EARLY_MUTEX, start_minimized=start_minimized)
    sys.exit(app_qt.exec())
