# WidgetOSD

Overlay para Windows con telemetría de hardware y estado de cuotas de servicios configurados. La aplicación no inventa datos: cuando una credencial falta, caduca o un servicio no expone una cuota, lo muestra como no disponible.

## Funciones

- Tres estilos: Bento Glass, Cyberpunk HUD y Minimalist Compact.
- Modos `all`, `quotas`, `hardware` y `fps`.
- Escala entre `0.6` y `2.0`.
- Lecturas de CPU, GPU, memoria, ventiladores y FPS cuando existe un sensor compatible.
- Proveedores opcionales: Antigravity, Codex, Claude, Gemini, Copilot, Grok, Cursor, OpenRouter, DeepSeek, Kimi y Perplexity.
- Ventana móvil, bandeja del sistema, refresco manual y configuración persistente.

## Requisitos

- Windows 10/11.
- Python 3.10 o posterior para ejecutar desde fuente.
- .NET Framework 4.x y el compilador C# de Windows para compilar el lector de hardware.
- Credenciales locales de cada proveedor que se quiera consultar. No se incluyen credenciales en el repositorio.

## Instalación desde fuente

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main_v3.py
```

El primer arranque crea o valida `config.json`. Las credenciales se leen de las variables de entorno y de los almacenes locales de cada CLI; no se escriben en el repositorio.

## Compilar el release

Las bibliotecas nativas del lector de hardware están en `vendor/`. El script genera `vendor/HardwareReader.exe`, crea el paquete PyInstaller en `dist/` y no modifica rutas fuera del proyecto.

```powershell
powershell -ExecutionPolicy Bypass -File .\build_v3.ps1
python verify_release.py
```

El lector de hardware puede necesitar permisos elevados para algunos sensores. Si un sensor no está disponible, el widget conserva el estado `sin datos`.

## Proveedores y credenciales

Cada proveedor usa su endpoint o CLI oficial y tiene un intervalo independiente. Las claves se pueden definir en `config.json` o en el entorno, según el proveedor. El registro elimina tokens y claves antes de escribir mensajes.

Para renovar el acceso OAuth de Gemini mediante este proyecto, define `GEMINI_OAUTH_CLIENT_ID` y `GEMINI_OAUTH_CLIENT_SECRET`. Si no están definidas, no se intenta enviar ningún secreto embebido.

## Pruebas

```powershell
python test_ai_providers.py
python test_antigravity_quota.py
python test_core_reliability.py
python test_security.py
python test_widget_behavior.py
python verify_release.py --offline
```

## Licencia

El código de WidgetOSD se distribuye bajo MIT. Las bibliotecas de `vendor/` conservan sus propias licencias; consulta `THIRD_PARTY_NOTICES.md`.
