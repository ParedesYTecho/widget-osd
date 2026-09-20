"""
config_manager.py — Gestión centralizada y validada de configuración con Pydantic v2.
Lee y escribe config.json con validación estricta de tipos, rangos y persistencia atómica.
"""

import json
import os
import shutil
import time
from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from core.logger import logger
from core.models import AppConfigModel


class ConfigManager:
    """Administrador de configuración con validación Pydantic v2 y persistencia atómica."""

    DEFAULT_CONFIG: dict[str, Any] = AppConfigModel().model_dump()

    def __init__(self, config_path: str) -> None:
        self._config_path: str = config_path
        self._config: dict[str, Any] = self.load()

    @property
    def path(self) -> str:
        return self._config_path

    def load(self) -> dict[str, Any]:
        """Lee y valida config.json con Pydantic v2."""
        if not os.path.isfile(self._config_path):
            self.save(self.DEFAULT_CONFIG)
            self._config = deepcopy(self.DEFAULT_CONFIG)
            return self._config

        rewrite = False
        can_rewrite = True
        try:
            with open(self._config_path, "r", encoding="utf-8") as fh:
                user_cfg: dict[str, Any] = json.load(fh)
            if not isinstance(user_cfg, dict):
                raise ValueError("la raíz de config.json debe ser un objeto JSON")
        except (json.JSONDecodeError, UnicodeError, ValueError) as e:
            backup = self._backup_invalid_config()
            logger.warning(f"Archivo de configuración corrupto ({e}). Backup: {backup or 'no disponible'}")
            user_cfg = {}
            rewrite = True
        except OSError as e:
            logger.warning(f"Archivo de configuración ilegible ({e}). Usando defaults sin sobrescribirlo.")
            user_cfg = {}
            can_rewrite = False

        merged = self._deep_merge(self.DEFAULT_CONFIG, user_cfg)

        try:
            validated = AppConfigModel.model_validate(merged)
            self._config = validated.model_dump()
            if can_rewrite and self._config != user_cfg:
                rewrite = True
        except ValidationError as exc:
            backup = self._backup_invalid_config()
            repaired = deepcopy(merged)
            for error in exc.errors():
                self._restore_default_at(repaired, error.get("loc", ()))
            try:
                self._config = AppConfigModel.model_validate(repaired).model_dump()
            except ValidationError:
                self._config = deepcopy(self.DEFAULT_CONFIG)
            logger.warning(
                f"Configuración inválida reparada campo a campo. Backup: {backup or 'no disponible'}"
            )
            rewrite = True

        if rewrite:
            self.save(self._config)

        return self._config

    def save(self, config: dict[str, Any]) -> bool:
        """Escribe la configuración en config.json de forma atómica (.tmp + os.replace)."""
        directory = os.path.dirname(self._config_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        try:
            validated = AppConfigModel.model_validate(self._deep_merge(self.DEFAULT_CONFIG, config))
            data_to_save = validated.model_dump()
        except Exception as exc:
            logger.error(f"Configuración rechazada; se conserva la última válida: {exc}")
            return False

        tmp_path = self._config_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(data_to_save, fh, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self._config_path)
            self._config = data_to_save
            return True
        except Exception as e:
            logger.error(f"Error guardando configuración atómica: {e}")
            return False

    def get(self, *keys: str, default: Any = None) -> Any:
        current: Any = self._config
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current

    @property
    def hotkey_config(self) -> dict[str, Any]:
        return self._config.get("hotkey", self.DEFAULT_CONFIG["hotkey"])

    def set_hotkey(self, modifiers: list[str], key: str) -> None:
        config = dict(self._config)
        config["hotkey"] = {
            "modifiers": list(modifiers),
            "key": str(key).lower()
        }
        self.save(config)

    @property
    def display_config(self) -> dict[str, Any]:
        return self._config.get("display", self.DEFAULT_CONFIG["display"])

    def set_position(self, x: int, y: int, corner: str = "custom") -> None:
        """Actualiza y persiste la posición de la ventana en pantalla."""
        config = dict(self._config)
        config["display"] = {
            "monitor": self.display_config.get("monitor", 1),
            "corner": corner,
            "offset_x": int(x),
            "offset_y": int(y),
        }
        self.save(config)

    def set_corner(self, corner: str) -> None:
        """Actualiza la esquina de anclaje predeterminada."""
        disp = dict(self.display_config)
        disp["corner"] = corner
        config = dict(self._config)
        config["display"] = disp
        self.save(config)

    @property
    def autostart(self) -> bool:
        return bool(self._config.get("autostart", False))

    def set_autostart(self, enabled: bool) -> None:
        config = dict(self._config)
        config["autostart"] = bool(enabled)
        self.save(config)

    @property
    def ui_scale(self) -> float:
        try:
            return float(self._config.get("ui_scale", self.DEFAULT_CONFIG["ui_scale"]))
        except (ValueError, TypeError):
            return 1.2

    def set_ui_scale(self, scale: float) -> None:
        config = dict(self._config)
        config["ui_scale"] = round(max(0.6, min(2.0, float(scale))), 2)
        self.save(config)

    @property
    def theme_style(self) -> str:
        return str(self._config.get("theme_style", "bento_glass"))

    def set_theme_style(self, style: str) -> None:
        valid_styles = {"bento_glass", "cyberpunk_hud", "minimalist_compact"}
        target = style if style in valid_styles else "bento_glass"
        config = dict(self._config)
        config["theme_style"] = target
        self.save(config)

    def set_content_mode(self, mode: str) -> None:
        config = dict(self._config)
        config["content_mode"] = mode
        self.save(config)

    def set_ai_modules(self, modules: dict[str, bool]) -> None:
        config = dict(self._config)
        config["ai_modules"] = dict(modules)
        self.save(config)

    @property
    def ai_modules_config(self) -> dict[str, bool]:
        return self._config.get("ai_modules", self.DEFAULT_CONFIG["ai_modules"])

    @property
    def claude_config(self) -> dict[str, Any]:
        return self._config.get("claude", self.DEFAULT_CONFIG["claude"])

    @property
    def fan_aliases(self) -> dict[str, str]:
        return self._config.get("fan_aliases", self.DEFAULT_CONFIG["fan_aliases"])

    @property
    def antigravity_config(self) -> dict[str, Any]:
        return self._config.get("antigravity", self.DEFAULT_CONFIG["antigravity"])

    def provider_config(self, name: str) -> dict[str, Any]:
        return self._config.get("providers", {}).get(name, {})

    @staticmethod
    def _deep_merge(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for key, default_val in defaults.items():
            if key in overrides:
                override_val = overrides[key]
                if isinstance(default_val, dict) and isinstance(override_val, dict):
                    merged[key] = ConfigManager._deep_merge(default_val, override_val)
                else:
                    merged[key] = override_val
            else:
                merged[key] = default_val

        for key, val in overrides.items():
            if key not in defaults:
                merged[key] = val

        return merged

    def _backup_invalid_config(self) -> str | None:
        if not os.path.isfile(self._config_path):
            return None
        backup = (
            f"{self._config_path}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}"
            f"-{time.time_ns() % 1_000_000_000:09d}"
        )
        try:
            shutil.copy2(self._config_path, backup)
            return backup
        except OSError as exc:
            logger.warning(f"No se pudo crear backup de config inválida: {exc}")
            return None

    @classmethod
    def _restore_default_at(cls, candidate: dict[str, Any], location: tuple[Any, ...]) -> bool:
        if not location or not all(isinstance(part, str) for part in location):
            return False
        target: Any = candidate
        default: Any = cls.DEFAULT_CONFIG
        for part in location[:-1]:
            if not isinstance(target, dict) or not isinstance(default, dict) or part not in default:
                return False
            target = target.get(part)
            default = default.get(part)
        key = location[-1]
        if not isinstance(target, dict) or not isinstance(default, dict) or key not in default:
            return False
        target[key] = deepcopy(default[key])
        return True
