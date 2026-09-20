"""Verificación end-to-end de WidgetOSD v3. Reinicia instancia empaquetada."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import ctypes
from ctypes import wintypes
from pathlib import Path

import psutil

from providers.ai_usage_providers import ChatGPTWebProvider, CodexProvider, CopilotProvider, GrokProvider, CursorProvider
from providers.antigravity_provider import AntigravityProvider
from providers.base import ProviderStatus
from providers.lhm_provider import LHMProvider

PROJECT_ROOT = Path(__file__).resolve().parent
RELEASE = Path(os.environ.get("WIDGETOSD_RELEASE_DIR", PROJECT_ROOT / "dist" / "WidgetOSD_v3"))
EXE = RELEASE / "WidgetOSD_v3.exe"


def _instances() -> list[psutil.Process]:
    return [p for p in psutil.process_iter(("name",)) if (p.info["name"] or "").lower() == "widgetosd_v3.exe"]


def _wait_count(expected: int, timeout: float = 12.0) -> list[psutil.Process]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = _instances()
        if len(found) == expected:
            return found
        time.sleep(0.2)
    raise AssertionError(f"Instancias esperadas={expected}; encontradas={len(_instances())}")


def _wait_control_ready(timeout: float = 12.0) -> None:
    """Wait until the primary instance has created its native control events."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenEventW.restype = wintypes.HANDLE
    kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        handle = kernel32.OpenEventW(0x0002, False, "Local\\WidgetOSD_v3_Show")
        if handle:
            kernel32.CloseHandle(handle)
            return
        time.sleep(0.05)
    raise AssertionError("Instancia primaria no expuso evento de control a tiempo")


def verify_release() -> None:
    assert EXE.is_file(), f"Release ausente: {EXE}"
    internal = RELEASE / "_internal"
    assert (internal / "hardware" / "HardwareReader.exe").is_file()
    assert not (internal / "icuuc.dll").exists(), "ICU de Poppler contamina Qt"
    assert not (internal / "icudt78.dll").exists(), "ICU de Poppler contamina Qt"

    subprocess.run([str(EXE), "--kill"], timeout=15, check=False)
    _wait_count(0)
    subprocess.Popen([str(EXE), "--minimized"])
    running = _wait_count(1)
    assert running[0].is_running()
    _wait_control_ready()
    subprocess.run([str(EXE)], timeout=15, check=True)
    assert len(_instances()) == 1, "Bloqueo de segunda instancia falló"
    _wait_visible(running[0].pid)
    subprocess.run([str(EXE)], timeout=15, check=True)
    time.sleep(0.3)
    _wait_visible(running[0].pid)
    subprocess.run([str(EXE), "--kill"], timeout=15, check=True)
    _wait_count(0)
    print("release: OK")


def _wait_visible(pid: int, timeout: float = 12.0):
    deadline = time.monotonic() + timeout
    while True:
        try:
            return verify_visible_window(pid)
        except AssertionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.2)


def verify_visible_window(pid: int) -> list[dict]:
    """Inspect actual Windows geometry, not just the existence of a process."""
    user32 = ctypes.windll.user32
    user32.MonitorFromRect.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD]
    user32.MonitorFromRect.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def inspect(hwnd, _data):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)) or rect.right - rect.left < 60 or rect.bottom - rect.top < 20:
            return True
        monitor = user32.MonitorFromRect(ctypes.byref(rect), 2)
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            area = info.rcWork
            found.append({"inside": area.left <= rect.left and area.top <= rect.top and rect.right <= area.right and rect.bottom <= area.bottom,
                          "rect": (rect.left, rect.top, rect.right, rect.bottom),
                          "work_area": (area.left, area.top, area.right, area.bottom)})
        return True

    user32.EnumWindows(inspect, 0)
    assert found and all(item["inside"] for item in found), f"Overlay ausente o fuera del área visible: {found}"
    return found


def verify_hardware() -> None:
    provider = LHMProvider()
    first = provider.fetch()
    time.sleep(2.1)
    second = provider.fetch()
    assert second.get("status") == ProviderStatus.OK
    assert second.get("ram_total_gb", 0) > 0
    assert second.get("top_process")
    changing = ("cpu_percent", "gpu_percent", "ram_percent")
    assert any(first.get(key) != second.get(key) for key in changing), "Telemetría congelada"
    print(f"hardware: OK · {len(second.get('fans', []))} fans medidos · {second.get('fps', 0):.0f} FPS")


def verify_providers() -> None:
    providers = (
        AntigravityProvider(),
        CodexProvider(),
        ChatGPTWebProvider(),
        CopilotProvider(),
        GrokProvider(),
        CursorProvider(),
    )
    failures = []
    print("claude: SKIP · módulo desactivado, cero llamadas")
    print("gemini: SKIP · CLI oculto; cuota independiente de Antigravity")
    for provider in providers:
        result = provider.fetch()
        name = provider.get_name()
        if result.get("status") != ProviderStatus.OK:
            if result.get("status") in (ProviderStatus.STALE, ProviderStatus.RATE_LIMITED, ProviderStatus.AUTH_ERROR):
                status = result.get("status")
                detail = result.get("error") or result.get("hint") or "cuota no disponible"
                print(f"{name}: {getattr(status, 'value', status)} · {detail}")
                continue
            failures.append(f"{name}: {result.get('error') or result.get('hint') or 'sin datos'}")
            continue
        remaining = result.get("remaining_percent")
        print(f"{name}: OK" + (f" · {float(remaining):.1f}%" if remaining is not None else ""))
    assert not failures, "Proveedores fallidos: " + "; ".join(failures)


def verify_ui() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from ui.bento_window import BentoWindow

    app = QApplication.instance() or QApplication([])
    window = BentoWindow()
    window.update_hardware({
        "cpu_percent": 25, "cpu_temp": 55, "cpu_power": 65,
        "gpu_percent": 40, "gpu_temp": 60, "gpu_hotspot": 72,
        "ram_percent": 75, "ram_used_gb": 12, "ram_total_gb": 16,
        "vram_percent": 30, "vram_used_gb": 5, "fps": 144,
        "top_process": "game.exe", "top_process_gb": 4.2,
        "fans": [{"name": "CPU", "rpm": 1200}], "fan_status": "hwinfo",
    })
    assert "144 FPS" in window.lbl_gpu_sub.text()
    assert "game" in window.lbl_ram_sub.text()
    assert set(window.ai_cards) == {"codex", "chatgpt_web", "gemini", "copilot", "grok", "cursor"}
    window.close()
    app.processEvents()
    print("ui: OK")


def verify_offline() -> None:
    from test_ai_providers import main as check_providers
    from test_widget_behavior import main as check_widget
    from test_antigravity_quota import main as check_antigravity
    from test_core_reliability import main as check_core
    from test_security import main as check_security
    check_providers()
    check_widget()
    check_antigravity()
    check_core()
    check_security()
    verify_ui()
    print("offline: OK")


if __name__ == "__main__":
    try:
        if "--offline" in sys.argv:
            verify_offline()
            raise SystemExit(0)
        verify_release()
        verify_hardware()
        verify_providers()
        verify_ui()
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
    launch_env = os.environ.copy()
    launch_env.pop("QT_QPA_PLATFORM", None)
    subprocess.Popen([str(EXE)], env=launch_env)
    print("ALL OK")
