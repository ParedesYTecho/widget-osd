"""
keyring_manager.py — Gestión criptosegura de credenciales mediante Windows Credential Locker (DPAPI).
Elimina el almacenamiento de tokens en texto plano y proporciona migración automática.
"""

import os

import keyring

from core.logger import logger

_SERVICE_NAME = "WidgetOSD_Claude"
_ACCESS_TOKEN_KEY = "access_token"
_REFRESH_TOKEN_KEY = "refresh_token"
_DEFAULT_CLAUDE_CREDS = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")


class KeyringManager:
    """Manejador centralizado de credenciales en el Almacén Seguro de Windows."""

    @staticmethod
    def get_claude_token() -> str | None:
        """Obtiene un token manual del almacén seguro de Windows."""
        try:
            token = keyring.get_password(_SERVICE_NAME, _ACCESS_TOKEN_KEY)
            if token and token.strip():
                return token.strip()
        except Exception as e:
            logger.warning(f"No se pudo consultar Windows Credential Locker: {e}")

        # Fallback a variable de entorno
        env_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
        if env_token:
            KeyringManager.set_claude_token(env_token)
            return env_token

        return None

    @staticmethod
    def set_claude_token(token: str, refresh_token: str | None = None) -> bool:
        """Almacena el token de Claude de forma cifrada en Windows Credential Locker."""
        token = (token or "").strip()
        if not token:
            return False

        try:
            keyring.set_password(_SERVICE_NAME, _ACCESS_TOKEN_KEY, token)
            if refresh_token:
                keyring.set_password(_SERVICE_NAME, _REFRESH_TOKEN_KEY, refresh_token.strip())
            logger.info("Token de Claude guardado criptoseguramente en Windows Credential Locker (DPAPI).")
            return True
        except Exception as e:
            logger.error(f"Error al guardar token en Windows Credential Locker: {e}")
            return False

    @staticmethod
    def get_claude_refresh_token() -> str | None:
        """Obtiene el refresh token de Claude desde Windows Credential Locker."""
        try:
            val = keyring.get_password(_SERVICE_NAME, _REFRESH_TOKEN_KEY)
            return val.strip() if val else None
        except Exception:
            return None

    @staticmethod
    def delete_claude_tokens() -> bool:
        """Elimina los tokens almacenados en Windows Credential Locker."""
        try:
            try:
                keyring.delete_password(_SERVICE_NAME, _ACCESS_TOKEN_KEY)
            except Exception:
                pass
            try:
                keyring.delete_password(_SERVICE_NAME, _REFRESH_TOKEN_KEY)
            except Exception:
                pass
            logger.info("Tokens de Claude eliminados de Windows Credential Locker.")
            return True
        except Exception as e:
            logger.error(f"Error al eliminar tokens: {e}")
            return False
