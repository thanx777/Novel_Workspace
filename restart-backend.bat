@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title OmniAgent Hub - Restart

echo ============================================
echo   Restart OmniAgent Hub
echo ============================================

:: ---- Step 1: Kill old processes ----
echo [1/2] Stopping old services...
for %%p in (8000 5173 5174 5175 5176 5177) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%p" ^| findstr "LISTENING" 2^>nul') do (
        echo   Kill PID %%a (port %%p)
        taskkill /F /PID %%a >nul 2>&1
    )
)
echo   Waiting for ports to release...
ping -n 4 127.0.0.1 >nul

:: ---- Step 2: Start services ----
echo [2/2] Starting services...

start "Backend-8000"  "%~dp0start_backend.bat"
start "Frontend-5176" "%~dp0start_frontend.bat"

echo.
echo ============================================
echo   Backend  : http://127.0.0.1:8000
echo   Frontend : http://localhost:5176
echo ============================================
echo.
echo This window closes in 5s...
timeout /t 5 /nobreak >nul
endlocal
