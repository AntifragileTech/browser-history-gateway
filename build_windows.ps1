# Created: 21:55 27-Apr-2026
# Build Browser-History-Gateway.exe as a single-file PyInstaller bundle.
#
# Run from the repo root in PowerShell:
#   .\build_windows.ps1
#
# Output: dist\Browser-History-Gateway.exe
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "==> Cleaning previous builds"
if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist)  { Remove-Item -Recurse -Force dist  }
if (Test-Path "Browser-History-Gateway.spec") { Remove-Item -Force "Browser-History-Gateway.spec" }

Write-Host "==> Resolving Python"
$python = (Get-Command python -ErrorAction Stop).Source
Write-Host "    using $python"

# PyInstaller bundles need every dynamic-import target listed via
# --hidden-import, plus the resource files via --add-data (semicolon
# separator on Windows: source;dest).
$hidden = @(
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "anyio._backends",
    "anyio._backends._asyncio",
    "watchdog.observers",
    "watchdog.observers.read_directory_changes",
    "watchdog.observers.api",
    "fastapi",
    "starlette",
    "jinja2",
    "pystray._win32",
    "pkg_resources.py2_warn",
    "collector.chromium",
    "collector.firefox",
    "collector.safari",
    "collector.run",
    "collector.state",
    "collector.paths",
    "web.app"
)
$hiddenArgs = $hidden | ForEach-Object { "--hidden-import=$_" }

Write-Host "==> Running PyInstaller"
$pyiArgs = @(
    "--noconfirm",
    "--clean",
    "--onefile",
    "--noconsole",
    "--name", "Browser-History-Gateway",
    "--add-data", "schema.sql;.",
    "--add-data", "web/templates;web/templates",
    "--add-data", "assets/menubar_template.png;assets",
    "--add-data", "assets/menubar_template@2x.png;assets",
    "--add-data", "assets/logo.png;assets"
)
# Optional Windows .ico for the EXE — falls back to PyInstaller default if missing.
if (Test-Path "assets/AppIcon.ico") {
    $pyiArgs += @("--icon", "assets/AppIcon.ico")
}
$pyiArgs += $hiddenArgs
$pyiArgs += "app/__main__.py"

& $python -m PyInstaller @pyiArgs

if (-Not (Test-Path "dist/Browser-History-Gateway.exe")) {
    throw "PyInstaller did not produce dist/Browser-History-Gateway.exe"
}

$size = (Get-Item "dist/Browser-History-Gateway.exe").Length / 1MB
Write-Host ""
Write-Host "================================================================"
Write-Host "  Build complete."
Write-Host "  EXE:  dist\Browser-History-Gateway.exe  ($([math]::Round($size,1)) MB)"
Write-Host ""
Write-Host "  Distribute by sharing the EXE directly. On first launch"
Write-Host "  Windows SmartScreen will warn (publisher unknown — the"
Write-Host "  binary is unsigned). Click 'More info' -> 'Run anyway'."
Write-Host "================================================================"
