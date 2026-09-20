"""Offline regressions for monitor recovery, scaling, display modes and missing data."""

import os
import tempfile
import time
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QMenu

from core.config_manager import ConfigManager
from main_v3 import WidgetApp, TelemetryThread
from providers.base import ProviderStatus
from providers.lhm_provider import LHMProvider
from ui.bento_window import BentoWindow


def main():
    app = QApplication.instance() or QApplication([])
    for font_file in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "consola.ttf"):
        QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / font_file))
    app.setFont(QFont("Segoe UI", 10))
    window = BentoWindow()
    window.show()
    app.processEvents()
    assert window.bento_pill_fps.text() == "FPS --"
    assert "16.0 GB" not in window.bento_lbl_ram_sub.text()
    assert window.cyber_lbl_gpu_pwr.text() == "-- W"
    assert window.cyber_lbl_f1_v.text() == "--"
    assert window.cyber_lbl_f2_v.text() == "--"
    assert window.cyber_lbl_f3_v.text() == "--"
    assert window.mini_ram_percent.text() == "0%"
    assert not any(window.cyber_spark_cpu_pwr.points), "Missing CPU power seeded a fake graph"
    assert not window._bento_fan_rows
    assert window.mini_fan1_rpm.text() == "-- RPM"

    with tempfile.TemporaryDirectory() as tmp:
        controller = WidgetApp.__new__(WidgetApp)
        controller.window = window
        controller.config = ConfigManager(str(Path(tmp) / "config.json"))
        screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1040))
        secondary = SimpleNamespace(availableGeometry=lambda: QRect(-1280, 0, 1280, 984))
        screens = [screen, secondary]
        controller.app = SimpleNamespace(screens=lambda: screens, primaryScreen=lambda: screen)
        window.move(-1100, 30)
        controller._ensure_on_screen()
        assert window.x() == -1100, "Valid negative monitor coordinates were lost"
        screens.pop()
        controller._ensure_on_screen()
        assert screen.availableGeometry().contains(window.frameGeometry()), "Disconnected monitor strands widget"
        controller.config.set_position(2191, 30, "top-right")
        controller._init_position()
        assert screen.availableGeometry().contains(window.frameGeometry()), "Legacy preset margin strands widget"
        controller.set_preset_position("bottom-right")
        expected = window.pos()
        controller._init_position()
        assert window.pos() == expected, "Preset position drifts after restart"
        assert controller.config.display_config["offset_x"] == 30

        samples = []
        for theme in ("bento_glass", "cyberpunk_hud", "minimalist_compact"):
            window.set_theme(theme, save=False)
            for mode in window.CONTENT_MODES:
                window.set_content_mode(mode)
                small = None
                for scale in (0.6, 0.8, 1.0, 1.2, 1.6, 2.0):
                    window.apply_scale(scale, save=False)
                    app.processEvents()
                    if scale == 0.6:
                        small = window.size()
                    elif scale == 1.0:
                        assert window.width() > small.width() and window.height() > small.height(), (theme, mode, small, window.size())
                    assert not window.fps_only_label.isHidden() == (mode == "fps")
                    assert window._is_provider_visible("codex") == (mode in ("all", "quotas"))
                    assert window.bento_hw_container.isHidden() == (mode in ("fps", "quotas"))
                samples.append((theme, mode, small.width(), small.height()))
            window.set_content_mode("all")
            window.apply_scale(1.0, save=False)
            baseline = window.size()
            window.apply_scale(0.8, save=False)
            window.apply_scale(1.0, save=False)
            app.processEvents()
            assert window.size() == baseline, "Scaling accumulates rounding or stale metrics"

        window.set_content_mode("fps")
        window.fan_aliases = {"CPU": "Radiador CPU"}
        window.update_hardware({"fps": 165, "fans": [{"name": "CPU", "rpm": 1200}]})
        assert window.fps_only_label.text() == "165 FPS"
        assert window.mini_ram_percent.text() == "0%"
        assert window._bento_fan_rows["bento_fan_0"]["lbl_name"].text() == "Radiador CPU"
        window.update_hardware({"fps": 0, "fans": []})
        assert window.fps_only_label.text() == "FPS --"
        assert window.cyber_lbl_gpu_fps.text() == "--"
        assert window.mini_ram_fps.text() == "FPS --"
        assert not window._bento_fan_rows
        window.set_content_mode("quotas")
        modules = dict(window.ai_modules)
        window.set_content_mode("hardware")
        assert window.ai_modules == modules, "Group toggle overwrote individual choices"
        window.set_content_mode("all")
        assert window._is_provider_visible("codex")
        controller.threads = [SimpleNamespace(provider=SimpleNamespace(get_name=lambda n=name: n), enabled=True)
                              for name in ("system", "claude", "codex", "antigravity")]
        window.set_content_mode("fps")
        controller._on_content_mode_changed("fps")
        assert [thread.enabled for thread in controller.threads] == [True, False, False, False]
        reloaded = ConfigManager(controller.config._config_path)
        assert reloaded.get("content_mode") == "fps"
        window.set_content_mode("quotas")
        controller._on_content_mode_changed("quotas")
        assert not controller.threads[0].enabled and controller.threads[2].enabled
        controller.config.set_ui_scale(0.6)
        assert ConfigManager(controller.config._config_path).ui_scale == 0.6
        menu = QMenu()
        modes = window.add_content_menu(menu)
        modes.actions()[2].trigger()
        assert window.content_mode == "fps"
        zoom = window.add_scale_menu(menu)
        zoom.actions()[0].trigger()
        assert window.ui_scale == 0.6
        window.set_content_mode("all")
        window.card_display_modes.pop("antigravity", None)
        window.update_antigravity({
            "status": ProviderStatus.OK,
            "remaining_percent": 20,
            "reset_desc": "1h 0m",
            "is_live": True,
            "models": [
                {"label": "Gemini Pro", "remaining_percent": 20, "reset_desc": "1h 0m"},
                {"label": "Claude Sonnet", "remaining_percent": 80, "reset_desc": "4h 0m"},
            ],
            "windows": {"primary": {"remaining_percent": 20, "reset_desc": "1h 0m"}},
        })
        assert window.bento_val_ag.text() == "20%"
        window._cycle_card_mode("antigravity")
        assert window.bento_val_ag.text() == "80%", "Antigravity click did not select a real alternate model quota"
        assert window.cyber_lbl_ag_val.text().startswith("80%")

        window.card_display_modes["antigravity"] = 0
        window.update_antigravity({
            "status": ProviderStatus.OK,
            "remaining_percent": 20,
            "reset_desc": "1h 0m",
            "is_live": True,
            "windows": {
                "primary": {"remaining_percent": 20, "reset_desc": "1h 0m"},
                "weekly": {"remaining_percent": 65, "reset_desc": "5d 0h"},
            },
        })
        window._cycle_card_mode("antigravity")
        assert window.bento_val_ag.text() == "65%", "Antigravity weekly quota was not selected on click"

        window.card_display_modes["antigravity"] = 0
        window.update_antigravity({
            "status": ProviderStatus.OK,
            "remaining_percent": 20,
            "reset_desc": "1h 0m",
            "is_live": True,
            "windows": {
                "primary": {"remaining_percent": 20, "reset_desc": "1h 0m"},
                "daily": {"remaining_percent": 55, "reset_desc": "18h 0m"},
            },
        })
        window._cycle_card_mode("antigravity")
        assert window.bento_val_ag.text() == "55%"
        assert window.bento_sub_ag.text() == "Cuota diaria"

        window.apply_scale(2.0, save=False)
        controller._ensure_on_screen()
        app.processEvents()
        assert screen.availableGeometry().contains(window.frameGeometry()), "Oversized widget not fitted to work area"

    hardware = LHMProvider()
    hardware._exe_path = __file__
    hardware._circuit_breaker.call = lambda *args, **kwargs: {"cpu": {}, "gpu": {}, "ram": {"total_gb": 16}, "fans": [{"name": "CPU", "rpm": 1200}]}
    hardware._read_afterburner = lambda: {}
    hardware._top_memory_process = lambda: ("fixture", 0.0)
    hardware._read_hwinfo = lambda: {"fps": 0.0}
    assert hardware.fetch()["fps"] == 0.0, "Provider fabricated FPS without a sensor"
    hardware._read_hwinfo = lambda: {"fps": 165.0}
    assert hardware.fetch()["fps"] == 165.0, "Provider lost measured FPS"

    calls = []
    provider = SimpleNamespace(get_name=lambda: "fixture", get_interval=lambda: 60,
                               fetch=lambda: calls.append(True) or {"status": ProviderStatus.OK})
    thread = TelemetryThread(provider)
    thread.enabled = False
    thread.start()
    try:
        time.sleep(0.3)
        assert not calls, "Hidden provider fetched"
        thread.enabled = True
        deadline = time.monotonic() + 2
        while not calls and time.monotonic() < deadline:
            time.sleep(0.02)
        assert len(calls) == 1, "Enabled provider did not resume"
        thread.enabled = False
        time.sleep(0.3)
        assert len(calls) == 1
    finally:
        thread.running = False
        assert thread.wait(2000)
    if "--snapshots" in sys.argv:
        folder = Path(sys.argv[sys.argv.index("--snapshots") + 1])
        folder.mkdir(parents=True, exist_ok=True)
        window.update_hardware({"fps": 165, "cpu_percent": 25, "cpu_temp": 52,
                                "gpu_percent": 70, "gpu_temp": 62, "ram_percent": 55,
                                "ram_used_gb": 9, "ram_total_gb": 16,
                                "fans": [{"name": "CPU Fan", "rpm": 1200, "hardware": "120mm PWM", "max_rpm": 1800}]})
        window.update_antigravity({
            "status": ProviderStatus.OK,
            "remaining_percent": 8,
            "reset_desc": "49h 0m",
            "is_live": True,
            "windows": {
                "five_hour": {"reset_desc": "4h 59m"},
                "weekly": {"remaining_percent": 8, "reset_desc": "49h 0m"},
            },
        })
        window.update_quota_provider("copilot", {
            "status": ProviderStatus.OK,
            "used_percent": 18.5,
            "remaining_percent": 81.5,
            "count_remaining": 163,
            "count_total": 200,
            "count_used": 37,
            "reset_desc": "1 Oct 2026",
        })
        window.update_quota_provider("codex", {
            "status": ProviderStatus.OK,
            "used_percent": 100,
            "remaining_percent": 0,
            "reset_desc": "0h 51m",
            "windows": {
                "weekly": {"remaining_percent": 22, "reset_desc": "3d 18h"},
            },
        })
        window.update_quota_provider("grok", {
            "status": ProviderStatus.OK,
            "used_percent": 94,
            "remaining_percent": 6,
            "reset_desc": "19 Sep 2026",
        })
        window.update_quota_provider("cursor", {
            "status": ProviderStatus.STALE,
            "error": "Cuota inaccesible",
        })
        window.set_content_mode("all")
        for theme in ("bento_glass", "cyberpunk_hud", "minimalist_compact"):
            window.set_theme(theme, save=False)
            window.apply_scale(0.8, save=False)
            app.processEvents()
            assert window.grab().save(str(folder / f"{theme}.png"))
    window.close()
    app.processEvents()
    print("widget regressions: OK (3 themes, 4 modes, 6 scales, monitor recovery, polling, missing telemetry)")
    print("minimum sizes:", samples)


if __name__ == "__main__":
    main()
