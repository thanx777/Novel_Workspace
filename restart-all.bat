@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Novel Workspace - Restart All

echo ============================================
echo   Restart Novel Workspace
echo ============================================

:: ---- Step 1: Kill old processes ----
echo [1/3] Stopping old services...

for %%p in (8000 8001 8002 8003 9000 5173 5174 5175 5176 5177) do (
    for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%%p " ^| findstr "LISTENING"') do (
        echo   Kill PID %%a on port %%p
        taskkill /F /PID %%a >nul 2>&1
    )
)

:: ---- Step 2: Wait ----
echo [2/3] Waiting 5s for ports to release...
timeout /t 5 /nobreak >nul

:: ---- Step 3: Start services ----
echo [3/3] Starting services...

start "NovelWorkspace-Backend" "%~dp0start_backend.bat"

timeout /t 6 /nobreak >nul

:: Read actual backend port
set "BACKEND_PORT=8000"
if exist "%~dp0backend_port.txt" (
    set /p BACKEND_PORT=<"%~dp0backend_port.txt"
)

start "NovelWorkspace-Frontend" "%~dp0start_frontend.bat"

echo.
echo ============================================
echo   Backend  : http://127.0.0.1:!BACKEND_PORT!
echo   Frontend : http://localhost:5176
echo ============================================
echo.
pause
endlocal
