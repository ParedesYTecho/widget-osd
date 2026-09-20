"""Security regressions: setup actions never bootstrap remote code or use a command shell."""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import main_v3
from main_v3 import WidgetApp
import providers.ai_usage_providers as quota_providers
from providers.ai_usage_providers import _MAX_RESPONSE, _read_json_response


def main() -> None:
    source = Path(__file__).with_name("providers") / "ai_usage_providers.py"
    assert "GOCSP" not in source.read_text(encoding="utf-8"), "OAuth client secret embedded in source"

    original_which = main_v3.shutil.which
    original_isfile = main_v3.os.path.isfile
    original_popen = main_v3.subprocess.Popen
    original_open = main_v3.webbrowser.open
    processes: list[list[str]] = []
    urls: list[str] = []
    try:
        main_v3.shutil.which = lambda name: None
        main_v3.os.path.isfile = lambda path: False
        main_v3.subprocess.Popen = lambda command, **kwargs: processes.append(command)
        main_v3.webbrowser.open = lambda url, **kwargs: urls.append(url) or True
        dummy = object()
        for provider in ("codex", "copilot", "grok", "gemini"):
            WidgetApp._setup_provider(dummy, provider)
        assert not processes, "Missing CLI unexpectedly launched a shell/bootstrap process"
        assert len(urls) == 4
        assert all(url.startswith("https://") for url in urls)

        urls.clear()
        main_v3.shutil.which = lambda name: f"C:/safe/{name}.exe"
        main_v3.os.path.isfile = lambda path: True
        WidgetApp._setup_provider(dummy, "codex")
        WidgetApp._setup_provider(dummy, "copilot")
        WidgetApp._setup_provider(dummy, "grok")
        WidgetApp._setup_provider(dummy, "gemini")
        assert len(processes) == 4
        flattened = " ".join(" ".join(command) for command in processes).lower()
        assert "powershell" not in flattened
        assert "irm " not in flattened
        assert "iex" not in flattened
        assert "npm install" not in flattened
        assert all(isinstance(command, list) for command in processes)

        try:
            _read_json_response(io.BytesIO(b"{" + b"x" * _MAX_RESPONSE + b"}"))
            raise AssertionError("Oversized HTTP response was accepted")
        except ValueError as exc:
            assert "supera el límite" in str(exc)

        original_json_file = quota_providers._json_file
        original_post_form = quota_providers._post_form
        posted = []
        try:
            quota_providers._json_file = lambda path: {
                "account": {
                    "refresh_token": "fixture-refresh",
                    "oidc_client_id": "fixture-client",
                    "oidc_issuer": "https://evil.example.test",
                }
            }
            quota_providers._post_form = lambda *args, **kwargs: posted.append(args) or {}
            assert quota_providers.GrokProvider()._refresh_credentials() is False
            assert not posted, "Refresh token was sent to an untrusted OIDC issuer"
        finally:
            quota_providers._json_file = original_json_file
            quota_providers._post_form = original_post_form

        stopped = []
        fake_thread = SimpleNamespace(
            running=True,
            wait=lambda timeout: stopped.append(timeout) or True,
            isRunning=lambda: False,
        )
        fake_app = SimpleNamespace(quit=lambda: stopped.append("quit"))
        controller = WidgetApp.__new__(WidgetApp)
        controller.app = fake_app
        controller.threads = [fake_thread]
        controller.hotkey_thread = None
        controller.is_visible = True
        WidgetApp.quit(controller)
        assert fake_thread.running is False
        assert "quit" in stopped
    finally:
        main_v3.shutil.which = original_which
        main_v3.os.path.isfile = original_isfile
        main_v3.subprocess.Popen = original_popen
        main_v3.webbrowser.open = original_open
    print("security: OK")


if __name__ == "__main__":
    main()
