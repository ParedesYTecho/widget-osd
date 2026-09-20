"""Deterministic Antigravity quota parsing checks; no process scan or network."""

import json
import tempfile
from datetime import datetime, timedelta, timezone

from providers.antigravity_provider import AntigravityProvider


def test_parse_keeps_only_provider_evidenced_reset_windows():
    provider = AntigravityProvider()
    reset_time = "2099-01-01T01:02:03Z"
    result = provider._parse_language_server_data({
        "userStatus": {
            "name": "Test",
            "cascadeModelConfigData": {
                "clientModelConfigs": [
                    {
                        "label": "Gemini 2.5 Pro",
                        "modelId": "gemini-pro",
                        "quotaInfo": {
                            "remainingFraction": 0.75,
                            "resetTime": reset_time,
                        },
                    },
                    {
                        "label": "Gemini 2.5 Flash",
                        "modelId": "gemini-flash",
                        "quotaInfo": {
                            "remainingFraction": 0.5,
                            "resetTime": reset_time,
                        },
                    },
                ]
            },
        }
    })

    assert result["remaining_percent"] == 75.0
    assert result["reset_time"] == reset_time
    assert result["windows"]["primary"]["reset_desc"]
    assert result["windows"]["secondary"]["reset_time"] == reset_time
    assert "weekly" not in result["windows"]
    assert result["windows"]["primary"]["label"] == "Antigravity"
    assert result["windows"]["secondary"]["label"] == "Gemini 2.5 Flash"
    assert set(result["windows"]["primary"]) == {
        "label", "remaining_percent", "usage_percent", "reset_desc", "reset_time"
    }


def test_parse_leaves_secondary_empty_without_flash():
    result = AntigravityProvider()._parse_language_server_data({
        "userStatus": {"cascadeModelConfigData": {"clientModelConfigs": [{
            "label": "Gemini 2.5 Pro",
            "quotaInfo": {"remainingFraction": 0.9},
        }]}}
    })

    assert result["windows"]["secondary"] == {}


def test_cache_removes_legacy_weekly_and_refreshes_window_countdowns():
    reset_time = (datetime.now(timezone.utc) + timedelta(hours=2, minutes=3)).isoformat()
    with tempfile.TemporaryDirectory() as directory:
        path = f"{directory}/quota.json"
        with open(path, "w", encoding="utf-8") as stream:
            json.dump({"saved_at": 1, "data": {
                "remaining_percent": 80,
                "reset_time": reset_time,
                "windows": {
                    "primary": {"reset_time": reset_time, "reset_desc": "5h 0m"},
                    "secondary": {"reset_time": reset_time, "reset_desc": "old"},
                    "five_hour": {
                        "remaining_percent": 82,
                        "usage_percent": 18,
                        "reset_time": reset_time,
                        "reset_desc": "old",
                    },
                    "weekly": {"remaining_percent": 80, "reset_desc": "7d"},
                },
                "models": [{"label": "Gemini 2.5 Pro"}],
            }}, stream)

        cached = AntigravityProvider({"cache_path": path})._load_quota_cache()

    assert cached is not None
    assert "weekly" not in cached["windows"]
    assert cached["windows"]["secondary"] == {}
    assert cached["windows"]["primary"]["reset_desc"] != "5h 0m"
    assert "remaining_percent" not in cached["windows"]["five_hour"]
    assert "usage_percent" not in cached["windows"]["five_hour"]


def test_parse_does_not_display_invalid_reset_text():
    result = AntigravityProvider()._parse_language_server_data({
        "userStatus": {
            "cascadeModelConfigData": {
                "clientModelConfigs": [{
                    "label": "Gemini",
                    "quotaInfo": {
                        "remainingFraction": 1,
                        "resetTime": "not-a-timestamp",
                    },
                }]
            }
        }
    })

    assert result["reset_desc"] == ""


def test_parse_keeps_short_reset_without_inventing_five_hour_percentage():
    now = datetime.now(timezone.utc)
    five_hour_reset = (now + timedelta(hours=4, minutes=59)).isoformat()
    weekly_reset = (now + timedelta(days=2, hours=1)).isoformat()
    result = AntigravityProvider()._parse_language_server_data({
        "userStatus": {"cascadeModelConfigData": {"clientModelConfigs": [
            {
                "label": "Gemini 3.1 Pro (High)",
                "quotaInfo": {"remainingFraction": 0.08, "resetTime": weekly_reset},
            },
            {
                "label": "Claude Sonnet 4.6 (Thinking)",
                "quotaInfo": {"resetTime": five_hour_reset},
            },
            {
                "label": "GPT-OSS 120B (Medium)",
                "quotaInfo": {"resetTime": five_hour_reset},
            },
        ]}}
    })

    assert "remaining_percent" not in result["windows"]["five_hour"]
    assert "usage_percent" not in result["windows"]["five_hour"]
    assert result["windows"]["weekly"]["remaining_percent"] == 8.0
    assert result["windows"]["five_hour"]["reset_desc"].startswith("4h")
    assert "h" in result["windows"]["weekly"]["reset_desc"]


def main():
    test_parse_keeps_only_provider_evidenced_reset_windows()
    test_parse_leaves_secondary_empty_without_flash()
    test_cache_removes_legacy_weekly_and_refreshes_window_countdowns()
    test_parse_does_not_display_invalid_reset_text()
    test_parse_keeps_short_reset_without_inventing_five_hour_percentage()
    print("ok")


if __name__ == "__main__":
    main()
