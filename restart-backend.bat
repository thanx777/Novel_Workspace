@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Novel Workspace - Restart Backend

echo ============================================
echo   Restart Novel Workspace (Backend Only)
echo ============================================

:: ---- Step 1: Kill old backend ----
echo [1/2] Stopping old backend...

for %%p in (8000 8001 8002 8003 9000) do (
    for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%%p " ^| findstr "LISTENING"') do (
        echo   Kill PID %%a on port %%p
        taskkill /F /PID %%a >nul 2>&1
    )
)

echo   Waiting for ports to release...
timeout /t 5 /nobreak >nul

:: ---- Step 2: Start backend ----
echo [2/2] Starting backend...

start "NovelWorkspace-Backend" "%~dp0start_backend.bat"

timeout /t 6 /nobreak >nul

set "BACKEND_PORT=8000"
if exist "%~dp0backend_port.txt" (
    set /p BACKEND_PORT=<"%~dp0backend_port.txt"
)

echo.
echo ============================================
echo   Backend  : http://127.0.0.1:!BACKEND_PORT!
echo ============================================
echo.
pause
endlocal
