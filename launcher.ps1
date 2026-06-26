# CHIP Platform Launcher  (Phase A - standalone, port 8001 only)
# Frontend is served by the main PYCHARTs project (port 5173, /chip-api proxy)
# Run pycharts\launcher.ps1 separately for the full stack.

param()
$ErrorActionPreference = "Continue"

$chipDir    = $PSScriptRoot
$backendDir = Join-Path $chipDir "backend"
$uvExe      = "$env:LOCALAPPDATA\uv\bin\uv.exe"

$env:PATH = "$env:LOCALAPPDATA\uv\bin;" + $env:PATH

Write-Host ""
Write-Host "  ======================================" -ForegroundColor Cyan
Write-Host "   CHIP Platform  |  Project Alpha" -ForegroundColor Cyan
Write-Host "   Backend only   |  port 8001" -ForegroundColor Cyan
Write-Host "   Frontend -> PYCHARTs :5173 (/chip-api)" -ForegroundColor DarkCyan
Write-Host "  ======================================" -ForegroundColor Cyan
Write-Host ""

# ── Check uv ─────────────────────────────────────────────
Write-Host "[1/2] Checking uv..." -NoNewline
if (-not (Test-Path $uvExe)) {
    Write-Host " not found, installing..." -ForegroundColor Yellow
    Invoke-Expression (Invoke-WebRequest -UseBasicParsing "https://astral.sh/uv/install.ps1").Content
    $env:PATH = "$env:LOCALAPPDATA\uv\bin;" + $env:PATH
}
Write-Host " OK" -ForegroundColor Green

# ── Backend deps ──────────────────────────────────────────
Write-Host "[2/2] Backend deps (uv sync)..." -NoNewline
Push-Location $backendDir
$result = & $uvExe sync 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host " FAILED" -ForegroundColor Red
    $result | Write-Host
    Read-Host "Press Enter to exit"
    Pop-Location; exit 1
}
Pop-Location
Write-Host " OK" -ForegroundColor Green

# ── Create required directories ───────────────────────────
foreach ($sub in @("logs", "data", "data\reports")) {
    $d = Join-Path $chipDir $sub
    if (-not (Test-Path $d)) { New-Item -ItemType Directory $d | Out-Null }
}

Write-Host ""
Write-Host "  Launching CHIP backend..." -ForegroundColor Cyan

# ── Start backend supervisor (crash auto-restart) ─────────
$backendSup = Join-Path $backendDir "_supervisor.bat"
Start-Process -FilePath $backendSup -WorkingDirectory $backendDir

Write-Host ""
Write-Host "  ======================================" -ForegroundColor Green
Write-Host "   CHIP backend started" -ForegroundColor Green
Write-Host ""
Write-Host "   API      :  http://localhost:8001" -ForegroundColor Cyan
Write-Host "   Docs     :  http://localhost:8001/docs" -ForegroundColor Cyan
Write-Host "   Chip UI  :  http://localhost:5173  (need PYCHARTs running)" -ForegroundColor Yellow
Write-Host ""
Write-Host "   To start frontend: run pycharts\launcher.ps1" -ForegroundColor DarkYellow
Write-Host "   Crash auto-restart: ON (3 sec delay)" -ForegroundColor Yellow
Write-Host "  ======================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Press any key to close this window..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
