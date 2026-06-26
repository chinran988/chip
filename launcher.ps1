# CHIP Platform Launcher  (Project Alpha, port 8001 only)
# Frontend is served by the main PYCHARTs project (port 5173, /chip-api proxy)
# Run pycharts\launcher.ps1 separately for the full stack.

param()
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding           = [System.Text.Encoding]::UTF8
$ErrorActionPreference    = "Continue"

$chipDir    = $PSScriptRoot
$backendDir = Join-Path $chipDir "backend"
$uvExe      = "$env:LOCALAPPDATA\uv\bin\uv.exe"
$env:PATH   = "$env:LOCALAPPDATA\uv\bin;" + $env:PATH

Write-Host ""
Write-Host "  ============================================" -ForegroundColor Cyan
Write-Host "   CHIP Platform  |  Project Alpha" -ForegroundColor Cyan
Write-Host "   Backend only   |  port 8001" -ForegroundColor Cyan
Write-Host "   Frontend -> PYCHARTs :5173 (/chip-api)" -ForegroundColor DarkCyan
Write-Host "  ============================================" -ForegroundColor Cyan
Write-Host ""

# ── [1/3] uv ─────────────────────────────────────────────────
Write-Host "  [1/3] Checking uv..." -NoNewline
if (-not (Test-Path $uvExe)) {
    Write-Host "  not found, downloading..." -ForegroundColor Yellow
    Invoke-Expression (Invoke-WebRequest -UseBasicParsing "https://astral.sh/uv/install.ps1").Content
    $env:PATH = "$env:LOCALAPPDATA\uv\bin;" + $env:PATH
    if (-not (Test-Path $uvExe)) {
        Write-Host "  INSTALL FAILED — install manually from https://astral.sh/uv" -ForegroundColor Red
        Read-Host "Press Enter to exit"; exit 1
    }
}
$uvVer = (& $uvExe --version 2>&1) -replace "uv ", ""
Write-Host ("  found  ({0}  at {1})" -f $uvVer.Trim(), $uvExe) -ForegroundColor Green

# ── [2/3] Backend venv + deps ─────────────────────────────────
Write-Host "  [2/3] Backend venv + deps (uv sync)..." -NoNewline
Push-Location $backendDir
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "  creating .venv..." -ForegroundColor Yellow
    & $uvExe venv 2>&1 | Out-Null
}
$syncOut = & $uvExe sync 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  FAILED" -ForegroundColor Red
    $syncOut | ForEach-Object { Write-Host "        $_" -ForegroundColor Red }
    Pop-Location; Read-Host "Press Enter to exit"; exit 1
}
$pyVer = (& ".venv\Scripts\python.exe" --version 2>&1)
Pop-Location
Write-Host ("  OK  ({0}  at backend\.venv\Scripts\python.exe)" -f $pyVer.Trim()) -ForegroundColor Green

# ── [3/3] Directories ─────────────────────────────────────────
Write-Host "  [3/3] Creating data directories..." -NoNewline
$dirs = @("logs", "data", "data\reports")
$created = 0
foreach ($sub in $dirs) {
    $d = Join-Path $chipDir $sub
    if (-not (Test-Path $d)) { New-Item -ItemType Directory $d | Out-Null; $created++ }
}
if ($created -gt 0) {
    Write-Host ("  created {0} dir(s)" -f $created) -ForegroundColor Yellow
} else {
    Write-Host "  OK  (already exist)" -ForegroundColor Green
}

# ── Launch ────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ============================================" -ForegroundColor Cyan
Write-Host "   Starting CHIP backend supervisor..." -ForegroundColor Cyan
Write-Host "   Crash auto-restart: ON (3 sec delay)" -ForegroundColor DarkCyan
Write-Host "   Close the 'CHIP Backend :8001' window to stop." -ForegroundColor Yellow
Write-Host "  ============================================" -ForegroundColor Cyan
Write-Host ""

$backendSup = Join-Path $backendDir "_supervisor.bat"
Start-Process -FilePath $backendSup -WorkingDirectory $backendDir

Start-Sleep -Milliseconds 1500

Write-Host "  ============================================" -ForegroundColor Green
Write-Host "   CHIP backend started" -ForegroundColor Green
Write-Host ""
Write-Host "   API   :  http://localhost:8001"      -ForegroundColor Cyan
Write-Host "   Docs  :  http://localhost:8001/docs"  -ForegroundColor Cyan
Write-Host "   UI    :  http://localhost:5173  (need PYCHARTs running)" -ForegroundColor Yellow
Write-Host ""
Write-Host "   To start frontend : run pycharts\啟動.bat" -ForegroundColor DarkYellow
Write-Host "   To stop all       : run CHIP\結束.bat"     -ForegroundColor DarkYellow
Write-Host "  ============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Press any key to close this window..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
