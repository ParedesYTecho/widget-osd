"""
base.py — Clase base abstracta y enumeración de estados para proveedores de datos.

Todos los proveedores del widget deben heredar de :class:`DataProvider`
e implementar ``fetch()``, ``get_interval()`` y ``get_name()``.
"""

from abc import ABC, abstractmethod
from enum import Enum


class ProviderStatus(str, Enum):
    """Estado del resultado de un proveedor compatible con strings."""
    OK           = "ok"
    ERROR        = "error"
    LOADING      = "loading"
    STALE        = "stale"
    AUTH_ERROR   = "auth_error"
    RATE_LIMITED = "rate_limited"


class DataProvider(ABC):
    """Interfaz que todo proveedor de datos del widget debe implementar."""

    @abstractmethod
    def fetch(self) -> dict:
        """Obtiene datos actualizados. Se ejecuta en hilo de fondo.

        Returns:
            Diccionario con al menos la clave ``"status"`` (:class:`ProviderStatus`).
        """
        ...

    @abstractmethod
    def get_interval(self) -> float:
        """Intervalo de refresco en segundos entre llamadas a ``fetch()``.

        Returns:
            Número de segundos (float).
        """
        ...

    @abstractmethod
    def get_name(self) -> str:
        """Identificador único del proveedor.

        Returns:
            Cadena con el nombre (e.g. ``"claude"``, ``"system"``).
        """
        ...
