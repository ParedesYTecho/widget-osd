"""
circuit_breaker.py — Patrón Circuit Breaker para evitar saturación de CPU,
bloqueos de hilos y tormentas de reintentos en bridges de hardware y APIs.
"""

import threading
import time
import urllib.error
from collections.abc import Callable
from enum import Enum
from typing import Any

from core.logger import logger


class CircuitState(Enum):
    CLOSED = "CLOSED"        # Operación normal
    OPEN = "OPEN"            # Circuito abierto (falla rápido para no quemar CPU)
    HALF_OPEN = "HALF_OPEN"  # Prueba de recuperación


class CircuitBreaker:
    """Protege la aplicación frente a fallos continuos de subprocesos o APIs."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_state_change = time.time()
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                if (time.time() - self._last_state_change) >= self.cooldown_seconds:
                    self._state = CircuitState.HALF_OPEN
                    logger.info(f"CircuitBreaker '{self.name}' pasó a estado HALF_OPEN (probando recuperación).")
            return self._state

    def call(self, func: Callable[[], Any], fallback: Callable[[], Any] | None = None) -> Any:
        """Ejecuta func si el circuito lo permite; si está abierto, ejecuta fallback o retorna None."""
        curr_state = self.state

        if curr_state == CircuitState.OPEN:
            logger.warning(f"CircuitBreaker '{self.name}' está OPEN. Saltando ejecución para ahorrar CPU.")
            return fallback() if fallback else None

        try:
            result = func()
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure(exc)
            if fallback:
                return fallback()
            raise

    def _on_success(self):
        with self._lock:
            if self._state != CircuitState.CLOSED:
                logger.info(f"CircuitBreaker '{self.name}' recuperado. Estado -> CLOSED.")
            self._failure_count = 0
            self._state = CircuitState.CLOSED

    def _on_failure(self, exc: Exception):
        with self._lock:
            self._failure_count += 1
            auth_failure = isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403)
            if auth_failure:
                logger.info(
                    f"CircuitBreaker '{self.name}' recibió HTTP {exc.code}: autenticación requerida"
                )
            else:
                logger.warning(f"CircuitBreaker '{self.name}' registró fallo #{self._failure_count}: {exc}")
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._last_state_change = time.time()
                message = f"CircuitBreaker '{self.name}' disparado -> Estado OPEN por {self.cooldown_seconds}s."
                (logger.info if auth_failure else logger.error)(message)
