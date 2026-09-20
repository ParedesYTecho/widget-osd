"""
antigravity_provider.py — Proveedor de alta precisión para cuotas de Antigravity AI.
Implementa detección e intercepción directa del Language Server local (gRPC/Connect en 127.0.0.1)
 con soporte multi-modelo (Gemini, Claude, GPT-OSS), caché de última cuota oficial y métricas de logs sin cuota inferida.
"""

import os
import glob
import json
import time
import urllib.parse
import urllib.request
import ssl
from datetime import datetime, timezone
import psutil

from .base import DataProvider, ProviderStatus
from core.models import AntigravityTelemetry
from core.logger import logger

_MAX_TRANSCRIPTS_TO_PROCESS = 50
_MAX_LINE_LENGTH = 65536
_MAX_LINES_PER_FILE = 20000
_DEFAULT_CACHE_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "WidgetOSD",
    "antigravity_usage.json",
)

_EXHAUSTION_KEYWORDS = (
    "the stream was interrupted",
    "resource_exhausted",
    "quota exceeded",
    "rate limit",
    "rate_limit",
    "too many requests",
    "exhausted your capacity",
    "capacity reached",
    "quota limit"
)


class AntigravityProvider(DataProvider):
    """
    Proveedor dual de telemetría de cuotas de Antigravity:
    1. Intercepción en tiempo real del Language Server local (100% oficial y preciso).
    2. Caché del último estado oficial y métricas de logs sin convertirlas en cuota.
    """
    name = "antigravity"

    def __init__(self, config: dict | None = None):
        config = config or {}
        self._gemini_dir = os.path.expandvars(r"%USERPROFILE%\.gemini\antigravity")
        self._brain_dir = os.path.join(self._gemini_dir, "brain")

        self._max_turns_5h = int(config.get("max_turns_5h", config.get("max_requests_5h", 60)))
        if self._max_turns_5h > 200:
            self._max_turns_5h = 60
        self._refresh_interval = float(config.get("refresh_interval_seconds", 15.0))
        self._cache_path = str(config.get("cache_path", "")).strip() or _DEFAULT_CACHE_PATH

        self._last_fetch_time = 0.0
        self._cache_duration = 5.0
        self._cached_data = None

        # Caché de conexión al Language Server
        self._cached_pid: int | None = None
        self._cached_port: int | None = None
        self._cached_csrf: str | None = None

    def _load_quota_cache(self) -> dict | None:
        """Devuelve último estado oficial solo mientras su ventana de reset siga vigente."""
        try:
            with open(self._cache_path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            data = payload.get("data")
            if not isinstance(data, dict):
                return None
            if data.get("remaining_percent") is None and data.get("usage_percent") is None:
                return None

            reset_time = str(data.get("reset_time") or "").strip()
            if not reset_time:
                return None
            reset_at = datetime.fromisoformat(reset_time.replace("Z", "+00:00"))
            if reset_at <= datetime.now(timezone.utc):
                return None

            cached = dict(data)
            cached["status"] = ProviderStatus.STALE
            cached["is_live"] = False
            cached["stale"] = True
            cached["quota_source"] = "disk_cache"
            cached["last_live_at"] = payload.get("saved_at")
            cached["error"] = "Última cuota válida; pendiente de sincronización"
            total_seconds = max(0, int((reset_at - datetime.now(timezone.utc)).total_seconds()))
            hours, remainder = divmod(total_seconds, 3600)
            cached["reset_desc"] = f"{hours}h {remainder // 60}m" if hours else f"{remainder // 60}m"
            now = datetime.now(timezone.utc)
            windows = self._sanitize_windows(cached.get("windows"), now)
            for name, window in self._infer_reset_windows(cached.get("models", []), now).items():
                windows.setdefault(name, window)
            has_flash = any(
                "flash" in str(model.get("label") or "").lower()
                for model in cached.get("models", [])
                if isinstance(model, dict)
            )
            windows["secondary"] = windows.get("secondary", {}) if has_flash else {}
            cached["windows"] = windows
            return cached
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _sanitize_windows(windows: object, now: datetime) -> dict:
        """Keep known quota windows and recalculate each countdown from its reset."""
        if not isinstance(windows, dict):
            return {}
        clean = {}
        for name in ("primary", "secondary", "five_hour", "weekly"):
            window = windows.get(name)
            if not isinstance(window, dict):
                continue
            item = dict(window)
            reset_time = str(item.get("reset_time") or "").strip()
            if name in ("five_hour", "weekly") and not reset_time:
                continue
            # Older builds guessed the 5h percentage from unrelated model quota.
            # The current Language Server only evidences a short reset timestamp,
            # so cached percentages for this window are intentionally discarded.
            if name == "five_hour":
                item.pop("remaining_percent", None)
                item.pop("usage_percent", None)
            item["reset_desc"] = ""
            if reset_time:
                try:
                    reset_at = datetime.fromisoformat(reset_time.replace("Z", "+00:00"))
                    if reset_at.tzinfo is None:
                        reset_at = reset_at.replace(tzinfo=timezone.utc)
                    total_seconds = max(0, int((reset_at - now).total_seconds()))
                    hours, remainder = divmod(total_seconds, 3600)
                    item["reset_desc"] = f"{hours}h {remainder // 60}m" if hours else f"{remainder // 60}m"
                except (TypeError, ValueError):
                    pass
            clean[name] = item
        return clean

    @staticmethod
    def _infer_reset_windows(models: list[dict], now: datetime) -> dict:
        """Expose only reset windows actually evidenced by Language Server fields."""
        timed: list[tuple[int, dict]] = []
        for model in models:
            reset_time = str(model.get("reset_time") or "").strip()
            if not reset_time:
                continue
            try:
                reset_at = datetime.fromisoformat(reset_time.replace("Z", "+00:00"))
                if reset_at.tzinfo is None:
                    reset_at = reset_at.replace(tzinfo=timezone.utc)
                seconds = int((reset_at - now).total_seconds())
            except (TypeError, ValueError):
                continue
            if seconds >= 0:
                timed.append((seconds, model))

        if not timed:
            return {}

        def pack_reset(label: str, candidates: list[tuple[int, dict]]) -> dict:
            seconds, model = min(candidates, key=lambda item: item[0])
            hours, remainder = divmod(max(0, seconds), 3600)
            return {
                "label": label,
                "reset_desc": f"{hours}h {remainder // 60}m" if hours else f"{remainder // 60}m",
                "reset_time": model.get("reset_time"),
            }

        def pack_percent(label: str, candidates: list[tuple[int, dict]]) -> dict:
            seconds, model = min(candidates, key=lambda item: float(item[1]["remaining_percent"]))
            hours, remainder = divmod(max(0, seconds), 3600)
            remaining = float(model["remaining_percent"])
            return {
                "label": label,
                "remaining_percent": remaining,
                "usage_percent": 100.0 - remaining,
                "reset_desc": f"{hours}h {remainder // 60}m" if hours else f"{remainder // 60}m",
                "reset_time": model.get("reset_time"),
            }

        windows: dict[str, dict] = {}
        # Current GetUserStatus exposes short-window resetTime values without a
        # dedicated five_hour remainingFraction. Keep that reset countdown.
        five_candidates = [
            item for item in timed
            if item[0] <= 6 * 3600
        ]
        if five_candidates:
            windows["five_hour"] = pack_reset("5 h", five_candidates)

        weekly_candidates = [
            item for item in timed
            if 6 * 3600 < item[0] <= 8 * 24 * 3600 and item[1].get("remaining_percent") is not None
        ]
        if weekly_candidates:
            windows["weekly"] = pack_percent("Semanal", weekly_candidates)
        return windows

    def _save_quota_cache(self, data: dict) -> None:
        """Persiste solo respuesta oficial con porcentaje y reset explícitos."""
        if data.get("remaining_percent") is None or not data.get("reset_time"):
            return
        try:
            directory = os.path.dirname(self._cache_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            temporary = self._cache_path + ".tmp"
            with open(temporary, "w", encoding="utf-8") as fh:
                json.dump({"saved_at": time.time(), "data": data}, fh, ensure_ascii=False)
            os.replace(temporary, self._cache_path)
        except (OSError, TypeError, ValueError) as exc:
            logger.warning(f"No se pudo guardar caché Antigravity: {exc}")

    def _find_language_server(self) -> tuple[int, list[int], str | None] | None:
        """Localiza el proceso del Language Server, sus puertos de escucha y CSRF token."""
        # 1. Si tenemos un puerto y PID funcional en caché, verificar si sigue vivo
        if self._cached_pid and self._cached_port:
            try:
                p = psutil.Process(self._cached_pid)
                if p.is_running() and "language_server" in p.name().lower():
                    return self._cached_pid, [self._cached_port], self._cached_csrf
            except Exception:
                self._cached_pid = None
                self._cached_port = None
                self._cached_csrf = None

        # 2. Escaneo rápido de procesos
        for p in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                p_name = (p.info['name'] or '').lower()
                if 'language_server' not in p_name:
                    continue

                cmdline = p.info['cmdline'] or []
                csrf_token = None
                for idx, arg in enumerate(cmdline):
                    if arg == '--csrf_token' and idx + 1 < len(cmdline):
                        csrf_token = cmdline[idx + 1]
                    elif arg.startswith('--csrf_token='):
                        csrf_token = arg.split('=', 1)[1]
                    elif 'csrf' in arg.lower() and '=' in arg:
                        csrf_token = arg.split('=', 1)[1]

                # Obtener todos los puertos de escucha del proceso
                ports = []
                for c in p.net_connections():
                    if c.status == 'LISTEN':
                        ports.append(c.laddr.port)

                if ports:
                    return p.info['pid'], ports, csrf_token
            except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
                continue

        return None

    def _fetch_from_language_server(self) -> dict | None:
        """Consulta directamente el endpoint GetUserStatus en los puertos candidatos del Language Server."""
        ls_info = self._find_language_server()
        if not ls_info:
            return None

        pid, ports, csrf = ls_info
        body = json.dumps({
            "metadata": {
                "extension_name": "antigravity",
                "extension_version": "1.0.0"
            }
        }).encode("utf-8")

        for port in ports:
            url = f"https://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/GetUserStatus"
            parsed_url = urllib.parse.urlparse(url)
            if parsed_url.scheme != "https" or parsed_url.hostname != "127.0.0.1":
                continue
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "antigravity",
            }
            if csrf:
                headers["x-codeium-csrf-token"] = csrf

            try:
                req = urllib.request.Request(url, data=body, headers=headers, method="POST")
                local_tls = ssl.create_default_context()
                local_tls.check_hostname = False
                local_tls.verify_mode = ssl.CERT_NONE
                with urllib.request.urlopen(req, context=local_tls, timeout=1.5) as resp:  # nosec B310 B323
                    if resp.status == 200:
                        raw = resp.read().decode("utf-8")
                        # Cachear este puerto exitoso
                        self._cached_pid = pid
                        self._cached_port = port
                        self._cached_csrf = csrf
                        return json.loads(raw)
            except Exception:
                continue

        # Si ninguno respondió, invalidar caché
        self._cached_pid = None
        self._cached_port = None
        self._cached_csrf = None
        return None

    def _parse_language_server_data(self, data: dict) -> dict:
        """Procesa la respuesta oficial de GetUserStatus y calcula métricas."""
        user_status = data.get("userStatus", {})
        user_name = user_status.get("name") or "Usuario"
        plan_name = "Antigravity"

        configs = user_status.get("cascadeModelConfigData", {}).get("clientModelConfigs", [])
        now = datetime.now(timezone.utc)

        models_list = []
        gemini_model = None
        claude_model = None

        for m in configs:
            label = m.get("label", "Modelo")
            model_id = m.get("modelId", "")
            quota = m.get("quotaInfo") or {}
            raw_rem_frac = quota.get("remainingFraction")
            reset_time_str = quota.get("resetTime", "")
            rem_pct = None
            used_pct = None
            if raw_rem_frac is not None:
                try:
                    rem_frac = float(raw_rem_frac)
                except (TypeError, ValueError):
                    rem_frac = None
                if rem_frac is not None and 0.0 <= rem_frac <= 1.0:
                    rem_pct = round(rem_frac * 100.0, 1)
                    used_pct = round((1.0 - rem_frac) * 100.0, 1)

            if rem_pct is None and not reset_time_str:
                continue

            reset_desc = ""
            if reset_time_str:
                try:
                    rt = datetime.fromisoformat(reset_time_str.replace("Z", "+00:00"))
                    if rt.tzinfo is None:
                        rt = rt.replace(tzinfo=timezone.utc)
                    delta = rt - now
                    total_seconds = max(0, int(delta.total_seconds()))
                    hrs = total_seconds // 3600
                    mins = (total_seconds % 3600) // 60
                    if hrs > 0:
                        reset_desc = f"{hrs}h {mins}m"
                    else:
                        reset_desc = f"{mins}m"
                except (TypeError, ValueError):
                    # No countdown for an unparseable timestamp; raw text is not
                    # evidence of a reset window.
                    reset_desc = ""

            entry = {
                "label": label,
                "model_id": model_id,
                "remaining_percent": rem_pct,
                "usage_percent": used_pct,
                "reset_desc": reset_desc,
                "reset_time": reset_time_str
            }
            models_list.append(entry)

            if rem_pct is not None and "gemini" in label.lower() and gemini_model is None:
                gemini_model = entry
            elif rem_pct is not None and "claude" in label.lower() and claude_model is None:
                claude_model = entry

        gemini_pro = None
        gemini_flash = None
        for m in models_list:
            lbl = m["label"].lower()
            if "gemini" in lbl and m.get("remaining_percent") is not None:
                if "pro" in lbl and gemini_pro is None:
                    gemini_pro = m
                elif "flash" in lbl and gemini_flash is None:
                    gemini_flash = m

        evidenced_models = [m for m in models_list if m.get("remaining_percent") is not None]
        if not evidenced_models:
            return {
                "status": ProviderStatus.STALE,
                "usage_percent": None,
                "remaining_percent": None,
                "reset_desc": "Cuota no disponible",
                "reset_time": None,
                "plan_name": plan_name,
                "user_name": user_name,
                "models": models_list,
                "is_live": False,
                "is_exhausted": False,
                "error": "Language Server no devolvió cuota",
                "windows": self._infer_reset_windows(models_list, now),
            }

        # Modelo primario por defecto de Antigravity
        primary = gemini_pro or gemini_model or evidenced_models[0]
        secondary = gemini_flash or {}

        rem_pct = primary.get("remaining_percent")
        usage_pct = primary.get("usage_percent")
        reset_desc = primary.get("reset_desc", "")
        reset_time = primary.get("reset_time")

        is_exhausted = bool(rem_pct is not None and rem_pct <= 0.01)
        inferred_windows = self._infer_reset_windows(models_list, now)

        return {
            "status": ProviderStatus.OK,
            "usage_percent": usage_pct,
            "remaining_percent": rem_pct,
            "reset_desc": reset_desc,
            "reset_time": reset_time,
            "plan_name": plan_name,
            "user_name": user_name,
            "models": models_list,
            "is_live": True,
            "is_exhausted": is_exhausted,
            "error": None,
            "windows": {
                "primary": {
                    "label": "Antigravity",
                    "remaining_percent": rem_pct,
                    "usage_percent": usage_pct,
                    "reset_desc": reset_desc,
                    "reset_time": reset_time,
                },
                "secondary": (
                    {
                        "label": secondary["label"],
                        "remaining_percent": secondary.get("remaining_percent"),
                        "usage_percent": secondary.get("usage_percent"),
                        "reset_desc": secondary.get("reset_desc", ""),
                        "reset_time": secondary.get("reset_time"),
                    }
                    if secondary else {}
                ),
                **inferred_windows,
            }
        }

    def _analyze_transcripts(self) -> dict:
        """Analizador de logs como fallback cuando el IDE está cerrado."""
        if not os.path.exists(self._brain_dir):
            return {
                "user_turns_5h": 0,
                "user_turns_24h": 0,
                "total_conversations": 0,
                "total_steps_5h": 0,
                "stream_errors_30m": 0,
                "is_exhausted": False
            }

        now = time.time()
        thirty_min_ago = now - (30 * 60)
        five_h_ago = now - (5 * 3600)
        twenty_four_h_ago = now - (24 * 3600)

        user_turns_5h = 0
        user_turns_24h = 0
        total_steps_5h = 0
        stream_errors_30m = 0

        pattern = os.path.join(self._brain_dir, "*", ".system_generated", "logs", "transcript.jsonl")
        transcripts = glob.glob(pattern)
        total_conversations = len(transcripts)

        recent_transcripts = []
        for t_path in transcripts:
            try:
                mtime = os.path.getmtime(t_path)
                if mtime >= twenty_four_h_ago:
                    recent_transcripts.append((mtime, t_path))
            except OSError:
                continue

        recent_transcripts.sort(key=lambda x: x[0], reverse=True)
        recent_transcripts = recent_transcripts[:_MAX_TRANSCRIPTS_TO_PROCESS]

        for mtime, t_path in recent_transcripts:
            try:
                with open(t_path, "r", encoding="utf-8", errors="ignore") as f:
                    line_count = 0
                    for line in f:
                        line_count += 1
                        if line_count > _MAX_LINES_PER_FILE:
                            break
                        if len(line) > _MAX_LINE_LENGTH:
                            continue

                        line = line.strip()
                        if not line:
                            continue

                        try:
                            entry = json.loads(line)
                            entry_type = entry.get("type")
                            created_at_str = entry.get("created_at")
                            content = str(entry.get("content") or "")
                            error_str = str(entry.get("error") or "")

                            if created_at_str and isinstance(created_at_str, str):
                                try:
                                    event_time = datetime.fromisoformat(created_at_str.replace("Z", "+00:00")).timestamp()
                                except Exception:
                                    event_time = mtime
                            else:
                                event_time = mtime

                            is_30m = (event_time >= thirty_min_ago)
                            is_5h = (event_time >= five_h_ago)
                            is_24h = (event_time >= twenty_four_h_ago)

                            if is_30m and entry_type in ("ERROR_MESSAGE", "SYSTEM_MESSAGE"):
                                check_text = (content + " " + error_str).lower()
                                if any(kw in check_text for kw in _EXHAUSTION_KEYWORDS):
                                    stream_errors_30m += 1

                            if entry_type == "USER_INPUT":
                                if is_24h:
                                    user_turns_24h += 1
                                if is_5h:
                                    user_turns_5h += 1

                            if is_5h and ("step_index" in entry or entry_type in ("RUN_COMMAND", "VIEW_FILE", "CODE_ACTION", "GENERIC")):
                                total_steps_5h += 1
                        except Exception:
                            continue
            except Exception:
                continue

        is_exhausted = (stream_errors_30m >= 2)

        return {
            "user_turns_5h": user_turns_5h,
            "user_turns_24h": user_turns_24h,
            "total_conversations": total_conversations,
            "total_steps_5h": total_steps_5h,
            "stream_errors_30m": stream_errors_30m,
            "is_exhausted": is_exhausted
        }

    def fetch(self) -> dict:
        now = time.time()
        if self._cached_data and (now - self._last_fetch_time) < self._cache_duration:
            return self._cached_data

        # 1. Intentar obtención directa y oficial del Language Server
        ls_data = self._fetch_from_language_server()
        if ls_data:
            try:
                parsed = self._parse_language_server_data(ls_data)
                telemetry = AntigravityTelemetry(**parsed)
                result = telemetry.model_dump()
                result["status"] = parsed.get("status", ProviderStatus.OK)
                if result["status"] == ProviderStatus.OK and result.get("remaining_percent") is not None:
                    result["quota_source"] = "language_server"
                    result["stale"] = False
                    result["last_live_at"] = datetime.now(timezone.utc).isoformat()
                    self._save_quota_cache(result)
                self._cached_data = result
                self._last_fetch_time = now
                return result
            except Exception as e:
                logger.warning(f"Error procesando datos del Language Server: {e}")

        # 2. Usar último dato oficial mientras no haya cruzado su reset.
        cached = self._load_quota_cache()
        if cached:
            metrics = self._analyze_transcripts()
            cached.update({
                "user_turns_5h": metrics["user_turns_5h"],
                "user_turns_24h": metrics["user_turns_24h"],
                "total_steps_5h": metrics["total_steps_5h"],
                "total_conversations": metrics["total_conversations"],
                "stream_errors_30m": metrics["stream_errors_30m"],
                "max_turns_5h": self._max_turns_5h,
            })
            self._cached_data = cached
            self._last_fetch_time = now
            return cached

        # 3. Logs solo aportan actividad/errores; no cuota numérica.
        try:
            metrics = self._analyze_transcripts()
            turns_5h = metrics["user_turns_5h"]
            log_rate_limited = metrics["is_exhausted"]

            telemetry = AntigravityTelemetry(
                status=ProviderStatus.RATE_LIMITED if log_rate_limited else ProviderStatus.STALE,
                usage_percent=None,
                remaining_percent=None,
                reset_desc="",
                reset_time=None,
                plan_name="Antigravity",
                models=[],
                is_live=False,
                user_turns_5h=turns_5h,
                user_turns_24h=metrics["user_turns_24h"],
                total_conversations=metrics["total_conversations"],
                total_steps_5h=metrics["total_steps_5h"],
                max_turns_5h=self._max_turns_5h,
                stream_errors_30m=metrics["stream_errors_30m"],
                is_exhausted=False,
                error="Cuota no verificable; sincroniza con Antigravity"
            )

            result = telemetry.model_dump()
            result["status"] = telemetry.status
            self._cached_data = result
            self._last_fetch_time = now
            return result

        except Exception as e:
            logger.warning(f"Error en AntigravityProvider Fallback: {e}")
            return {
                "status": ProviderStatus.ERROR,
                "usage_percent": None,
                "remaining_percent": None,
                "reset_desc": "",
                "reset_time": None,
                "plan_name": "Antigravity",
                "models": [],
                "is_live": False,
                "user_turns_5h": 0,
                "user_turns_24h": 0,
                "total_conversations": 0,
                "total_steps_5h": 0,
                "max_turns_5h": self._max_turns_5h,
                "stream_errors_30m": 0,
                "is_exhausted": False,
                "error": str(e)
            }

    def get_interval(self) -> float:
        return self._refresh_interval

    def get_name(self) -> str:
        return "antigravity"
