$ErrorActionPreference = "Stop"

$ProjectDir = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$OutputDir = Join-Path $ProjectDir "dist"
$BuildDir = Join-Path $OutputDir "_build"
$VendorDir = Join-Path $ProjectDir "vendor"
$HardwareReader = Join-Path $VendorDir "HardwareReader.exe"
$HardwareDllNames = @(
    "BlackSharp.Core.dll",
    "DiskInfoToolkit.dll",
    "HidSharp.dll",
    "LibreHardwareMonitorLib.dll",
    "RAMSPDToolkit-NDD.dll",
    "System.Buffers.dll",
    "System.Memory.dll",
    "System.Numerics.Vectors.dll",
    "System.Runtime.CompilerServices.Unsafe.dll"
)

Set-Location -LiteralPath $ProjectDir

foreach ($name in $HardwareDllNames) {
    $path = Join-Path $VendorDir $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Falta dependencia de hardware: $path"
    }
}

# Fail before touching the output directory if behavioral regressions fail.
python verify_release.py --offline
if ($LASTEXITCODE -ne 0) { throw "Fallo la verificacion previa." }

Write-Host "Compilando WidgetOSD..." -ForegroundColor Cyan

$ReleaseExe = Join-Path $OutputDir "WidgetOSD_v3\WidgetOSD_v3.exe"
if (Test-Path -LiteralPath $ReleaseExe) {
    & $ReleaseExe --kill
    for ($i = 0; $i -lt 30 -and (Get-Process WidgetOSD_v3 -ErrorAction SilentlyContinue); $i++) {
        Start-Sleep -Milliseconds 100
    }
}
Get-Process WidgetOSD_v3 -ErrorAction SilentlyContinue | Stop-Process -Force

$CscPath = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path -LiteralPath $CscPath -PathType Leaf)) {
    throw "No se encontró el compilador C# de .NET Framework: $CscPath"
}

$LhmReference = "/reference:$(Join-Path $VendorDir 'LibreHardwareMonitorLib.dll')"
& $CscPath /optimize /platform:x64 "/out:$HardwareReader" `
    $LhmReference `
    "/reference:System.Web.Extensions.dll" `
    (Join-Path $ProjectDir "HardwareReader.cs")
if ($LASTEXITCODE -ne 0) { throw "Falló la compilación de HardwareReader.exe" }

$PyInstallerArgs = @(
    "-m", "PyInstaller", "--noconfirm", "--noconsole",
    "--icon=$(Join-Path $ProjectDir 'app_icon.ico')",
    "--name", "WidgetOSD_v3",
    "--add-data", "$(Join-Path $ProjectDir 'config.json');.",
    "--add-data", "$HardwareReader;hardware",
    "--add-data", "$(Join-Path $ProjectDir 'app_icon.ico');.",
    "--hidden-import=keyring.backends.Windows",
    "--hidden-import=keyring",
    "--hidden-import=pydantic",
    "--distpath", $OutputDir,
    "--workpath", $BuildDir,
    "--specpath", $BuildDir,
    "--clean"
)
foreach ($name in $HardwareDllNames) {
    $PyInstallerArgs += "--add-data"
    $PyInstallerArgs += "$(Join-Path $VendorDir $name);hardware"
}

& python @PyInstallerArgs (Join-Path $ProjectDir "main_v3.py")
if ($LASTEXITCODE -ne 0) { throw "Falló PyInstaller ($LASTEXITCODE)" }

# Qt no debe cargar ICU de Poppler si este está disponible en PATH.
$InternalDir = Join-Path $OutputDir "WidgetOSD_v3\_internal"
Remove-Item -LiteralPath (Join-Path $InternalDir "icuuc.dll") -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $InternalDir "icudt78.dll") -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $BuildDir -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "Release generado en: $(Join-Path $OutputDir 'WidgetOSD_v3\WidgetOSD_v3.exe')" -ForegroundColor Green
