@echo off
chcp 65001 >nul
title CHIP Backend :8001
set "PATH=%LOCALAPPDATA%\uv\bin;%PATH%"
cd /d "%~dp0"

:LOOP
echo.
echo [%date% %time%] Starting CHIP backend (port 8001)...
echo -------------------------------------------------------
uv run uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
set EC=%ERRORLEVEL%
echo.
echo [%date% %time%] Service stopped (exit=%EC%)

if %EC%==0 goto DONE

echo Crash detected. Restarting in 3 seconds...
timeout /t 3 /nobreak >nul
goto LOOP

:DONE
echo Stopped normally. Press any key to close.
pause >nul
