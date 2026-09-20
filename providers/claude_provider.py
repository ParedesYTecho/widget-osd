"""
claude_provider.py — Proveedor blindado de estadísticas de Claude vía API OAuth.
Incluye:
- Almacenamiento seguro de credenciales con Windows Credential Locker (KeyringManager / DPAPI).
- CircuitBreaker para mitigar tormentas de reintentos y saturación de red.
- Sanitización estricta de tokens en logs y mensajes de error.
- Límite de lectura de red acotado a 1 MB (Anti-OOM).
"""

import base64
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from core.circuit_breaker import CircuitBreaker
from core.keyring_manager import KeyringManager
from core.logger import logger
from providers.base import DataProvider, ProviderStatus

_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_TOKEN_URL = "https://api.anthropic.com/v1/oauth/token"
_OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"

_REQUEST_HEADERS = {
    "anthropic-beta": "oauth-2025-04-20",
    "Content-Type": "application/json",
    "User-Agent": "claude-code/2.1.0",
}

_REQUEST_TIMEOUT = 10  # segundos
_MAX_RESPONSE_BYTES = 1048576  # 1 MB límite estricto de lectura (Anti-OOM)
_DEFAULT_CREDENTIALS_PATH = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")
_DEFAULT_CACHE_PATH = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "WidgetOSD", "claude_usage.json")
_CREDENTIALS_LOCK = threading.Lock()

_BACKOFF_BASE = 300   # 5 min
_BACKOFF_FACTOR = 2
_BACKOFF_MAX = 900    # 15 min


def _win_dpapi_unprotect(blob: bytes) -> bytes | None:
    if not sys.platform.startswith("win") or not blob:
        return None
    try:
        import ctypes
        import ctypes.wintypes as wt

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        in_buf = ctypes.create_string_buffer(blob, len(blob))
        in_blob = DATA_BLOB(len(blob), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char)))
        out_blob = DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        ok = crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob))
        if not ok:
            return None
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)
    except Exception:
        return None


def _win_gcm_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, tag: bytes) -> bytes | None:
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes
        import ctypes.wintypes as wt

        bcrypt = ctypes.windll.bcrypt

        class BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wt.ULONG), ("dwInfoVersion", wt.ULONG),
                ("pbNonce", ctypes.c_void_p), ("cbNonce", wt.ULONG),
                ("pbAuthData", ctypes.c_void_p), ("cbAuthData", wt.ULONG),
                ("pbTag", ctypes.c_void_p), ("cbTag", wt.ULONG),
                ("pbMacContext", ctypes.c_void_p), ("cbMacContext", wt.ULONG),
                ("cbAAD", wt.ULONG), ("cbData", ctypes.c_ulonglong), ("dwFlags", wt.ULONG),
            ]

        h_alg = ctypes.c_void_p()
        h_key = ctypes.c_void_p()
        key_buf = ctypes.create_string_buffer(key, len(key))
        nonce_buf = ctypes.create_string_buffer(nonce, len(nonce))
        tag_buf = ctypes.create_string_buffer(tag, len(tag))
        ct_buf = ctypes.create_string_buffer(ciphertext, len(ciphertext))
        out = ctypes.create_string_buffer(max(1, len(ciphertext)))
        out_len = wt.ULONG(0)

        if bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(h_alg), "AES", None, 0) != 0:
            return None
        try:
            mode = "ChainingModeGCM".encode("utf-16-le") + b"\x00\x00"
            mode_buf = ctypes.create_string_buffer(mode, len(mode))
            if bcrypt.BCryptSetProperty(h_alg, "ChainingMode", mode_buf, len(mode), 0) != 0:
                return None
            if bcrypt.BCryptGenerateSymmetricKey(h_alg, ctypes.byref(h_key), None, 0, key_buf, len(key), 0) != 0:
                return None
            try:
                auth = BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO()
                auth.cbSize = ctypes.sizeof(auth)
                auth.dwInfoVersion = 1
                auth.pbNonce = ctypes.cast(nonce_buf, ctypes.c_void_p)
                auth.cbNonce = len(nonce)
                auth.pbTag = ctypes.cast(tag_buf, ctypes.c_void_p)
                auth.cbTag = len(tag)
                status = bcrypt.BCryptDecrypt(
                    h_key, ct_buf, len(ciphertext), ctypes.byref(auth), None, 0, out, len(ciphertext), ctypes.byref(out_len), 0
                )
                if status != 0:
                    return None
                return out.raw[:out_len.value]
            finally:
                if h_key:
                    bcrypt.BCryptDestroyKey(h_key)
        finally:
            if h_alg:
                bcrypt.BCryptCloseAlgorithmProvider(h_alg, 0)
    except Exception:
        return None


def _claude_desktop_tokens() -> list[str]:
    """Descubre tokens OAuth activos mantenidos por Claude Desktop en Windows."""
    if not sys.platform.startswith("win"):
        return []
    candidates = [
        Path(os.environ.get("APPDATA", "")) / "Claude",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Claude",
    ]
    packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Packages"
    if packages.exists():
        try:
            for p in packages.iterdir():
                if "claude" in p.name.lower() or "anthropic" in p.name.lower():
                    candidates.append(p / "LocalCache" / "Roaming" / "Claude")
        except (OSError, PermissionError):
            pass

    tokens = []
    for profile in candidates:
        state_file = profile / "Local State"
        cfg_file = profile / "config.json"
        if not (state_file.exists() and cfg_file.exists()):
            continue
        try:
            local_state = json.loads(state_file.read_text(encoding="utf-8"))
            enc_key = base64.b64decode(local_state["os_crypt"]["encrypted_key"])
            if not enc_key.startswith(b"DPAPI"):
                continue
            key = _win_dpapi_unprotect(enc_key[5:])
            if not key:
                continue
            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
            val = cfg.get("oauth:tokenCacheV2") or cfg.get("oauth:tokenCache")
            if not isinstance(val, str):
                continue
            blob = base64.b64decode(val)
            if len(blob) < 31:
                continue
            dec = _win_gcm_decrypt(key, blob[3:15], blob[15:-16], blob[-16:])
            if not dec:
                continue
            cache = json.loads(dec.decode("utf-8"))
            if isinstance(cache, dict):
                for entry in cache.values():
                    tok = entry.get("token") or entry.get("accessToken")
                    if tok and isinstance(tok, str) and tok not in tokens:
                        tokens.append(tok)
        except Exception:
            continue
    return tokens


def _get_claude_local_cache() -> dict[str, Any] | None:
    """Extrae uso de Claude Code sin costo de tokens desde ~/.claude.json."""
    claude_json_path = Path.home() / ".claude.json"
    if not claude_json_path.exists():
        return None
    try:
        data = json.loads(claude_json_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        cached = data.get("cachedUsageUtilization")
        account = data.get("oauthAccount") or {}
        if isinstance(cached, dict) and isinstance(cached.get("utilization"), dict):
            util = cached["utilization"]
            windows = [util.get("five_hour"), util.get("seven_day"), util.get("seven_day_opus")]
            if any(
                isinstance(window, dict)
                and any(key in window for key in ("utilization", "percent"))
                for window in windows
            ):
                return {
                    "five_hour": util.get("five_hour", {}),
                    "seven_day": util.get("seven_day", {}),
                    "seven_day_opus": util.get("seven_day_opus", {}),
                    "account": account,
                    "source": "local_cache",
                }
    except Exception:
        pass
    return None


class ClaudeProvider(DataProvider):
    """Proveedor que obtiene estadísticas de uso de Claude desde la API OAuth."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self._refresh_interval: float = float(
            config.get("refresh_interval_seconds", 300)
        )
        self._manual_token: str = config.get("oauth_token", "").strip()
        self._credentials_path = config.get("credentials_path", "").strip() or _DEFAULT_CREDENTIALS_PATH
        self._circuit_breaker = CircuitBreaker("Claude_API", failure_threshold=3, cooldown_seconds=60.0)

        self._backoff_until: float = 0.0
        self._backoff_seconds: float = _BACKOFF_BASE
        self._cache_path = config.get("cache_path", "").strip() or _DEFAULT_CACHE_PATH
        self._last_good_response: dict[str, Any] | None = self._load_cache()
        self._last_error: str | None = None
        self._expired_tokens: set[str] = set()
        self._active_token: str | None = None

    def fetch(self) -> dict[str, Any]:
        now = time.time()
        if now < self._backoff_until:
            retry_in = self._backoff_until - now
            return {
                "status": ProviderStatus.RATE_LIMITED,
                "error": f"Rate limited — reintento en {int(retry_in)}s",
                "stale": self._last_good_response is not None,
                "retry_in": retry_in,
                "raw": self._last_good_response,
            }

        token = self._get_token()
        if token is None:
            local = _get_claude_local_cache()
            if local:
                return {
                    "status": ProviderStatus.STALE,
                    "error": "Cuota local no actualizada; token expirado o ausente",
                    "stale": True,
                    "retry_in": None,
                    "raw": local,
                }
            if self._last_good_response:
                return {
                    "status": ProviderStatus.STALE,
                    "error": "Token expirado o ausente; última cuota válida",
                    "stale": True,
                    "retry_in": None,
                    "raw": self._last_good_response,
                }
            return {
                "status": ProviderStatus.AUTH_ERROR,
                "error": self._last_error or "token_expired",
                "stale": False,
                "retry_in": None,
                "raw": None,
                "hint": "Ejecuta 'claude login' o introduce tu token en 'Config'",
            }

        def _do_request():
            headers = dict(_REQUEST_HEADERS)
            headers["Authorization"] = f"Bearer {token}"
            req = urllib.request.Request(_USAGE_URL, headers=headers, method="GET")

            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:  # nosec B310
                raw_bytes = resp.read(_MAX_RESPONSE_BYTES)
                return json.loads(raw_bytes.decode("utf-8"))

        try:
            raw_data = self._circuit_breaker.call(_do_request)
            if raw_data is None:
                local = _get_claude_local_cache()
                if local:
                    return {
                        "status": ProviderStatus.STALE,
                        "error": "API de Claude no disponible; cuota local no actualizada",
                        "stale": True,
                        "raw": local,
                    }
                return {
                    "status": ProviderStatus.ERROR,
                    "error": "CircuitBreaker abierto: saltando llamada para ahorrar red/CPU",
                    "stale": self._last_good_response is not None,
                    "retry_in": None,
                    "raw": self._last_good_response,
                }

            self._backoff_seconds = _BACKOFF_BASE
            self._backoff_until = 0.0
            self._last_good_response = raw_data
            self._save_cache(raw_data)
            self._last_error = None

            return {
                "status": ProviderStatus.OK,
                "error": None,
                "stale": False,
                "retry_in": None,
                "raw": raw_data,
            }

        except urllib.error.HTTPError as exc:
            return self._handle_http_error(exc)

        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            local = _get_claude_local_cache()
            if local:
                return {
                    "status": ProviderStatus.STALE,
                    "error": "Error de red; cuota local no actualizada",
                    "stale": True,
                    "raw": local,
                }
            sanitized_err = self._sanitize_error(str(exc))
            logger.warning(f"Error conectando con API de Claude: {sanitized_err}")
            return {
                "status": ProviderStatus.ERROR,
                "error": f"Error de conexión: {sanitized_err}",
                "stale": self._last_good_response is not None,
                "retry_in": None,
                "raw": self._last_good_response,
            }

    def get_interval(self) -> float:
        return self._refresh_interval

    def get_name(self) -> str:
        return "claude"

    def set_manual_token(self, token: str, persist_to_file: bool = True) -> bool:
        """Guarda un token OAuth criptoseguramente en Windows Credential Locker."""
        token = token.strip()
        self._manual_token = token
        self._backoff_until = 0.0
        self._last_error = None

        if not token:
            return False

        return KeyringManager.set_claude_token(token)

    def test_token(self, candidate_token: str | None = None) -> tuple[bool, str, dict[str, Any] | None]:
        """Prueba un token contra la API de Anthropic con lectura acotada."""
        token = (candidate_token or "").strip() or self._get_token()
        if not token:
            return False, "No se proporcionó ningún token", None

        headers = dict(_REQUEST_HEADERS)
        headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(_USAGE_URL, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:  # nosec B310
                raw_bytes = resp.read(_MAX_RESPONSE_BYTES)
                raw_data: dict[str, Any] = json.loads(raw_bytes.decode("utf-8"))
            return True, "Conexión exitosa con Anthropic", raw_data
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                return False, f"Token inválido o expirado (HTTP {exc.code})", None
            if exc.code == 429:
                return True, "Token válido pero con rate-limit temporal (429)", None
            return False, f"Error HTTP {exc.code}: {exc.reason}", None
        except Exception as exc:
            return False, f"Error de red: {self._sanitize_error(str(exc))}", None

    def _get_token(self) -> str | None:
        candidates: list[str] = []
        if self._manual_token:
            candidates.append(self._manual_token)

        env_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
        if env_token and env_token not in candidates:
            candidates.append(env_token)

        oauth = self._read_oauth_credentials()
        token = str(oauth.get("accessToken", "")).strip()
        if token and not token.startswith("[") and token not in candidates:
            expires_at = oauth.get("expiresAt")
            refresh_token = str(oauth.get("refreshToken") or "").strip()
            refresh_expires_at = oauth.get("refreshTokenExpiresAt")
            try:
                access_expires = float(expires_at)
                if access_expires > 10_000_000_000:
                    access_expires /= 1000
            except (TypeError, ValueError):
                access_expires = None
            try:
                refresh_expires = float(refresh_expires_at)
                if refresh_expires > 10_000_000_000:
                    refresh_expires /= 1000
            except (TypeError, ValueError):
                refresh_expires = None
            refresh_valid = bool(refresh_token) and (
                refresh_expires is None or refresh_expires > time.time()
            )
            if access_expires is not None and access_expires <= time.time() and not refresh_valid:
                self._expired_tokens.add(token)
            else:
                candidates.append(token)

        vault_token = KeyringManager.get_claude_token()
        if vault_token and vault_token not in candidates:
            candidates.append(vault_token)

        for dt in _claude_desktop_tokens():
            if dt and dt not in candidates:
                candidates.append(dt)

        for candidate in candidates:
            if candidate not in self._expired_tokens:
                self._active_token = candidate
                return candidate

        self._active_token = None
        subscription_type = str(oauth.get("subscriptionType") or "").strip().lower()
        if subscription_type in {"free", "none"}:
            self._last_error = "Sin suscripción a Claude Code"
        elif oauth.get("accessToken") or self._expired_tokens:
            self._last_error = "Token expirado"
        else:
            self._last_error = "Credenciales no encontradas"
        return None

    def _read_oauth_credentials(self) -> dict[str, Any]:
        try:
            with open(self._credentials_path, "r", encoding="utf-8") as fh:
                return json.load(fh).get("claudeAiOauth", {})
        except (OSError, ValueError, TypeError):
            return {}

    def _load_cache(self) -> dict[str, Any] | None:
        try:
            with open(self._cache_path, "r", encoding="utf-8") as fh:
                cached = json.load(fh)
            raw = cached.get("raw")
            return raw if isinstance(raw, dict) else None
        except (OSError, ValueError, TypeError):
            return None

    def _save_cache(self, raw: dict[str, Any]) -> None:
        try:
            os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
            temporary = self._cache_path + ".tmp"
            with open(temporary, "w", encoding="utf-8") as fh:
                json.dump({"saved_at": time.time(), "raw": raw}, fh)
            os.replace(temporary, self._cache_path)
        except (OSError, ValueError, TypeError) as exc:
            logger.warning(f"No se pudo guardar caché Claude: {exc}")

    def _handle_http_error(self, exc: urllib.error.HTTPError) -> dict[str, Any]:
        code = exc.code
        if code in (401, 403):
            auth_error = "Token expirado" if code == 401 else "Sin suscripción a Claude Code o acceso no permitido"
            if self._active_token:
                self._expired_tokens.add(self._active_token)
            # Intentar refresco si hay refresh_token disponible
            refresh_tok = str(self._read_oauth_credentials().get("refreshToken", "")).strip()
            if not refresh_tok:
                refresh_tok = KeyringManager.get_claude_refresh_token()
            if refresh_tok:
                new_access = self._refresh_access_token(refresh_tok)
                if new_access:
                    self._expired_tokens.discard(new_access)
                    return self.fetch()

            # Resiliente: si la sesión OAuth expiró, extraer caché local de ~/.claude.json
            local = _get_claude_local_cache()
            if local:
                return {
                    "status": ProviderStatus.STALE,
                    "error": f"{auth_error}; cuota local no actualizada",
                    "stale": True,
                    "retry_in": None,
                    "raw": local,
                }
            if self._last_good_response:
                return {
                    "status": ProviderStatus.STALE,
                    "error": f"{auth_error}; última cuota válida",
                    "stale": True,
                    "retry_in": None,
                    "raw": self._last_good_response,
                }

            return {
                "status": ProviderStatus.AUTH_ERROR,
                "error": auth_error,
                "stale": False,
                "retry_in": None,
                "raw": None,
                "hint": "Ejecuta 'claude login' o actualiza tu token en 'Config'",
            }

        if code == 429:
            self._backoff_until = time.time() + self._backoff_seconds
            retry_in = self._backoff_seconds
            self._backoff_seconds = min(self._backoff_seconds * _BACKOFF_FACTOR, _BACKOFF_MAX)
            return {
                "status": ProviderStatus.RATE_LIMITED,
                "error": f"Rate limited (429) — reintento en {int(retry_in)}s",
                "stale": self._last_good_response is not None,
                "retry_in": retry_in,
                "raw": self._last_good_response,
            }

        return {
            "status": ProviderStatus.ERROR,
            "error": f"HTTP {code}: {exc.reason}",
            "stale": self._last_good_response is not None,
            "retry_in": None,
            "raw": self._last_good_response,
        }

    def _refresh_access_token(self, refresh_token: str) -> str | None:
        body = json.dumps({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": _OAUTH_CLIENT_ID,
        }).encode("utf-8")

        req = urllib.request.Request(
            _TOKEN_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "claude-code/2.1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:  # nosec B310
                raw_bytes = resp.read(_MAX_RESPONSE_BYTES)
                token_data = json.loads(raw_bytes.decode("utf-8"))

            new_access = token_data.get("access_token")
            new_refresh = token_data.get("refresh_token", refresh_token)
            if new_access:
                self._save_refreshed_credentials(new_access, new_refresh, token_data)
                return new_access
        except Exception as e:
            logger.warning(f"Fallo al refrescar token OAuth: {e}")

        return None

    def _save_refreshed_credentials(
        self, access_token: str, refresh_token: str, token_data: dict[str, Any]
    ) -> None:
        """Actualiza el archivo que posee Claude CLI sin borrar metadatos ajenos."""
        with _CREDENTIALS_LOCK:
            try:
                with open(self._credentials_path, "r", encoding="utf-8") as fh:
                    creds = json.load(fh)
                oauth = dict(creds.get("claudeAiOauth", {}))
                oauth["accessToken"] = access_token
                oauth["refreshToken"] = refresh_token
                if token_data.get("expires_in") is not None:
                    oauth["expiresAt"] = int((time.time() + float(token_data["expires_in"])) * 1000)
                if token_data.get("scope"):
                    oauth["scopes"] = str(token_data["scope"]).split()
                creds["claudeAiOauth"] = oauth
                tmp = self._credentials_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(creds, fh, indent=2)
                os.replace(tmp, self._credentials_path)
            except (OSError, ValueError, TypeError) as exc:
                logger.warning(f"No se pudieron guardar credenciales OAuth renovadas: {exc}")
                KeyringManager.set_claude_token(access_token, refresh_token)

    def _sanitize_error(self, err_str: str) -> str:
        if not err_str:
            return ""
        if self._manual_token and self._manual_token in err_str:
            err_str = err_str.replace(self._manual_token, "[MASKED_TOKEN]")
        return err_str
