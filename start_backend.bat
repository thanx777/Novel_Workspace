@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Novel Workspace - Backend

:: ---- Auto port selection ----
set "CHOSEN_PORT="

for %%p in (8000 8001 8002 8003 9000) do (
    if not defined CHOSEN_PORT (
        netstat -ano 2>nul | findstr ":%%p " | findstr "LISTENING" >nul 2>&1
        if errorlevel 1 (
            python -c "import socket; s=socket.socket(); s.bind(('127.0.0.1', %%p)); s.close()" >nul 2>&1
            if not errorlevel 1 (
                set "CHOSEN_PORT=%%p"
                echo   Port %%p is available
            ) else (
                echo   Port %%p is blocked, trying next...
            )
        ) else (
            echo   Port %%p is in use, trying next...
        )
    )
)

if not defined CHOSEN_PORT (
    echo.
    echo [ERROR] No available port found! Tried 8000-8003, 9000
    echo   Please close applications using these ports and retry.
    echo.
    pause
    exit /b 1
)

:: ---- Write port file for frontend ----
echo !CHOSEN_PORT!> "%~dp0backend_port.txt"

echo ============================================
echo   Backend on http://127.0.0.1:!CHOSEN_PORT!
echo ============================================

cd /d "%~dp0backend"
set AUTH_DISABLED=true
python -m uvicorn main:app --host 127.0.0.1 --port !CHOSEN_PORT!

if errorlevel 1 (
    echo.
    echo [ERROR] Backend failed!
    echo   1) Port is in use
    echo   2) main.py has import/syntax errors
    echo   3) Missing dependencies: pip install -r requirements.txt
    echo.
)
echo.
echo Window closes in 10s...
timeout /t 10 /nobreak
