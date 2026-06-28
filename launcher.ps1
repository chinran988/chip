# CHIP 籌碼情報平台 啟動器  (Project Alpha，僅後端 port 8001)
# 前端由主專案 PYCHARTs 提供（port 5173，/chip-api proxy）
# 請先啟動主專案 pycharts\啟動.bat，再執行本腳本。

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
Write-Host "   CHIP 籌碼情報平台  |  Project Alpha" -ForegroundColor Cyan
Write-Host "   僅後端             |  port 8001" -ForegroundColor Cyan
Write-Host "   前端 -> PYCHARTs :5173 (/chip-api)" -ForegroundColor DarkCyan
Write-Host "  ============================================" -ForegroundColor Cyan
Write-Host ""

# ── [1/3] uv 套件管理器 ──────────────────────────────────────
Write-Host "  [1/3] 檢查 uv 套件管理器..." -NoNewline
if (-not (Test-Path $uvExe)) {
    Write-Host "  未安裝，自動下載中..." -ForegroundColor Yellow
    Invoke-Expression (Invoke-WebRequest -UseBasicParsing "https://astral.sh/uv/install.ps1").Content
    $env:PATH = "$env:LOCALAPPDATA\uv\bin;" + $env:PATH
    if (-not (Test-Path $uvExe)) {
        Write-Host "  安裝失敗，請手動安裝：https://astral.sh/uv" -ForegroundColor Red
        Read-Host "按 Enter 關閉"; exit 1
    }
}
$uvVer = (& $uvExe --version 2>&1) -replace "uv ", ""
Write-Host ("  已就緒  ({0}  路徑：{1})" -f $uvVer.Trim(), $uvExe) -ForegroundColor Green

# ── [2/3] 後端虛擬環境 + 依賴 ───────────────────────────────
Write-Host "  [2/3] 後端虛擬環境 + 依賴套件（uv sync）..." -NoNewline
Push-Location $backendDir
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "  建立虛擬環境中..." -ForegroundColor Yellow
    & $uvExe venv 2>&1 | Out-Null
}
$syncOut = & $uvExe sync 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  失敗" -ForegroundColor Red
    $syncOut | ForEach-Object { Write-Host "        $_" -ForegroundColor Red }
    Pop-Location; Read-Host "按 Enter 關閉"; exit 1
}
$pyVer = (& ".venv\Scripts\python.exe" --version 2>&1)
Pop-Location
Write-Host ("  完成  ({0}  虛擬環境：backend\.venv\)" -f $pyVer.Trim()) -ForegroundColor Green

# ── [3/3] 資料目錄 ───────────────────────────────────────────
Write-Host "  [3/3] 確認資料目錄..." -NoNewline
$dirs    = @("logs", "data", "data\reports")
$created = 0
foreach ($sub in $dirs) {
    $d = Join-Path $chipDir $sub
    if (-not (Test-Path $d)) { New-Item -ItemType Directory $d | Out-Null; $created++ }
}
if ($created -gt 0) {
    Write-Host ("  已建立 {0} 個目錄" -f $created) -ForegroundColor Yellow
} else {
    Write-Host "  已存在" -ForegroundColor Green
}

# ── 啟動後端 Supervisor ──────────────────────────────────────
Write-Host ""
Write-Host "  ============================================" -ForegroundColor Cyan
Write-Host "   啟動後端服務（supervisor 自動重啟）..." -ForegroundColor Cyan
Write-Host "   關閉「CHIP 後端 :8001」視窗可停止服務。" -ForegroundColor Yellow
Write-Host "  ============================================" -ForegroundColor Cyan
Write-Host ""

$backendSup = Join-Path $backendDir "_supervisor.bat"
Start-Process -FilePath $backendSup -WorkingDirectory $backendDir

Start-Sleep -Milliseconds 1500

Write-Host "  ============================================" -ForegroundColor Green
Write-Host "   CHIP 後端已啟動" -ForegroundColor Green
Write-Host ""
Write-Host "   API 文件  :  http://localhost:8001/docs"  -ForegroundColor Cyan
Write-Host "   籌碼 UI   :  http://localhost:5173  （需先啟動 PYCHARTs）" -ForegroundColor Yellow
Write-Host ""
Write-Host "   啟動主專案  :  執行 pycharts\啟動.bat"  -ForegroundColor DarkYellow
Write-Host "   停止本服務  :  執行 CHIP\結束.bat"       -ForegroundColor DarkYellow
Write-Host "  ============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  按任意鍵關閉此視窗..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
