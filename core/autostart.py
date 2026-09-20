r"""
autostart.py — Gestión segura del autoinicio de Widget OSD con Windows.
Crea o elimina el acceso directo en la carpeta Startup (%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup).
"""

import os
import sys
from core.logger import logger

_STARTUP_DIR = os.path.join(
    os.path.expandvars(r"%APPDATA%"),
    "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
)
_SHORTCUT_NAME = "WidgetOSD_AutoStart.lnk"
_SHORTCUT_PATH = os.path.join(_STARTUP_DIR, _SHORTCUT_NAME)


def _ps_literal(value: str) -> str:
    """Escapa una cadena para literal PowerShell entre comillas simples."""
    return value.replace("'", "''")


def _powershell_exe() -> str | None:
    """Usa PowerShell del sistema; evita resolver un ejecutable arbitrario desde PATH."""
    system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
    candidate = os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return candidate if os.path.isfile(candidate) else None


def get_target_exe() -> str:
    """Obtiene la ruta al ejecutable de producción o al script de ejecución."""
    if getattr(sys, "frozen", False):
        return sys.executable

    return sys.executable


def is_autostart_enabled() -> bool:
    """Comprueba si el acceso directo de autoinicio existe."""
    return os.path.isfile(_SHORTCUT_PATH)


def set_autostart(enabled: bool) -> bool:
    """Habilita o deshabilita el autoinicio con Windows."""
    try:
        if not enabled:
            if os.path.isfile(_SHORTCUT_PATH):
                os.remove(_SHORTCUT_PATH)
                logger.info("Autoinicio de Windows desactivado (acceso directo eliminado).")
            return True

        # Crear acceso directo con argumento --tray
        target_exe = get_target_exe()
        if not os.path.isfile(target_exe):
            logger.warning(f"No se encontró el ejecutable para autoinicio en: {target_exe}")
            return False

        os.makedirs(_STARTUP_DIR, exist_ok=True)

        shortcut_path = _ps_literal(_SHORTCUT_PATH)
        safe_target = _ps_literal(target_exe)
        safe_workdir = _ps_literal(os.path.dirname(target_exe))

        # Usar WScript.Shell vía powershell o ctypes/win32com para crear el .lnk
        import subprocess
        powershell = _powershell_exe()
        if not powershell:
            logger.error("PowerShell del sistema no disponible; no se modifica autoinicio.")
            return False
        ps_cmd = f"""
        $WshShell = New-Object -ComObject WScript.Shell
        $Shortcut = $WshShell.CreateShortcut('{shortcut_path}')
        $Shortcut.TargetPath = '{safe_target}'
        $Shortcut.Arguments = '--tray'
        $Shortcut.WorkingDirectory = '{safe_workdir}'
        $Shortcut.IconLocation = '{safe_target},0'
        $Shortcut.Save()
        """
        res = subprocess.run([powershell, "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True)
        if res.returncode == 0 and os.path.isfile(_SHORTCUT_PATH):
            logger.info("Autoinicio con Windows habilitado con éxito (--tray).")
            return True
        else:
            logger.error(f"Error creando acceso directo de autoinicio: {res.stderr}")
            return False

    except Exception as e:
        logger.error(f"Error gestionando autoinicio: {e}")
        return False
