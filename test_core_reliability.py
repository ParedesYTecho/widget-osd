"""Deterministic checks for config, logging, circuit breaker and core models."""

from __future__ import annotations

import json
import logging
import tempfile
import time
from pathlib import Path

from core.autostart import _powershell_exe, _ps_literal
from core.circuit_breaker import CircuitBreaker, CircuitState
from core.config_manager import ConfigManager
from core.logger import SanitizingFormatter, logger as app_logger
from core.models import HardwareTelemetry


def main() -> None:
    logger_was_disabled = app_logger.disabled
    app_logger.disabled = True  # Expected failure cases below must not pollute production diagnostics.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        config = ConfigManager(str(path))
        config.set_content_mode("fps")
        before = path.read_text(encoding="utf-8")
        invalid = dict(config._config)
        invalid["content_mode"] = "invalid-mode"
        assert config.save(invalid) is False
        assert path.read_text(encoding="utf-8") == before, "Invalid config replaced last-known-good file"
        assert config.get("content_mode") == "fps"

        modules = dict(config.ai_modules_config)
        modules["show_codex"] = False
        config.set_ai_modules(modules)
        reloaded = ConfigManager(str(path))
        assert reloaded.ai_modules_config["show_codex"] is False
        json.loads(path.read_text(encoding="utf-8"))

        manual = reloaded._config.copy()
        manual["content_mode"] = "broken"
        manual["ui_scale"] = 1.6
        path.write_text(json.dumps(manual), encoding="utf-8")
        repaired = ConfigManager(str(path))
        assert repaired.get("content_mode") == "all"
        assert repaired.ui_scale == 1.6, "Repair discarded unrelated valid settings"
        assert list(Path(tmp).glob("config.json.corrupt-*")), "Invalid config was not backed up"
        assert json.loads(path.read_text(encoding="utf-8"))["content_mode"] == "all"

        path.write_text("{not-json", encoding="utf-8")
        recovered = ConfigManager(str(path))
        assert recovered.get("content_mode") == "all"
        json.loads(path.read_text(encoding="utf-8"))
        assert len(list(Path(tmp).glob("config.json.corrupt-*"))) >= 2, "Config backups collided"

        legacy = recovered._config.copy()
        legacy.pop("content_mode", None)
        legacy["theme"] = {"accent_color": "#fake-unused-setting"}
        path.write_text(json.dumps(legacy), encoding="utf-8")
        migrated = ConfigManager(str(path))
        persisted = json.loads(path.read_text(encoding="utf-8"))
        assert migrated.get("content_mode") == "all"
        assert persisted["content_mode"] == "all"
        assert "theme" not in persisted, "Obsolete no-op config survived migration"

    formatter = SanitizingFormatter("%(message)s")
    samples = (
        'Authorization: Bearer super-secret-token',
        'api_key="sk-ant-abcdef0123456789"',
        'cookie=private-session-value',
        'refresh_token: refresh-secret-value',
        'github_pat_abcdef0123456789',
    )
    for sample in samples:
        record = logging.LogRecord("test", logging.ERROR, __file__, 1, sample, (), None)
        rendered = formatter.format(record)
        assert "secret-token" not in rendered
        assert "private-session-value" not in rendered
        assert "refresh-secret-value" not in rendered
        assert "abcdef0123456789" not in rendered
        assert "REDACTED" in rendered

    breaker = CircuitBreaker("fixture", failure_threshold=2, cooldown_seconds=0.01)
    for _ in range(2):
        try:
            breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        except RuntimeError:
            pass
    assert breaker.state == CircuitState.OPEN
    time.sleep(0.02)
    assert breaker.state == CircuitState.HALF_OPEN
    assert breaker.call(lambda: 42) == 42
    assert breaker.state == CircuitState.CLOSED

    telemetry = HardwareTelemetry(cpu_percent=120, gpu_percent=-5, fps=-1)
    assert telemetry.cpu_percent == 100
    assert telemetry.gpu_percent == 0
    assert telemetry.fps == 0

    assert _ps_literal("C:/Users/O'Brien/App.exe") == "C:/Users/O''Brien/App.exe"
    powershell = _powershell_exe()
    if powershell:
        assert Path(powershell).is_absolute() and powershell.lower().endswith("powershell.exe")
    app_logger.disabled = logger_was_disabled
    print("core reliability: OK")


if __name__ == "__main__":
    main()
