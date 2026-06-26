# CHIP Platform stopper — ONLY kills CHIP backend (port 8001)
# Does NOT touch PYCHARTs main project (ports 8000 / 5173)

$chipDir = $PSScriptRoot   # ...\Project Quant\CHIP\
$killed  = 0

Write-Host ""
Write-Host "  =====================================" -ForegroundColor Cyan
Write-Host "   CHIP Platform - Stop Backend :8001" -ForegroundColor Cyan
Write-Host "   (PYCHARTs main project untouched)" -ForegroundColor DarkCyan
Write-Host "  =====================================" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Kill CHIP supervisor window ───────────────────
Write-Host "  [1/3] Stopping CHIP supervisor window..." -ForegroundColor Yellow
$out = taskkill /F /FI "WINDOWTITLE eq CHIP Backend :8001" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "        'CHIP Backend :8001' stopped" -ForegroundColor Green
    $killed++
} else {
    Write-Host "        (no supervisor window found)" -ForegroundColor DarkGray
}

# Also kill CHIP launcher window if open
$out = taskkill /F /FI "WINDOWTITLE eq CHIP Launcher" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "        'CHIP Launcher' stopped" -ForegroundColor Green
    $killed++
}

Start-Sleep -Milliseconds 800

# ── Step 2: Kill whatever is listening on port 8001 ───────
Write-Host "  [2/3] Freeing port 8001..." -ForegroundColor Yellow
$lines = netstat -ano 2>$null | Select-String "[:.]8001\s+\S+\s+LISTENING"
if (-not $lines) {
    Write-Host "        Port 8001 : already free" -ForegroundColor DarkGray
} else {
    foreach ($line in $lines) {
        $parts    = ($line.ToString().Trim() -split '\s+')
        $ownerPid = [int]$parts[-1]
        if ($ownerPid -le 4) { continue }
        $proc = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
        $name = if ($proc) { $proc.ProcessName } else { "unknown" }
        Write-Host "        Port 8001 : PID $ownerPid ($name)  " -NoNewline
        $out = taskkill /F /PID $ownerPid /T 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "killed" -ForegroundColor Green; $killed++
        } else {
            Write-Host "FAILED" -ForegroundColor Red
        }
    }
}

Start-Sleep -Milliseconds 500

# ── Step 3: Orphaned CHIP python processes ────────────────
# Only matches processes whose command line contains the CHIP backend path
Write-Host "  [3/3] Checking for orphaned CHIP processes..." -ForegroundColor Yellow
$chipBackendPath = (Join-Path $chipDir "backend").ToLower()
$orphans = Get-WmiObject Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -match "python|uvicorn" -and
        $_.CommandLine -and
        $_.CommandLine.ToLower() -like "*$chipBackendPath*"
    }
if ($orphans) {
    foreach ($p in $orphans) {
        Write-Host "        Orphan PID $($p.ProcessId) ($($p.Name))  " -NoNewline
        $out = taskkill /F /PID $p.ProcessId /T 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "killed" -ForegroundColor Green; $killed++
        } else {
            Write-Host "FAILED" -ForegroundColor Red
        }
    }
} else {
    Write-Host "        None found" -ForegroundColor DarkGray
}

# ── Verify ────────────────────────────────────────────────
Start-Sleep -Seconds 2
Write-Host ""
$stillBusy = netstat -ano 2>$null | Select-String "[:.]8001\s+\S+\s+LISTENING"
if (-not $stillBusy) {
    Write-Host "  Port 8001 is free. $killed process(es) stopped." -ForegroundColor Green
    Write-Host "  Safe to run launcher.ps1 now." -ForegroundColor DarkGreen
} else {
    Write-Host "  Port 8001 still occupied." -ForegroundColor Red
    Write-Host "  Try running as Administrator." -ForegroundColor DarkYellow
}

Write-Host ""
Write-Host "  Press any key to close..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
