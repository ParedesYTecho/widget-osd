"""Providers de cuotas AI inspirados en CodexBar, usando sesiones oficiales locales."""

from __future__ import annotations

import base64
from datetime import datetime
import json
import math
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from providers.base import DataProvider, ProviderStatus

_MAX_RESPONSE = 1024 * 1024


def _validate_https_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Solo se permiten endpoints HTTPS")


def _read_json_response(resp, max_bytes: int = _MAX_RESPONSE) -> dict[str, Any]:
    raw = resp.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"Respuesta JSON supera el límite de {max_bytes} bytes")
    value = json.loads(raw.decode("utf-8"))
    return value if isinstance(value, dict) else {}


def _json_file(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            value = json.load(fh)
            return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _jwt_claims(token: str) -> dict[str, Any]:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        value = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
        return value if isinstance(value, dict) else {}
    except (ValueError, IndexError, UnicodeError, json.JSONDecodeError):
        return {}


def _request_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    _validate_https_url(url)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=request_headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
        return _read_json_response(resp)


def _post_form(url: str, values: dict[str, str], timeout: float = 10.0) -> dict[str, Any]:
    _validate_https_url(url)
    data = urllib.parse.urlencode(values).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
        return _read_json_response(resp)


def _save_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".widget.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _reset_countdown(reset_at: Any) -> str:
    try:
        try:
            reset_ts = float(reset_at)
            if reset_ts > 10_000_000_000:
                reset_ts /= 1000
        except (TypeError, ValueError):
            reset_ts = datetime.fromisoformat(str(reset_at).replace("Z", "+00:00")).timestamp()
        seconds = int(reset_ts - time.time())
        if seconds <= 0:
            return ""
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes = remainder // 60
        if days:
            return f"{days}d {hours}h"
        return f"{hours}h {minutes}m" if hours else f"{minutes}m"
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _valid_percent(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and 0.0 <= number <= 100.0 else None


def _rate_window_key(seconds: int, slot: str) -> tuple[str, str]:
    if seconds and seconds <= 6 * 3600:
        return "five_hour", "5 h"
    if seconds and seconds <= 36 * 3600:
        return "daily", "Diaria"
    if seconds and seconds <= 8 * 86400:
        return "weekly", "Semanal"
    return slot, slot.replace("_", " ").title()


def _rate_windows(rate: dict[str, Any], *, limit_reached: bool = False) -> dict[str, dict[str, Any]]:
    """Normaliza ventanas del servidor sin asumir que primary es siempre 5 h."""
    if not isinstance(rate, dict):
        return {}
    windows: dict[str, dict[str, Any]] = {}
    for slot, raw in (("primary", rate.get("primary_window")), ("secondary", rate.get("secondary_window"))):
        if not isinstance(raw, dict):
            continue
        used = _valid_percent(raw.get("used_percent", raw.get("usedPercent")))
        if used is None:
            remaining = _valid_percent(raw.get("remaining_percent", raw.get("remainingPercent")))
            if remaining is not None:
                used = 100.0 - remaining
        if used is None and limit_reached:
            used = 100.0
        if used is None:
            continue
        try:
            duration = int(float(raw.get("limit_window_seconds") or raw.get("limitWindowSeconds") or 0))
        except (TypeError, ValueError, OverflowError):
            duration = 0
        key, label = _rate_window_key(duration, slot)
        reset_at = raw.get("reset_at", raw.get("resetAt"))
        reset_desc = _reset_countdown(reset_at) if reset_at else ""
        if not reset_desc:
            try:
                seconds = max(0, int(float(raw.get("reset_after_seconds") or raw.get("resetAfterSeconds") or 0)))
                days, remainder = divmod(seconds, 86400)
                hours, remainder = divmod(remainder, 3600)
                minutes = remainder // 60
                reset_desc = f"{days}d {hours}h" if days else (f"{hours}h {minutes}m" if hours else f"{minutes}m")
            except (TypeError, ValueError, OverflowError):
                reset_desc = ""
        packed = {
            "used_percent": used,
            "remaining_percent": max(0.0, 100.0 - used),
            "reset_at": reset_at,
            "reset_desc": reset_desc,
            "label": label,
            "limit_window_seconds": duration,
        }
        windows[key] = packed
        windows[slot] = packed
    return windows


def _result(
    name: str,
    used: float,
    label: str,
    *,
    second: float | None = None,
    second_label: str = "",
    reset_at: Any = None,
    plan: str = "",
    details: list[dict[str, Any]] | None = None,
    reset_desc: str = "",
    count_remaining: int | None = None,
    count_total: int | None = None,
    count_used: int | None = None,
    is_unlimited: bool = False,
    windows: dict[str, Any] | None = None,
    balance: float | None = None,
    currency: str = "USD",
) -> dict[str, Any]:
    used = max(0.0, min(100.0, float(used)))
    return {
        "status": ProviderStatus.OK,
        "provider": name,
        "used_percent": used,
        "remaining_percent": 100.0 - used,
        "primary_label": label,
        "secondary_used_percent": None if second is None else max(0.0, min(100.0, float(second))),
        "secondary_label": second_label,
        "reset_at": reset_at,
        "reset_desc": reset_desc,
        "plan": plan,
        "details": details or [],
        "count_remaining": count_remaining,
        "count_total": count_total,
        "count_used": count_used,
        "is_unlimited": is_unlimited,
        "windows": windows or {},
        "balance": balance,
        "currency": currency,
    }


class _QuotaProvider(DataProvider):
    name = "ai"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.interval = float(self.config.get("refresh_interval_seconds", 300))

    def get_name(self) -> str:
        return self.name

    def get_interval(self) -> float:
        return self.interval

    def fetch(self) -> dict[str, Any]:
        try:
            return self._fetch()
        except urllib.error.HTTPError as exc:
            refreshed = False
            if exc.code in (401, 403):
                try:
                    refreshed = self._refresh_credentials()
                except (OSError, ValueError, TypeError, TimeoutError, urllib.error.URLError):
                    refreshed = False
            if refreshed:
                try:
                    return self._fetch()
                except (OSError, ValueError, TypeError, TimeoutError, urllib.error.URLError):
                    pass
            status = ProviderStatus.AUTH_ERROR if exc.code in (401, 403) else ProviderStatus.ERROR
            if self.name == "chatgpt_web":
                error = "Token Web expirado o no autorizado" if exc.code == 401 else "Sesión Web no verificable con el token local"
            else:
                error = f"HTTP {exc.code}"
            return {"status": status, "provider": self.name, "error": error}
        except (OSError, ValueError, TypeError, TimeoutError, urllib.error.URLError) as exc:
            return {"status": ProviderStatus.ERROR, "provider": self.name, "error": str(exc)[:160]}

    def _fetch(self) -> dict[str, Any]:
        raise NotImplementedError

    def _refresh_credentials(self) -> bool:
        return False


class CodexProvider(_QuotaProvider):
    name = "codex"

    @staticmethod
    def _auth_path() -> Path:
        return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "auth.json"

    @classmethod
    def _auth_headers(cls, user_agent: str) -> tuple[str, dict[str, str]]:
        auth = _json_file(cls._auth_path())
        tokens = auth.get("tokens", auth)
        token = str(tokens.get("access_token") or tokens.get("accessToken") or "").strip()
        claims = _jwt_claims(token)
        auth_claims = claims.get("https://api.openai.com/auth", {})
        account_id = str(tokens.get("account_id") or auth_claims.get("chatgpt_account_id") or "").strip()
        headers = {"Authorization": f"Bearer {token}", "User-Agent": user_agent}
        if account_id:
            headers["ChatGPT-Account-Id"] = account_id
        return token, headers

    def _fetch(self) -> dict[str, Any]:
        token, headers = self._auth_headers("codex-cli")
        if not token:
            return {"status": ProviderStatus.AUTH_ERROR, "provider": self.name, "error": "Inicia sesión en Codex"}
        raw = _request_json("https://chatgpt.com/backend-api/wham/usage", headers=headers)
        rate = raw.get("rate_limit") or raw.get("rateLimit") or {}
        if not isinstance(rate, dict):
            rate = {}

        limit_reached = bool(rate.get("limit_reached", False)) or (rate.get("allowed") is False)
        rate_type = raw.get("rate_limit_reached_type")
        if rate_type:
            limit_reached = True

        credits_info = raw.get("credits") or {}
        if not isinstance(credits_info, dict):
            credits_info = {}
        if credits_info.get("has_credits") and credits_info.get("balance") == "0" and credits_info.get("overage_limit_reached", False):
            limit_reached = True

        windows = _rate_windows(rate, limit_reached=limit_reached)
        if not windows:
            raise ValueError("Codex no devolvió ventanas de cuota medibles")
        main = windows.get("five_hour") or windows.get("daily") or windows.get("weekly") or next(iter(windows.values()))
        secondary_window = windows.get("weekly") or windows.get("daily")
        second = secondary_window.get("used_percent") if secondary_window is not None and secondary_window is not main else None

        return _result(
            self.name, main["used_percent"], main["label"], second=second,
            second_label=secondary_window.get("label", "") if second is not None else "",
            reset_at=main.get("reset_at"),
            reset_desc=main.get("reset_desc", ""),
            plan=str(raw.get("plan_type", raw.get("planType", ""))).title(),
            windows=windows,
        )

    def _refresh_credentials(self) -> bool:
        path = self._auth_path()
        auth = _json_file(path)
        tokens = auth.get("tokens", auth)
        refresh = str(tokens.get("refresh_token") or tokens.get("refreshToken") or "").strip()
        if not refresh:
            return False
        raw = _request_json("https://auth.openai.com/oauth/token", body={
            "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "scope": "openid profile email",
        })
        tokens["access_token"] = raw.get("access_token", tokens.get("access_token"))
        tokens["refresh_token"] = raw.get("refresh_token", refresh)
        if raw.get("id_token"):
            tokens["id_token"] = raw["id_token"]
        _save_json(path, auth)
        return bool(tokens.get("access_token"))


class ChatGPTWebProvider(CodexProvider):
    """Cuota Web separada; nunca reutiliza la cuota Codex si el endpoint no la expone."""

    name = "chatgpt_web"

    def _fetch(self) -> dict[str, Any]:
        token, headers = self._auth_headers("Mozilla/5.0")
        if not token:
            return {
                "status": ProviderStatus.AUTH_ERROR,
                "provider": self.name,
                "error": "Inicia sesión en ChatGPT Web",
            }
        raw = _request_json("https://chatgpt.com/backend-api/usage", headers=headers)
        rate = raw.get("rate_limit") or raw.get("rateLimit") or {}
        if not isinstance(rate, dict):
            rate = {}
        windows = _rate_windows(rate, limit_reached=bool(rate.get("limit_reached") or rate.get("allowed") is False))
        if not windows:
            return {
                "status": ProviderStatus.STALE,
                "provider": self.name,
                "error": "ChatGPT Web no publicó una cuota medible",
                "windows": {},
            }
        main = windows.get("five_hour") or windows.get("daily") or windows.get("weekly") or next(iter(windows.values()))
        return _result(
            self.name,
            main["used_percent"],
            main["label"],
            reset_at=main.get("reset_at"),
            reset_desc=main.get("reset_desc", ""),
            plan=str(raw.get("plan_type") or raw.get("planType") or "ChatGPT Web").title(),
            windows=windows,
        )

    def _refresh_credentials(self) -> bool:
        return False


class GeminiProvider(_QuotaProvider):
    name = "gemini"

    def fetch(self) -> dict[str, Any]:
        # Compatibilidad: si Antigravity expone cuota, reutilizarla sin inventar disponibilidad.
        try:
            from providers.antigravity_provider import AntigravityProvider
            fallback = AntigravityProvider(self.config).fetch()
            usage = fallback.get("usage_percent")
            remaining = fallback.get("remaining_percent")
            if fallback.get("status") == ProviderStatus.OK and (usage is not None or remaining is not None):
                used = float(usage) if usage is not None else (100.0 - float(remaining) if remaining is not None else 0.0)
                models = fallback.get("models", [])
                second = models[1].get("usage_percent") if len(models) > 1 else None
                fallback_windows = fallback.get("windows") or {}
                primary_window = fallback_windows.get("weekly") or {}
                if primary_window:
                    weekly = {
                        "label": "Semanal",
                        "used_percent": primary_window.get("usage_percent", used),
                        "remaining_percent": primary_window.get("remaining_percent", 100.0 - used),
                        "reset_at": primary_window.get("reset_time", fallback.get("reset_time")),
                        "reset_desc": primary_window.get("reset_desc", fallback.get("reset_desc", "")),
                    }
                    return _result(
                        self.name, used, "Antigravity",
                        second=second,
                        second_label="Flash" if second is not None else "",
                        reset_at=fallback.get("reset_time"),
                        reset_desc=fallback.get("reset_desc", ""),
                        plan="Antigravity",
                        details=models,
                        windows={"weekly": weekly},
                    )
        except Exception:
            pass

        # Fallback secundario si Antigravity no estuviera disponible
        try:
            return super().fetch()
        except Exception as exc:
            return {"status": ProviderStatus.ERROR, "provider": self.name, "error": str(exc)[:160]}

    def _fetch(self) -> dict[str, Any]:
        creds = _json_file(Path.home() / ".gemini" / "oauth_creds.json")
        token = str(creds.get("access_token", "")).strip()
        if not token:
            return {"status": ProviderStatus.AUTH_ERROR, "provider": self.name, "error": "Inicia sesión en Gemini CLI"}
        headers = {"Authorization": f"Bearer {token}", "User-Agent": "gemini-cli"}
        tier = _request_json(
            "https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist",
            headers=headers,
            body={"metadata": {"ideType": "GEMINI_CLI", "pluginType": "GEMINI"}},
        )
        project = tier.get("cloudaicompanionProject")
        quota = _request_json(
            "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota",
            headers=headers,
            body={"project": project} if project else {},
        )
        buckets = quota.get("buckets") or quota.get("quotaBuckets") or []
        models: list[dict[str, Any]] = []
        for bucket in buckets:
            fraction = bucket.get("remainingFraction")
            if fraction is None:
                continue
            models.append({
                "label": str(bucket.get("modelId", "Modelo")),
                "remaining_percent": max(0.0, min(100.0, float(fraction) * 100.0)),
                "reset_at": bucket.get("resetTime"),
            })
        if not models:
            raise ValueError("Gemini no devolvió cuotas; usa Antigravity para cuentas AI Pro/Ultra")
        pro = [m for m in models if "flash" not in m["label"].lower()] or models
        flash = [m for m in models if "flash" in m["label"].lower()]
        main = min(pro, key=lambda m: m["remaining_percent"])
        alt = min(flash, key=lambda m: m["remaining_percent"]) if flash else None
        paid = tier.get("paidTier") or {}
        plan = str(paid.get("name") or tier.get("currentTier", {}).get("name") or "Gemini")
        reset_desc = _reset_countdown(main.get("reset_at"))
        weekly = {
            "label": "Semanal",
            "used_percent": 100.0 - main["remaining_percent"],
            "remaining_percent": main["remaining_percent"],
            "reset_at": main.get("reset_at"),
            "reset_desc": reset_desc,
        }
        return _result(
            self.name, 100 - main["remaining_percent"], "Pro",
            second=None if alt is None else 100 - alt["remaining_percent"], second_label="Flash",
            reset_at=main.get("reset_at"), reset_desc=reset_desc, plan=plan, details=models,
            windows={"weekly": weekly},
        )

    def _refresh_credentials(self) -> bool:
        path = Path.home() / ".gemini" / "oauth_creds.json"
        creds = _json_file(path)
        refresh = str(creds.get("refresh_token") or "").strip()
        if not refresh:
            return False
        client_id = os.environ.get("GEMINI_OAUTH_CLIENT_ID", "").strip()
        client_secret = os.environ.get("GEMINI_OAUTH_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            return False
        raw = _post_form("https://oauth2.googleapis.com/token", {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        })
        if not raw.get("access_token"):
            return False
        creds.update(raw)
        _save_json(path, creds)
        return True


class CopilotProvider(_QuotaProvider):
    name = "copilot"

    def _token(self) -> str:
        token = str(self.config.get("token", "")).strip() or os.environ.get("GITHUB_TOKEN", "").strip() or os.environ.get("COPILOT_TOKEN", "").strip()
        if token:
            return token
        try:
            tok = subprocess.check_output(
                ["gh", "auth", "token"], text=True, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), stderr=subprocess.DEVNULL,
            ).strip()
            if tok:
                return tok
        except (OSError, subprocess.SubprocessError):
            pass
        hosts_paths = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "github-copilot" / "hosts.json",
            Path(os.environ.get("APPDATA", "")) / "GitHub Copilot" / "hosts.json",
            Path.home() / ".config" / "github-copilot" / "hosts.json",
        ]
        for hp in hosts_paths:
            if hp.exists():
                data = _json_file(hp)
                for entry in data.values():
                    if isinstance(entry, dict) and entry.get("oauth_token"):
                        return str(entry["oauth_token"]).strip()
        return ""

    def _fetch(self) -> dict[str, Any]:
        token = self._token()
        if not token:
            return {"status": ProviderStatus.AUTH_ERROR, "provider": self.name, "error": "Ejecuta: gh auth login"}
        raw = _request_json("https://api.github.com/copilot_internal/user", headers={
            "Authorization": f"token {token}",
            "Editor-Version": "vscode/1.96.2",
            "Editor-Plugin-Version": "copilot-chat/0.26.7",
            "User-Agent": "GitHubCopilotChat/0.26.7",
            "X-Github-Api-Version": "2025-04-01",
        })
        snapshots = raw.get("quotaSnapshots", raw.get("quota_snapshots", {}))
        premium = snapshots.get("premiumInteractions", snapshots.get("premium_interactions", {})) or {}
        chat = snapshots.get("chat", {}) or {}

        def used(item: dict[str, Any]) -> float | None:
            remaining = item.get("percentRemaining", item.get("percent_remaining"))
            remaining_percent = _valid_percent(remaining)
            return None if remaining_percent is None else 100.0 - remaining_percent

        primary = used(premium)
        secondary = used(chat)
        if primary is None and secondary is None:
            raise ValueError("Copilot no devolvió una cuota medible")

        remaining_count = premium.get("remaining", premium.get("quota_remaining"))
        entitlement = premium.get("entitlement", premium.get("quota_entitlement"))
        credits_used = premium.get("credits_used")
        if credits_used is None and remaining_count is not None and entitlement is not None:
            try:
                credits_used = max(0.0, float(entitlement) - float(remaining_count))
            except (TypeError, ValueError):
                credits_used = None

        raw_reset = (
            raw.get("quotaResetDate", raw.get("quota_reset_date"))
            or premium.get("quotaResetAt", premium.get("quota_reset_at"))
            or chat.get("quotaResetAt", chat.get("quota_reset_at"))
        )
        reset_desc = ""
        if raw_reset:
            try:
                if isinstance(raw_reset, (int, float)):
                    reset_desc = _reset_countdown(raw_reset)
                else:
                    dt = datetime.fromisoformat(str(raw_reset).replace("Z", "+00:00"))
                    months = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
                    reset_desc = f"{dt.day} {months[dt.month - 1]} {dt.year}"
            except Exception:
                reset_desc = str(raw_reset)

        primary_label = "Premium"
        if remaining_count is not None and entitlement is not None:
            primary_label = f"{remaining_count} / {entitlement} Premium"

        if primary is None:
            primary, primary_label, secondary = secondary, "Chat", None

        windows: dict[str, dict[str, Any]] = {}
        if primary is not None:
            windows["premium"] = {
                "label": "Premium" if primary_label != "Chat" else "Chat",
                "used_percent": primary,
                "remaining_percent": 100.0 - primary,
                "reset_at": raw_reset,
                "reset_desc": reset_desc,
            }
        if secondary is not None:
            windows["chat"] = {
                "label": "Chat",
                "used_percent": secondary,
                "remaining_percent": 100.0 - secondary,
                "reset_at": chat.get("quotaResetAt", chat.get("quota_reset_at")),
                "reset_desc": _reset_countdown(chat.get("quotaResetAt", chat.get("quota_reset_at"))) if chat.get("quotaResetAt", chat.get("quota_reset_at")) else reset_desc,
            }

        return _result(
            self.name, primary, primary_label, second=secondary, second_label="Chat",
            reset_at=raw_reset,
            reset_desc=reset_desc,
            count_remaining=remaining_count,
            count_total=entitlement,
            count_used=credits_used,
            plan=str(raw.get("copilotPlan", raw.get("copilot_plan", "Copilot"))).title(),
            windows=windows,
        )


class GrokProvider(_QuotaProvider):
    name = "grok"

    @staticmethod
    def _find_auth(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            if value.get("key") and (value.get("refresh_token") or value.get("email")):
                return value
            for child in value.values():
                found = GrokProvider._find_auth(child)
                if found:
                    return found
        return {}

    def _fetch(self) -> dict[str, Any]:
        home = Path(os.environ.get("GROK_HOME") or Path.home() / ".grok")
        auth = self._find_auth(_json_file(home / "auth.json"))
        token = str(auth.get("key") or os.environ.get("GROK_OAUTH_TOKEN", "")).strip()
        if not token:
            return {"status": ProviderStatus.AUTH_ERROR, "provider": self.name, "error": "Ejecuta: grok login"}
        headers = {"Authorization": f"Bearer {token}", "x-xai-token-auth": "xai-grok-cli"}
        raw = _request_json("https://cli-chat-proxy.grok.com/v1/billing?format=credits", headers=headers)
        config = raw.get("config", raw)
        percent = config.get("creditUsagePercent")
        on_demand_used = (config.get("onDemandUsed") or {}).get("val")
        on_demand_cap = (config.get("onDemandCap") or {}).get("val")
        plan = str(config.get("subscriptionTier") or "Grok").strip()
        explicit_unlimited = bool(config.get("isUnlimited") is True or "unlimited" in plan.lower())
        is_unlimited = explicit_unlimited
        if percent is None:
            if on_demand_cap is not None and float(on_demand_cap) > 0:
                percent = float(on_demand_used or 0) / float(on_demand_cap) * 100
            elif explicit_unlimited:
                percent = 0.0
            else:
                return {
                    "status": ProviderStatus.STALE,
                    "provider": self.name,
                    "error": "Cuota Grok no verificable",
                    "plan": plan,
                }

        period = config.get("currentPeriod") or {}
        if plan.lower() in {"oidc", "oauth", "oauth2"}:
            plan = "Grok"
        if is_unlimited:
            label = "Ilimitado (Web)"
            if plan == "Grok":
                plan = "Unlimited Web"
        else:
            label = "Créditos"

        raw_reset = period.get("end") or config.get("billingPeriodEnd")
        reset_desc = ""
        if raw_reset:
            try:
                dt = datetime.fromisoformat(str(raw_reset).replace("Z", "+00:00"))
                months = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
                reset_desc = f"{dt.day} {months[dt.month - 1]} {dt.year}"
            except Exception:
                reset_desc = str(raw_reset)

        return _result(
            self.name, percent, label,
            reset_at=raw_reset,
            reset_desc=reset_desc,
            plan=plan,
            is_unlimited=is_unlimited
        )

    def _refresh_credentials(self) -> bool:
        path = Path(os.environ.get("GROK_HOME") or Path.home() / ".grok") / "auth.json"
        root = _json_file(path)
        for entry in root.values():
            if not isinstance(entry, dict) or not entry.get("refresh_token") or not entry.get("oidc_client_id"):
                continue
            issuer = str(entry.get("oidc_issuer") or "https://auth.x.ai").rstrip("/")
            parsed_issuer = urllib.parse.urlparse(issuer)
            if parsed_issuer.scheme != "https" or parsed_issuer.hostname != "auth.x.ai":
                return False
            raw = _post_form(f"{issuer}/oauth2/token", {
                "client_id": str(entry["oidc_client_id"]),
                "refresh_token": str(entry["refresh_token"]),
                "grant_type": "refresh_token",
            })
            token = raw.get("access_token")
            if not token:
                return False
            entry["key"] = token
            entry["refresh_token"] = raw.get("refresh_token", entry["refresh_token"])
            _save_json(path, root)
            return True
        return False


class CursorProvider(_QuotaProvider):
    name = "cursor"

    @staticmethod
    def _find_token() -> str:
        token = os.environ.get("CURSOR_SESSION_TOKEN", "").strip()
        if token:
            return token
        appdata = Path(os.environ.get("APPDATA", ""))
        candidates = [
            appdata / "Cursor" / "User" / "globalStorage" / "state.vscdb",
            Path.home() / ".config" / "cursor" / "User" / "globalStorage" / "state.vscdb",
            Path.home() / ".cursor" / "auth.json",
        ]
        for cand in candidates:
            if cand.suffix == ".json" and cand.exists():
                data = _json_file(cand)
                tok = str(data.get("access_token") or data.get("token") or "").strip()
                if tok:
                    return tok
            elif cand.suffix == ".vscdb" and cand.exists():
                try:
                    import sqlite3
                    conn = sqlite3.connect(f"file:{cand}?mode=ro", uri=True)
                    cur = conn.cursor()
                    cur.execute("SELECT value FROM ItemTable WHERE key IN ('cursorAuth/accessToken', 'WorkosCursorSessionToken') LIMIT 1")
                    row = cur.fetchone()
                    conn.close()
                    if row and row[0]:
                        val = str(row[0]).strip().strip('"')
                        if val:
                            return val
                except Exception:
                    pass
        return ""

    def _fetch(self) -> dict[str, Any]:
        token = self._find_token() or str(self.config.get("token", "")).strip()
        if not token:
            return {
                "status": ProviderStatus.STALE,
                "provider": self.name,
                "error": "Cuota inaccesible",
            }

        cookie = token
        if "::" in token and "%3A%3A" not in token:
            parts = token.split("::", 1)
            cookie = f"{parts[0]}%3A%3A{parts[1]}"
        elif "." in token and "%3A%3A" not in token:
            claims = _jwt_claims(token)
            sub = claims.get("sub", "")
            if sub:
                cookie = f"{sub}%3A%3A{token}"

        headers = {
            "Cookie": f"WorkosCursorSessionToken={cookie}",
            "Accept": "application/json",
            "User-Agent": "Cursor/0.45.0"
        }
        raw = _request_json("https://cursor.com/api/usage-summary", headers=headers)
        individual = raw.get("individualUsage", {})
        plan_usage = individual.get("plan", {})
        used = float(plan_usage.get("totalPercentUsed", plan_usage.get("autoPercentUsed", 0.0)))
        limit = plan_usage.get("limit")
        used_count = plan_usage.get("used")
        plan_type = str(raw.get("membershipType", "Cursor Pro")).title()

        raw_reset = raw.get("billingCycleEnd")
        reset_desc = ""
        if raw_reset:
            try:
                dt = datetime.fromisoformat(str(raw_reset).replace("Z", "+00:00"))
                months = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
                reset_desc = f"{dt.day} {months[dt.month - 1]}"
            except Exception:
                reset_desc = str(raw_reset)

        count_rem = (limit - used_count) if (limit is not None and used_count is not None) else None
        label = f"{count_rem}/{limit}" if (count_rem is not None and limit is not None) else plan_type

        return _result(
            self.name, used, label,
            reset_at=raw_reset,
            reset_desc=reset_desc,
            plan=plan_type,
            count_remaining=count_rem,
            count_total=limit,
            count_used=used_count,
        )


class OpenRouterProvider(_QuotaProvider):
    name = "openrouter"

    def _api_key(self) -> str:
        for var in ("OPENROUTER_API_KEY", "OPENROUTER_KEY"):
            val = os.environ.get(var, "").strip()
            if val:
                return val
        return str(self.config.get("api_key") or self.config.get("token") or "").strip()

    def _fetch(self) -> dict[str, Any]:
        key = self._api_key()
        if not key:
            return {
                "status": ProviderStatus.AUTH_ERROR,
                "provider": self.name,
                "error": "API key de OpenRouter no configurada",
            }
        headers = {"Authorization": f"Bearer {key}", "User-Agent": "WidgetOSD/3.2"}
        raw = _request_json("https://openrouter.ai/api/v1/credits", headers=headers)
        credits_data = raw.get("data", {})
        total_credits = float(credits_data.get("total_credits", 0.0))
        total_usage = float(credits_data.get("total_usage", 0.0))
        balance = max(0.0, total_credits - total_usage)
        used_pct = (total_usage / total_credits * 100.0) if total_credits > 0 else 0.0
        label = f"${balance:.2f}"
        return _result(
            self.name,
            used_pct,
            label,
            second=min(100.0, used_pct),
            second_label=f"${total_usage:.2f} used",
            plan="OpenRouter",
            reset_desc=f"${balance:.2f} bal",
            balance=balance,
            currency="USD",
            windows={
                "primary": {"label": "Balance", "value": f"${balance:.2f}"},
                "secondary": {"label": "Usage", "value": f"${total_usage:.2f}"},
            }
        )


class DeepSeekProvider(_QuotaProvider):
    name = "deepseek"

    def _api_key(self) -> str:
        for var in ("DEEPSEEK_API_KEY", "DEEPSEEK_KEY"):
            val = os.environ.get(var, "").strip()
            if val:
                return val
        return str(self.config.get("api_key") or self.config.get("token") or "").strip()

    def _fetch(self) -> dict[str, Any]:
        key = self._api_key()
        if not key:
            return {
                "status": ProviderStatus.AUTH_ERROR,
                "provider": self.name,
                "error": "API key de DeepSeek no configurada",
            }
        headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
        raw = _request_json("https://api.deepseek.com/user/balance", headers=headers)
        infos = raw.get("balance_infos", [])
        total_bal = 0.0
        topped_up = 0.0
        granted = 0.0
        currency = "CNY"
        if infos and isinstance(infos, list):
            first = infos[0]
            total_bal = float(first.get("total_balance", 0.0))
            topped_up = float(first.get("topped_up_balance", 0.0))
            granted = float(first.get("granted_balance", 0.0))
            currency = str(first.get("currency", "CNY")).upper()
        sym = "¥" if currency == "CNY" else "$"
        label = f"{sym}{total_bal:.2f}"
        second_label = f"Grant: {sym}{granted:.2f}" if granted > 0 else (f"Cash: {sym}{topped_up:.2f}" if topped_up > 0 else "")
        return _result(
            self.name,
            0.0,
            label,
            second=0.0,
            second_label=second_label,
            plan="DeepSeek",
            reset_desc=f"{sym}{total_bal:.2f} bal",
            balance=total_bal,
            currency=currency,
            windows={
                "primary": {"label": "Total Balance", "value": f"{sym}{total_bal:.2f}"},
                "secondary": {
                    "label": "Cash / Grant",
                    "value": f"Cash: {sym}{topped_up:.2f} · Grant: {sym}{granted:.2f}" if granted > 0 else f"Cash: {sym}{topped_up:.2f}",
                },
            }
        )


class KimiProvider(_QuotaProvider):
    name = "kimi"

    def _api_key(self) -> str:
        for var in ("MOONSHOT_API_KEY", "KIMI_API_KEY", "MOONSHOT_KEY"):
            val = os.environ.get(var, "").strip()
            if val:
                return val
        return str(self.config.get("api_key") or self.config.get("token") or "").strip()

    def _fetch(self) -> dict[str, Any]:
        key = self._api_key()
        if not key:
            return {
                "status": ProviderStatus.AUTH_ERROR,
                "provider": self.name,
                "error": "API key de Kimi no configurada",
            }
        headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
        raw = _request_json("https://api.moonshot.cn/v1/users/me/balance", headers=headers)
        data = raw.get("data", {})
        avail = float(data.get("available_balance", 0.0))
        cash = float(data.get("cash_balance", 0.0))
        voucher = float(data.get("voucher_balance", 0.0))
        label = f"¥{avail:.2f}"
        second_label = f"Voucher: ¥{voucher:.2f}" if voucher > 0 else (f"Cash: ¥{cash:.2f}" if cash > 0 else "")
        return _result(
            self.name,
            0.0,
            label,
            second=0.0,
            second_label=second_label,
            plan="Kimi K2",
            reset_desc=f"¥{avail:.2f} bal",
            balance=avail,
            currency="CNY",
            windows={
                "primary": {"label": "Available", "value": f"¥{avail:.2f}"},
                "secondary": {
                    "label": "Cash / Voucher",
                    "value": f"Cash: ¥{cash:.2f} · Voucher: ¥{voucher:.2f}" if voucher > 0 else f"Cash: ¥{cash:.2f}",
                },
            }
        )


class PerplexityProvider(_QuotaProvider):
    name = "perplexity"

    def _api_key(self) -> str:
        for var in ("PERPLEXITY_API_KEY", "PPLX_API_KEY", "PERPLEXITY_TOKEN"):
            val = os.environ.get(var, "").strip()
            if val:
                return val
        return str(self.config.get("api_key") or self.config.get("token") or "").strip()

    def _session_token(self) -> str:
        for var in ("PERPLEXITY_SESSION_TOKEN", "PPLX_SESSION_TOKEN"):
            val = os.environ.get(var, "").strip()
            if val:
                return val
        return str(self.config.get("session_token", "")).strip()

    def _fetch(self) -> dict[str, Any]:
        key = self._api_key()
        session_token = self._session_token()
        session_error = None

        if session_token:
            cookie_val = session_token if "=" in session_token else f"__Secure-next-auth.session-token={session_token}"
            headers = {
                "Cookie": cookie_val,
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
            }
            try:
                raw = _request_json("https://www.perplexity.ai/api/auth/session", headers=headers)
                user = raw.get("user", {})
                tier = str(user.get("subscription_tier") or user.get("subscription_status") or "Pro").title()
                is_pro = "pro" in tier.lower() or bool(user.get("subscription_status") == "active")
                label = "Pro" if is_pro else "Standard"
                return _result(
                    self.name,
                    0.0,
                    label,
                    plan=f"Perplexity {tier}",
                    is_unlimited=True,
                    reset_desc="Active",
                    windows={
                        "primary": {"label": "Subscription", "value": f"Perplexity {tier}"},
                        "secondary": {"label": "Search Tier", "value": "Pro Search Unlimited" if is_pro else "Standard Search"},
                    }
                )
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    session_error = "Token de sesión de Perplexity inválido o expirado"
                else:
                    session_error = f"HTTP {exc.code} al verificar Perplexity"
            except (OSError, ValueError, TypeError, TimeoutError, urllib.error.URLError):
                session_error = "No se pudo verificar la sesión de Perplexity"

        if key:
            headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
            raw = _request_json("https://api.perplexity.ai/models", headers=headers)
            data = raw.get("data", [])
            model_count = len(data) if isinstance(data, list) else 0
            return _result(
                self.name,
                0.0,
                "API Active",
                second_label=f"{model_count} models" if model_count else "Online",
                plan="Perplexity API",
                is_unlimited=True,
                reset_desc="API Active",
                windows={
                    "primary": {"label": "Status", "value": "API Key Verified"},
                    "secondary": {"label": "Models Available", "value": f"{model_count} models"},
                }
            )

        return {
            "status": ProviderStatus.AUTH_ERROR,
            "provider": self.name,
            "error": session_error or "API key o token de sesión de Perplexity no configurado",
        }


def _self_check() -> None:
    result = _result("x", 25, "5 h", second=10)
    assert result["remaining_percent"] == 75
    assert _jwt_claims("x.e30.x") == {}
    cursor_res = CursorProvider().fetch()
    assert cursor_res["status"] in (ProviderStatus.OK, ProviderStatus.STALE, ProviderStatus.AUTH_ERROR)
    for provider in (OpenRouterProvider(), DeepSeekProvider(), KimiProvider(), PerplexityProvider()):
        result = provider.fetch()
        assert result["status"] != ProviderStatus.OK or result.get("remaining_percent") is not None


if __name__ == "__main__":
    _self_check()
