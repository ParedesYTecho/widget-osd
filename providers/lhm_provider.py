"""
lhm_provider.py — Proveedor blindado de telemetría de hardware usando el bridge en C#
hacia LibreHardwareMonitorLib.dll con validación Pydantic v2 y CircuitBreaker.
"""

import ctypes
import ctypes.wintypes as wintypes
import json
import os
import struct
import subprocess
import sys
import time

import psutil

from core.circuit_breaker import CircuitBreaker
from core.logger import logger
from core.models import HardwareTelemetry

from .base import DataProvider, ProviderStatus


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


class LHMProvider(DataProvider):
    """
    Proveedor nativo de telemetría de hardware usando un bridge en C#
    hacia LibreHardwareMonitorLib.dll con aislamiento, CircuitBreaker y validación Pydantic.
    """
    def __init__(self):
        if getattr(sys, 'frozen', False):
            base_dir = os.path.join(sys._MEIPASS, "hardware")
        else:
            base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor")

        self._exe_path = os.path.abspath(os.path.join(base_dir, "HardwareReader.exe"))
        self._last_good_data: dict | None = None
        self._is_admin = is_admin()
        self._circuit_breaker = CircuitBreaker("HardwareReader", failure_threshold=3, cooldown_seconds=30.0)
        self._hwinfo_last_poll = None
        self._hwinfo_stale_reads = 0
        self._last_schtasks_check = 0.0
        self._telemetry_json_path = os.path.join(os.environ.get("LOCALAPPDATA", ""), "WidgetOSD", "telemetry.json")
        self._last_file_timestamp = None

    def _try_launch_scheduled_task(self):
        now = time.time()
        if now - self._last_schtasks_check < 30.0:
            return
        self._last_schtasks_check = now
        try:
            subprocess.Popen(
                ["schtasks", "/run", "/tn", "WidgetOSD_HardwareReader"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
        except Exception:
            pass

    def fetch(self) -> dict:
        if not os.path.isfile(self._exe_path):
            return {
                "status": ProviderStatus.ERROR,
                "error": "HardwareReader binario no encontrado o inaccesible"
            }

        def _execute_reader() -> dict:
            proc = subprocess.run(
                [self._exe_path],
                cwd=os.path.dirname(self._exe_path),
                capture_output=True,
                text=True,
                check=True,
                timeout=2.5,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            output_str = proc.stdout.strip()
            if len(output_str) > 1048576:
                raise ValueError("Salida de telemetría excede el límite de tamaño permitido")
            parsed = json.loads(output_str)
            if isinstance(parsed, dict):
                self._last_file_timestamp = parsed.get("timestamp")
            return parsed

        def _get_data() -> dict:
            # 1. Leer directamente el JSON generado por el daemon elevado solo si es nuevo
            if os.path.isfile(self._telemetry_json_path):
                try:
                    mtime = os.path.getmtime(self._telemetry_json_path)
                    if (time.time() - mtime) < 3.0:
                        with open(self._telemetry_json_path, "r", encoding="utf-8") as fh:
                            parsed = json.load(fh)
                            ts = parsed.get("timestamp")
                            if isinstance(parsed, dict) and "cpu" in parsed:
                                if ts and ts != self._last_file_timestamp:
                                    self._last_file_timestamp = ts
                                    return parsed
                except Exception:
                    pass

            # Intentar arrancar tarea programada si no está corriendo
            self._try_launch_scheduled_task()

            # 2. Ejecución bajo demanda mediante subprocess
            return _execute_reader()

        def _fallback():
            return self._last_good_data

        try:
            data = self._circuit_breaker.call(_get_data, fallback=_fallback)
            if not data:
                return {
                    "status": ProviderStatus.ERROR,
                    "error": "HardwareReader en estado CircuitBreaker OPEN (enfriamiento activo)"
                }

            cpu_data = data.get('cpu', {})
            gpu_data = data.get('gpu', {})
            ram_data = data.get('ram', {})

            # Formatear VRAM
            vram_total = float(gpu_data.get('vram_total_mb') or 0.0)
            vram_used = float(gpu_data.get('vram_used_mb') or 0.0)
            vram_usage_percent = float(gpu_data.get('vram_usage_percent') or 0.0)

            if vram_total > 0 and vram_used >= 0:
                vram_usage_percent = (vram_used / vram_total) * 100.0

            # Formatear CPU Temp
            cpu_temp = cpu_data.get('temp_tctl_tdie')
            if cpu_temp is None or cpu_temp == 0.0:
                cpu_temp = cpu_data.get('temp_package') or 0.0

            cpu_power = cpu_data.get('power_watts') or 0.0

            # Sin elevación, valores ausentes permanecen ausentes. No inventar telemetría.
            cpu_temp = None if cpu_temp == 0.0 else float(cpu_temp)
            cpu_power = None if cpu_power == 0.0 else float(cpu_power)

            # Integración HWiNFO y MSI Afterburner (resiliencia total sin elevación)
            afterburner = self._read_afterburner()
            hwinfo_data = self._read_hwinfo()

            if cpu_temp is None and hwinfo_data.get("cpu_temp") is not None:
                cpu_temp = hwinfo_data["cpu_temp"]
            if cpu_temp is None and afterburner.get("CPU temperature") is not None:
                cpu_temp = float(afterburner["CPU temperature"])

            if cpu_power is None and hwinfo_data.get("cpu_power") is not None:
                cpu_power = hwinfo_data["cpu_power"]
            if cpu_power is None and afterburner.get("CPU power") is not None:
                cpu_power = float(afterburner["CPU power"])

            gpu_core = float(gpu_data['temp_core_edge']) if gpu_data.get('temp_core_edge') else hwinfo_data.get("gpu_temp")
            if gpu_core is None and afterburner.get("GPU temperature") is not None:
                gpu_core = float(afterburner["GPU temperature"])

            fans = data.get('fans', [])
            fan_status = "lhm"
            hwinfo_fans = hwinfo_data.get("fans", [])
            hwinfo_status = hwinfo_data.get("status", "hwinfo_offline")
            fps = hwinfo_data.get("fps", 0.0)

            # Si fans viene de LHM o HWiNFO, enriquecerlos con modelo y ubicación
            if not fans:
                fans, fan_status = hwinfo_fans, hwinfo_status

            # Keep only sensor readings. Missing fan telemetry must remain missing.
            for f in fans:
                f.setdefault("hardware", "Sensor de ventilador")
                f.setdefault("location", "Sensor de hardware")
                f.setdefault("max_rpm", 0)
                rpm = float(f.get("rpm", 0.0))
                max_r = float(f.get("max_rpm") or 0.0)
                if max_r > 0:
                    f["percent"] = round((rpm / max_r) * 100.0, 1)
                f.setdefault("speed_label", "Medición en vivo")

            top_process, top_process_gb = self._top_memory_process()

            telemetry = HardwareTelemetry(
                status="ok",
                cpu_percent=float(cpu_data.get('usage_percent') or 0.0),
                cpu_temp=cpu_temp,
                cpu_power=cpu_power,
                ram_percent=float(ram_data.get('usage_percent') or 0.0),
                ram_used_gb=float(ram_data.get('used_gb') or 0.0),
                ram_total_gb=float(ram_data.get('total_gb') or 0.0),
                gpu_percent=float(gpu_data.get('usage_percent') or 0.0),
                gpu_temp=gpu_core,
                gpu_hotspot=(float(gpu_data['temp_hotspot']) if gpu_data.get('temp_hotspot') else None),
                vram_percent=float(vram_usage_percent or 0.0),
                vram_used_gb=(vram_used / 1024.0) if vram_used else None,
                fps=fps if fps > 0 else 0.0,
                top_process=top_process,
                top_process_gb=top_process_gb,
                fans=fans,
                is_admin=self._is_admin or (cpu_temp is not None),
                error=None
            )

            result = telemetry.model_dump()
            result["status"] = ProviderStatus.OK
            result["fan_status"] = fan_status
            self._last_good_data = data
            return result

        except Exception as e:
            logger.warning(f"Error en LHMProvider: {e}")
            return {
                "status": ProviderStatus.ERROR,
                "error": f"Error de telemetría: {e}"
            }

    def get_interval(self) -> float:
        return 2.0

    def get_name(self) -> str:
        return "system"

    @staticmethod
    def _top_memory_process() -> tuple[str, float]:
        largest_name, largest_rss = "", 0
        for process in psutil.process_iter(("name", "memory_info")):
            try:
                rss = process.info["memory_info"].rss
                if rss > largest_rss:
                    largest_name = process.info["name"] or f"PID {process.pid}"
                    largest_rss = rss
            except (psutil.Error, AttributeError):
                continue
        return largest_name, largest_rss / (1024 ** 3)

    def _read_hwinfo(self) -> dict:
        """Lee RPM, Temperaturas y FPS desde HWiNFO Shared Memory v2."""
        k32 = ctypes.windll.kernel32
        k32.OpenFileMappingW.restype = wintypes.HANDLE
        k32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        k32.MapViewOfFile.restype = ctypes.c_void_p
        k32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
        k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = 0
        for name in ("Global\\HWiNFO_SENS_SM2", "HWiNFO_SENS_SM2"):
            handle = k32.OpenFileMappingW(4, False, name)
            if handle:
                break
        if not handle:
            return {"fans": [], "status": "hwinfo_offline", "fps": 0.0, "cpu_temp": None, "cpu_power": None, "gpu_temp": None}
        address = k32.MapViewOfFile(handle, 4, 0, 0, 0)
        if not address:
            k32.CloseHandle(handle)
            return {"fans": [], "status": "hwinfo_permissions", "fps": 0.0, "cpu_temp": None, "cpu_power": None, "gpu_temp": None}
        try:
            header = ctypes.string_at(address, 44)
            signature, _, _, poll = struct.unpack("<4sIIq", header[:20])
            _, _, _, readings_offset, reading_size, reading_count = struct.unpack("<IIIIII", header[20:44])
            if signature != b"HWiS" or not (284 <= reading_size <= 1024) or not (0 < reading_count < 5000):
                return {"fans": [], "status": "hwinfo_invalid", "fps": 0.0, "cpu_temp": None, "cpu_power": None, "gpu_temp": None}
            self._hwinfo_stale_reads = self._hwinfo_stale_reads + 1 if poll == self._hwinfo_last_poll else 0
            self._hwinfo_last_poll = poll
            if self._hwinfo_stale_reads >= 4:
                return {"fans": [], "status": "hwinfo_restart", "fps": 0.0, "cpu_temp": None, "cpu_power": None, "gpu_temp": None}
            memory = ctypes.string_at(address + readings_offset, reading_count * reading_size)
            fans = []
            fps_candidates = []
            hwinfo_cpu_temp = None
            hwinfo_cpu_power = None
            hwinfo_gpu_temp = None

            for index in range(reading_count):
                chunk = memory[index * reading_size:(index + 1) * reading_size]
                reading_type = struct.unpack_from("<I", chunk, 0)[0]
                original = chunk[12:140].split(b"\0", 1)[0].decode("utf-8", "ignore")
                user = chunk[140:268].split(b"\0", 1)[0].decode("utf-8", "ignore")
                unit = chunk[268:284].split(b"\0", 1)[0].decode("ascii", "ignore")
                value = struct.unpack_from("<d", chunk, 284)[0]
                name_lower = (user or original).lower()

                if reading_type == 3:
                    if value > 0:
                        fans.append({"name": user or original or "Fan", "rpm": max(0.0, value), "hardware": "HWiNFO"})
                elif reading_type == 1:
                    if 0 < value < 150:
                        if "cpu" in name_lower and ("tctl" in name_lower or "tdie" in name_lower):
                            hwinfo_cpu_temp = value
                        elif hwinfo_cpu_temp is None and "cpu" in name_lower and ("package" in name_lower or "die" in name_lower or "core" in name_lower):
                            hwinfo_cpu_temp = value
                        elif "gpu" in name_lower and ("temperature" in name_lower or "temp" in name_lower) and "hot" not in name_lower and "mem" not in name_lower:
                            hwinfo_gpu_temp = value
                elif reading_type == 5:
                    if 0 < value < 500 and "cpu" in name_lower and ("package" in name_lower or "ppt" in name_lower or "power" in name_lower):
                        hwinfo_cpu_power = value
                elif unit.upper() == "FPS" and 0.0 < value < 5000.0:
                    label = original.lower()
                    rank = 0 if label == "framerate" else 1 if "displayed (avg)" in label else 2 if "presented (avg)" in label else 9
                    fps_candidates.append((rank, value))

            fps = min(fps_candidates, default=(99, 0.0), key=lambda item: item[0])[1]
            return {
                "fans": fans,
                "status": "hwinfo",
                "fps": fps,
                "cpu_temp": hwinfo_cpu_temp,
                "cpu_power": hwinfo_cpu_power,
                "gpu_temp": hwinfo_gpu_temp,
            }
        finally:
            k32.UnmapViewOfFile(address)
            k32.CloseHandle(handle)

    def _read_afterburner(self) -> dict:
        """Lee telemetría en tiempo real desde MSI Afterburner (MAHMSharedMemory) sin requerir elevación."""
        k32 = ctypes.windll.kernel32
        k32.OpenFileMappingW.restype = wintypes.HANDLE
        k32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        k32.MapViewOfFile.restype = ctypes.c_void_p
        k32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
        k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]

        handle = k32.OpenFileMappingW(4, False, "MAHMSharedMemory")
        if not handle:
            return {}
        addr = k32.MapViewOfFile(handle, 4, 0, 0, 0)
        if not addr:
            k32.CloseHandle(handle)
            return {}

        res = {}
        try:
            hdr = ctypes.string_at(addr, 32)
            sig, ver, hdr_sz, num_entries, entry_sz, tm = struct.unpack("<IIIIII", hdr[:24])
            if sig != 0x4D41484D:
                return {}
            data = ctypes.string_at(addr + hdr_sz, num_entries * entry_sz)
            for i in range(num_entries):
                chunk = data[i * entry_sz:(i + 1) * entry_sz]
                name = chunk[0:260].split(b"\0", 1)[0].decode("latin1", "ignore").strip()
                val = struct.unpack_from("<f", chunk, 1300)[0]
                if abs(val) < 1000000:
                    res[name] = float(val)
        except Exception:
            pass
        finally:
            k32.UnmapViewOfFile(addr)
            k32.CloseHandle(handle)
        return res
