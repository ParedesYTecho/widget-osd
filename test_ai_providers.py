"""Comprobación mínima del contrato común de cuotas, sin usar credenciales reales."""

import io
import json
import os
import tempfile
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import providers.ai_usage_providers as providers
import providers.claude_provider as claude_provider
from providers.antigravity_provider import AntigravityProvider
from providers.base import ProviderStatus


def main() -> None:
    original = providers._request_json
    original_json_file = providers._json_file
    try:
        providers._request_json = lambda *args, **kwargs: {
            "copilotPlan": "pro",
            "quotaResetDate": "2026-10-01",
            "quotaSnapshots": {
                "premiumInteractions": {"percentRemaining": 73},
                "chat": {"percentRemaining": 90},
            },
        }
        provider = providers.CopilotProvider({"token": "fixture-token"})
        result = provider.fetch()
        assert result["used_percent"] == 27
        assert result["remaining_percent"] == 73
        assert result["secondary_used_percent"] == 10

        providers._request_json = lambda *args, **kwargs: {
            "quotaResetDate": "2026-10-01T00:00:00Z",
            "quotaSnapshots": {
                "premiumInteractions": {
                    "percentRemaining": 81.5,
                    "remaining": 163,
                    "entitlement": 200,
                },
            },
        }
        counted_copilot = providers.CopilotProvider({"token": "fixture-token"}).fetch()
        assert counted_copilot["count_remaining"] == 163
        assert counted_copilot["count_total"] == 200
        assert counted_copilot["count_used"] == 37.0

        providers._request_json = lambda *args, **kwargs: {
            "quotaSnapshots": {"chat": {"percentRemaining": 81}}
        }
        chat_only = providers.CopilotProvider({"token": "fixture-token"}).fetch()
        assert chat_only["primary_label"] == "Chat"
        assert chat_only["used_percent"] == 19
        assert chat_only["secondary_used_percent"] is None

        ag = AntigravityProvider()
        exhausted = ag._parse_language_server_data({
            "userStatus": {
                "cascadeModelConfigData": {
                    "clientModelConfigs": [{
                        "label": "Gemini Pro",
                        "modelId": "gemini-pro",
                        "quotaInfo": {"remainingFraction": 0},
                    }]
                }
            }
        })
        assert exhausted["plan_name"] == "Antigravity"
        assert exhausted["remaining_percent"] == 0.0
        assert exhausted["is_exhausted"] is True

        unavailable = ag._parse_language_server_data({
            "userStatus": {
                "cascadeModelConfigData": {
                    "clientModelConfigs": [{"label": "Gemini Pro", "modelId": "gemini-pro"}]
                }
            }
        })
        assert unavailable["status"] == ProviderStatus.STALE
        assert unavailable["remaining_percent"] is None

        with tempfile.TemporaryDirectory() as tmp:
            cached_ag = AntigravityProvider({"cache_path": os.path.join(tmp, "antigravity.json")})
            cached_ag._save_quota_cache({
                "status": ProviderStatus.OK,
                "usage_percent": 0.0,
                "remaining_percent": 100.0,
                "reset_time": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
                "is_live": True,
            })
            cached = cached_ag._load_quota_cache()
            assert cached["status"] == ProviderStatus.STALE
            assert cached["quota_source"] == "disk_cache"
            assert cached["remaining_percent"] == 100.0

            expired_ag = AntigravityProvider({"cache_path": os.path.join(tmp, "expired.json")})
            expired_ag._save_quota_cache({
                "status": ProviderStatus.OK,
                "usage_percent": 0.0,
                "remaining_percent": 100.0,
                "reset_time": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                "is_live": True,
            })
            assert expired_ag._load_quota_cache() is None

        original_ag_fetch = AntigravityProvider.fetch
        try:
            AntigravityProvider.fetch = lambda self: {
                "status": ProviderStatus.OK,
                "usage_percent": 40.0,
                "remaining_percent": 60.0,
                "reset_desc": "6d 23h",
                "reset_time": "2026-09-21T12:00:00Z",
                "models": [],
                "windows": {
                    "primary": {
                        "remaining_percent": 60.0,
                        "usage_percent": 40.0,
                        "reset_desc": "6d 23h",
                        "reset_time": "2026-09-21T12:00:00Z",
                    }
                },
            }
            gemini_live = providers.GeminiProvider().fetch()
            assert gemini_live["windows"]["weekly"]["remaining_percent"] == 60.0
            assert gemini_live["windows"]["weekly"]["reset_desc"] == "6d 23h"

            AntigravityProvider.fetch = lambda self: {
                "status": ProviderStatus.OK,
                "usage_percent": None,
                "remaining_percent": None,
            }
            providers._json_file = lambda *args, **kwargs: {}
            gemini_unavailable = providers.GeminiProvider().fetch()
            assert gemini_unavailable["status"] == ProviderStatus.AUTH_ERROR
            assert gemini_unavailable.get("remaining_percent") is None
        finally:
            AntigravityProvider.fetch = original_ag_fetch

        providers._request_json = lambda *args, **kwargs: {
            "config": {"creditUsagePercent": 12, "subscriptionTier": "oidc"}
        }
        providers._json_file = lambda *args, **kwargs: {
            "account": {"key": "fixture-token", "email": "fixture@example.test"}
        }
        grok = providers.GrokProvider()
        grok_result = grok.fetch()
        assert grok_result["plan"] == "Grok"
        assert grok_result["used_percent"] == 12.0
        assert grok_result["remaining_percent"] == 88.0
        assert grok_result["is_unlimited"] is False

        providers._request_json = lambda *args, **kwargs: {"config": {"subscriptionTier": "pro"}}
        grok_unknown = providers.GrokProvider().fetch()
        assert grok_unknown["status"] == ProviderStatus.STALE
        assert "remaining_percent" not in grok_unknown

        providers._request_json = lambda *args, **kwargs: {
            "config": {"subscriptionTier": "Unlimited", "isUnlimited": True}
        }
        grok_unlimited = providers.GrokProvider().fetch()
        assert grok_unlimited["status"] == ProviderStatus.OK
        assert grok_unlimited["is_unlimited"] is True

        missing_env = {
            name: ""
            for name in (
                "OPENROUTER_API_KEY", "OPENROUTER_KEY",
                "DEEPSEEK_API_KEY", "DEEPSEEK_KEY",
                "MOONSHOT_API_KEY", "KIMI_API_KEY", "MOONSHOT_KEY",
                "PERPLEXITY_API_KEY", "PPLX_API_KEY", "PERPLEXITY_TOKEN",
                "PERPLEXITY_SESSION_TOKEN", "PPLX_SESSION_TOKEN",
            )
        }
        with patch.dict(os.environ, missing_env):
            for missing_provider in (
                providers.OpenRouterProvider(),
                providers.DeepSeekProvider(),
                providers.KimiProvider(),
                providers.PerplexityProvider(),
            ):
                missing = missing_provider.fetch()
                assert missing["status"] == ProviderStatus.AUTH_ERROR
                assert "remaining_percent" not in missing

        def unauthorized(*args, **kwargs):
            raise urllib.error.HTTPError("https://example.test", 401, "expired", {}, io.BytesIO())

        providers._request_json = unauthorized
        invalid_perplexity = providers.PerplexityProvider({"api_key": "fixture-key"}).fetch()
        assert invalid_perplexity["status"] == ProviderStatus.AUTH_ERROR

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".claude.json").write_text(
                json.dumps({"oauthAccount": {"organizationType": "claude_pro"}}), encoding="utf-8"
            )
            with patch.object(claude_provider.Path, "home", return_value=home):
                assert claude_provider._get_claude_local_cache() is None

        calls = 0
        refreshed = False

        class RefreshingProvider(providers._QuotaProvider):
            def _fetch(self):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise urllib.error.HTTPError("https://example.test", 401, "expired", {}, io.BytesIO())
                return providers._result("fixture", 20, "Quota")

            def _refresh_credentials(self):
                nonlocal refreshed
                refreshed = True
                return True

        # OpenRouter test
        providers._request_json = lambda *args, **kwargs: {
            "data": {"total_credits": 50.0, "total_usage": 10.5}
        }
        or_p = providers.OpenRouterProvider({"api_key": "fixture-key"})
        or_res = or_p.fetch()
        assert or_res["balance"] == 39.5
        assert or_res["primary_label"] == "$39.50"
        assert or_res["used_percent"] == 21.0

        # DeepSeek test
        providers._request_json = lambda *args, **kwargs: {
            "balance_infos": [{"currency": "CNY", "total_balance": "88.50", "topped_up_balance": "50.00", "granted_balance": "38.50"}]
        }
        ds_p = providers.DeepSeekProvider({"api_key": "fixture-key"})
        ds_res = ds_p.fetch()
        assert ds_res["balance"] == 88.50
        assert ds_res["primary_label"] == "¥88.50"
        assert "Grant: ¥38.50" in ds_res["secondary_label"]
        assert "Cash: ¥50.00" in ds_res["windows"]["secondary"]["value"]

        # Kimi test
        providers._request_json = lambda *args, **kwargs: {
            "data": {"available_balance": 42.0, "cash_balance": 30.0, "voucher_balance": 12.0}
        }
        kimi_p = providers.KimiProvider({"api_key": "fixture-key"})
        kimi_res = kimi_p.fetch()
        assert kimi_res["balance"] == 42.0
        assert kimi_res["primary_label"] == "¥42.00"
        assert "Voucher: ¥12.00" in kimi_res["secondary_label"]
        assert "Cash: ¥30.00" in kimi_res["windows"]["secondary"]["value"]

        # Perplexity test
        providers._request_json = lambda *args, **kwargs: {
            "user": {"subscription_tier": "pro", "subscription_status": "active"}
        }
        perp_p = providers.PerplexityProvider({"session_token": "fixture-session"})
        perp_res = perp_p.fetch()
        assert perp_res["primary_label"] == "Pro"
        assert perp_res["is_unlimited"] is True

        providers._request_json = lambda *args, **kwargs: {
            "data": [{"id": "sonar-pro"}]
        }
        perp_api = providers.PerplexityProvider({"api_key": "pplx-fixture"})
        perp_api_res = perp_api.fetch()
        assert perp_api_res["primary_label"] == "API Active"

        # Cursor test
        providers._request_json = lambda *args, **kwargs: {
            "individualUsage": {"plan": {"totalPercentUsed": 40.0, "limit": 500, "used": 200}},
            "membershipType": "pro",
        }
        cursor_p = providers.CursorProvider({"token": "fixture-token"})
        cursor_res = cursor_p.fetch()
        assert cursor_res["count_remaining"] == 300
        assert cursor_res["count_total"] == 500
        assert cursor_res["used_percent"] == 40.0

        original_cursor_find = providers.CursorProvider._find_token
        try:
            providers.CursorProvider._find_token = staticmethod(lambda: "")
            cursor_missing = providers.CursorProvider({}).fetch()
            assert cursor_missing["status"] == ProviderStatus.STALE
            assert cursor_missing["error"] == "Cuota inaccesible"
            assert "count_total" not in cursor_missing
            assert "remaining_percent" not in cursor_missing
        finally:
            providers.CursorProvider._find_token = original_cursor_find

        # BentoWindow Contract & Dynamic Card reflow
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication, QLabel
        from ui.bento_window import BentoWindow

        app = QApplication.instance() or QApplication([])
        win = BentoWindow()
        assert set(win.ai_cards) == {"codex", "gemini", "copilot", "grok", "cursor"}
        assert win.bento_ai_cards["cursor"]["value"].text() == "--"
        assert win.cyber_ai_cards["codex"]["reset"].text() == "Actualizando"
        assert win.cyber_ai_cards["codex"]["val"].text() == "--"
        assert win.bento_val_ag.text() == "--"
        assert win.cyber_lbl_ag_val.text() == "CUOTA NO PUBLICADA"
        assert not any(
            isinstance(widget, QLabel) and widget.isVisible() and widget.parent() is None
            for widget in app.topLevelWidgets()
        )
        win.update_antigravity(unavailable)
        assert win.bento_val_ag.text() == "--"
        win.update_antigravity({
            "status": ProviderStatus.RATE_LIMITED,
            "usage_percent": 100.0,
            "remaining_percent": 0.0,
            "is_exhausted": True,
        })
        assert win.bento_val_ag.text() == "0%"

        # Test enabling extended providers
        win.update_ai_modules({
            "show_antigravity": True, "show_codex": True, "show_gemini": True,
            "show_copilot": True, "show_grok": True, "show_cursor": True,
            "show_openrouter": True, "show_deepseek": True, "show_kimi": True, "show_perplexity": True,
        })
        assert "openrouter" in win.bento_ai_cards
        assert "deepseek" in win.bento_ai_cards
        assert "kimi" in win.bento_ai_cards
        assert "perplexity" in win.bento_ai_cards

        win.update_antigravity({
            "status": ProviderStatus.OK,
            "usage_percent": 92.0,
            "remaining_percent": 8.0,
            "reset_desc": "49h 0m",
            "windows": {
                "five_hour": {"reset_desc": "4h 59m"},
                "weekly": {"remaining_percent": 8.0, "reset_desc": "49h 0m"},
            },
            "models": [{
                "label": "Gemini Pro",
                "remaining_percent": 8.0,
                "reset_desc": "49h 0m",
            }],
        })
        assert win.bento_val_ag.text() == "8%"
        assert win.bento_sub_ag.text() == "Cuota 5h"
        assert win.bento_foot_ag.text() == "Sem 8% · 49h 0m"
        assert win.bento_pill_ag.text() == "4h 59m"
        assert "Gemini Pro: 8.0%" in win.bento_card_ag.toolTip()

        win.update_quota_provider("copilot", counted_copilot)
        assert win.bento_ai_cards["copilot"]["value"].text() == "37/200"
        assert win.bento_ai_cards["copilot"]["subtitle"].text() == "premium used"
        assert win.bento_ai_cards["copilot"]["foot"].text() == "1 Oct"
        assert "Esperando" not in win.bento_ai_cards["copilot"]["subtitle"].text()

        win.update_quota_provider("gemini", gemini_live)
        assert win.bento_ai_cards["gemini"]["subtitle"].text() == "Cuota semanal"
        assert "reinicia 6d 23h" == win.bento_ai_cards["gemini"]["foot"].text()

        codex_weekly = {
            "status": ProviderStatus.OK,
            "used_percent": 20.0,
            "remaining_percent": 80.0,
            "reset_desc": "4h 50m",
            "windows": {
                "secondary": {"remaining_percent": 65.0, "reset_desc": "6d 23h"}
            },
        }
        win.update_quota_provider("codex", codex_weekly)
        assert win.bento_ai_cards["codex"]["value"].text() == "80%"
        assert win.bento_ai_cards["codex"]["subtitle"].text() == "Cuota 5h"
        assert win.bento_ai_cards["codex"]["pill"].text() == "4h 50m"
        assert win.bento_ai_cards["codex"]["foot"].text() == "Sem 65% · 6d 23h"
        assert win.cyber_ai_cards["codex"]["reset"].text() == "RESET 5H: 4H 50M · SEM: 65% / 6D 23H"
        assert not win.bento_ai_cards["codex"]["gauge"].isHidden()
        assert win.bento_ai_cards["codex"]["gauge"].value() == 80.0
        assert not win.bento_ai_cards["codex"]["pill"].isHidden()
        assert "Esperando" not in win.bento_ai_cards["codex"]["subtitle"].text()

        # Claude 5h Primary Verification
        win.update_claude({
            "status": ProviderStatus.OK,
            "raw": {
                "five_hour": {"utilization": 25.0, "resets_at": None},
                "seven_day": {"utilization": 50.0, "resets_at": None},
            }
        })
        assert win.bento_val_claude.text() == "75%"
        assert win.bento_sub_claude.text() == "Cuota 5h"
        assert win.bento_pill_claude.text() == "5h Activa"
        assert "Sem 50%" in win.bento_foot_claude.text()
        assert not win.bento_gauge_claude.isHidden()
        assert win.bento_gauge_claude.value() == 75.0

        win.update_claude({"status": ProviderStatus.AUTH_ERROR, "error": "Token expirado"})
        assert win.bento_val_claude.text() == "--"
        assert win.bento_sub_claude.text() == "Token expirado"
        assert "Token expirado" in win.bento_card_claude.toolTip()

        win.update_quota_provider("cursor", cursor_missing)
        assert win.bento_ai_cards["cursor"]["subtitle"].text() == "Cuota inaccesible"
        assert win.bento_ai_cards["cursor"]["foot"].text() == "Sin verificar"
        assert win.bento_ai_cards["cursor"]["gauge"].isHidden()

        win.update_quota_provider("grok", grok_result)
        assert win.bento_ai_cards["grok"]["value"].text() == "88%"
        assert win.bento_ai_cards["grok"]["subtitle"].text() == "Remaining quota"
        assert win.cyber_ai_cards["grok"]["val"].text() == "QUOTA: 88% LEFT"
        assert not [widget for widget in app.topLevelWidgets() if widget is not win]

        # Test mode cycling on extended provider
        win.update_quota_provider("openrouter", or_res)
        assert win.bento_ai_cards["openrouter"]["value"].text() == "$39.50"
        win._cycle_card_mode("openrouter")
        win.update_quota_provider("openrouter", or_res)
        assert win.bento_ai_cards["openrouter"]["subtitle"].text() == "Total Usage"
        win.close()
    finally:
        providers._request_json = original
        providers._json_file = original_json_file
    print("AI provider contract OK")


if __name__ == "__main__":
    main()
