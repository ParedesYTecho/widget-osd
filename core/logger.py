"""
logger.py — Sistema de logging estructurado, rotativo y sanitizado para Widget OSD.
Garantiza un límite estricto de 2 MB (máx. 2 backups) y enmascara automáticamente
cualquier token, contraseña o dato confidencial.
"""

import logging
import os
import re
import sys
import threading
from logging.handlers import RotatingFileHandler

_LOG_ROOT = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
_LOG_DIR = os.path.join(_LOG_ROOT, "WidgetOSD", "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "widget_osd.log")
_MAX_BYTES = 2 * 1024 * 1024  # 2 MB
_BACKUP_COUNT = 2

# Patrones para sanitizar tokens y claves
_TOKEN_PATTERNS = [
    re.compile(r"(Authorization[\"']?\s*[:=]\s*[\"']?(?:Bearer|token)\s+)[^\s\"',;]+", re.IGNORECASE),
    re.compile(r"(Bearer\s+)[a-zA-Z0-9\-_.~+/=]+", re.IGNORECASE),
    re.compile(
        r"([\"']?(?:access[_-]?token|refresh[_-]?token|id[_-]?token|api[_-]?key|password|secret|cookie|csrf(?:[_-]?token)?)[\"']?\s*[:=]\s*[\"']?)[^\s\"',;}]+",
        re.IGNORECASE,
    ),
    re.compile(r"(?:sk-(?:ant-)?|github_pat_|gh[pousr]_|pplx-)[a-zA-Z0-9\-_]{6,}", re.IGNORECASE),
]


class SanitizingFormatter(logging.Formatter):
    """Formateador que filtra automáticamente credenciales y datos sensibles."""

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        for index, pattern in enumerate(_TOKEN_PATTERNS):
            replacement = r"\1***[REDACTED]***" if index < len(_TOKEN_PATTERNS) - 1 else "***[REDACTED]***"
            msg = pattern.sub(replacement, msg)
        return msg


def setup_logger(name: str = "WidgetOSD") -> logging.Logger:
    """Configura y devuelve el logger singleton seguro y rotativo."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = SanitizingFormatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_error = None
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        file_handler = RotatingFileHandler(
            _LOG_FILE,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)
        logger.addHandler(file_handler)
    except OSError as exc:
        file_error = exc

    # Handler para stderr (solo errores críticos en consola)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.WARNING)
    logger.addHandler(console_handler)

    if file_error is not None:
        logger.warning("Logging a archivo desactivado: %s", file_error)

    return logger


def get_log_path() -> str:
    """Ruta estable del log rotativo para diagnóstico y soporte."""
    return _LOG_FILE


def install_exception_hooks(target_logger: logging.Logger) -> None:
    """Registra excepciones no controladas del hilo principal y threads Python."""
    previous_main = sys.excepthook
    previous_thread = getattr(threading, "excepthook", None)

    def _main_hook(exc_type, exc_value, exc_traceback):
        target_logger.critical("Excepción no controlada", exc_info=(exc_type, exc_value, exc_traceback))
        if previous_main not in (None, sys.__excepthook__):
            previous_main(exc_type, exc_value, exc_traceback)

    def _thread_hook(args):
        target_logger.critical(
            "Excepción no controlada en thread %s",
            getattr(args.thread, "name", "unknown"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        if previous_thread not in (None, threading.__excepthook__):
            previous_thread(args)

    sys.excepthook = _main_hook
    if previous_thread is not None:
        threading.excepthook = _thread_hook


logger = setup_logger()
