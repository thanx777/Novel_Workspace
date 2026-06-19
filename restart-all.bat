@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Novel Workspace - Restart All

echo ============================================
echo   Restart Novel Workspace (Backend + Frontend)
echo ============================================

:: ---- Step 1: Kill all related processes ----
echo [1/3] Stopping old services...
for %%p in (8000 5173 5174 5175 5176 5177) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%p " ^| findstr "LISTENING" 2^>nul') do (
        echo   Kill PID %%a on port %%p
        taskkill /F /PID %%a >nul 2>&1
    )
)

:: ---- Step 2: Fixed wait for ports to release ----
echo [2/3] Waiting 5s for ports to release...
timeout /t 5 /nobreak >nul

:: ---- Step 3: Start services ----
echo [3/3] Starting services...

start "NovelWorkspace-Backend" cmd /c "cd /d "%~dp0backend" && set AUTH_DISABLED=true&& chcp 65001 >nul && echo ============================================ && echo   Backend (uvicorn) on http://127.0.0.1:8000 && echo ============================================ && python -m uvicorn main:app --host 127.0.0.1 --port 8000"

ping -n 3 127.0.0.1 >nul

start "NovelWorkspace-Frontend" cmd /c "cd /d "%~dp0frontend" && chcp 65001 >nul && echo ============================================ && echo   Frontend (vite) on http://localhost:5176 && echo ============================================ && npm run dev -- --port 5176"

echo.
echo ============================================
echo   Backend  : http://127.0.0.1:8000
echo   Frontend : http://localhost:5176
echo ============================================
echo.
echo This window closes in 5s...
timeout /t 5 /nobreak >nul
endlocal
