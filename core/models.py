"""
models.py — Modelos de validación estricta con Pydantic v2 para telemetría, cuotas y configuración.
Garantiza cero caídas ante datos incompletos, corruptos o de tipos erróneos.
"""

from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator


class FanTelemetry(BaseModel):
    name: str = "Fan"
    rpm: float = Field(default=0.0, ge=0.0)
    hardware: str = "Hardware"

    @field_validator("rpm", mode="before")
    @classmethod
    def parse_rpm(cls, v: Any) -> float:
        try:
            return max(0.0, float(v or 0.0))
        except (ValueError, TypeError):
            return 0.0


class HardwareTelemetry(BaseModel):
    status: str = "ok"
    cpu_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    cpu_temp: float | None = Field(default=None, ge=0.0, le=150.0)
    cpu_power: float | None = Field(default=None, ge=0.0)
    gpu_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    gpu_temp: float | None = Field(default=None, ge=0.0, le=150.0)
    gpu_hotspot: float | None = Field(default=None, ge=0.0, le=150.0)
    ram_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    ram_used_gb: float = Field(default=0.0, ge=0.0)
    ram_total_gb: float = Field(default=0.0, ge=0.0)
    vram_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    vram_used_gb: float | None = Field(default=None, ge=0.0)
    fps: float = Field(default=0.0, ge=0.0, le=5000.0)
    top_process: str = ""
    top_process_gb: float = Field(default=0.0, ge=0.0)
    fans: list[dict[str, Any]] = Field(default_factory=list)
    is_admin: bool = False
    error: str | None = None

    @field_validator("cpu_percent", "gpu_percent", "ram_percent", "vram_percent", mode="before")
    @classmethod
    def clamp_percent(cls, v: Any) -> float:
        try:
            val = float(v or 0.0)
            return max(0.0, min(100.0, val))
        except (ValueError, TypeError):
            return 0.0

    @field_validator("fps", mode="before")
    @classmethod
    def clamp_fps(cls, v: Any) -> float:
        try:
            return max(0.0, min(5000.0, float(v or 0.0)))
        except (ValueError, TypeError):
            return 0.0


class AntigravityTelemetry(BaseModel):
    status: str = "ok"
    usage_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    remaining_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    reset_desc: str = ""
    reset_time: str | None = None
    plan_name: str = "No disponible"
    user_name: str | None = None
    models: list[dict[str, Any]] = Field(default_factory=list)
    is_live: bool = True
    user_turns_5h: int = Field(default=0, ge=0)
    user_turns_24h: int = Field(default=0, ge=0)
    total_steps_5h: int = Field(default=0, ge=0)
    total_conversations: int = Field(default=0, ge=0)
    max_turns_5h: int | None = Field(default=None, gt=0)
    stream_errors_30m: int = Field(default=0, ge=0)
    is_exhausted: bool = False
    windows: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ClaudeTelemetry(BaseModel):
    status: str = "ok"
    five_hour_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    seven_day_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    raw: dict[str, Any] | None = None
    stale: bool = False
    retry_in: float | None = None
    hint: str | None = None
    error: str | None = None


class HotkeyConfig(BaseModel):
    modifiers: list[str] = Field(default_factory=lambda: ["ctrl"])
    key: str = "period"


class DisplayConfig(BaseModel):
    monitor: int = 1
    corner: str = "top-right"
    offset_x: int = 30
    offset_y: int = 30


class AiModulesConfig(BaseModel):
    show_claude: bool = True
    show_antigravity: bool = True
    show_codex: bool = True
    show_gemini: bool = False
    show_copilot: bool = True
    show_grok: bool = True
    show_cursor: bool = True
    show_openrouter: bool = False
    show_deepseek: bool = False
    show_kimi: bool = False
    show_perplexity: bool = False


class AppConfigModel(BaseModel):
    hotkey: HotkeyConfig = Field(default_factory=HotkeyConfig)
    display: DisplayConfig = Field(default_factory=DisplayConfig)
    ui_scale: float = Field(default=1.0, ge=0.6, le=2.0)
    content_mode: Literal["all", "hardware", "fps", "quotas"] = "all"
    autostart: bool = Field(default=False)
    theme_style: str = Field(default="bento_glass")
    ai_modules: AiModulesConfig = Field(default_factory=AiModulesConfig)
    fan_aliases: dict[str, str] = Field(default_factory=lambda: {
        "CPU": "CPU Fan",
        "CPU_OPT": "CPU Optional",
        "Chasis1": "Chassis 1",
        "GPU Ventilador": "GPU Fan"
    })
    antigravity: dict[str, Any] = Field(default_factory=lambda: {
        "max_turns_5h": 60,
        "refresh_interval_seconds": 15.0
    })
    claude: dict[str, Any] = Field(default_factory=lambda: {
        "refresh_interval_seconds": 300.0
    })
    providers: dict[str, dict[str, Any]] = Field(default_factory=lambda: {
        name: {"refresh_interval_seconds": 300.0}
        for name in ("codex", "gemini", "copilot", "grok", "cursor", "openrouter", "deepseek", "kimi", "perplexity")
    })
