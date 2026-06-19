@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Novel Workspace - Stop All

echo ============================================
echo   Stop Novel Workspace
echo ============================================

for %%p in (8000 5173 5174 5175 5176 5177) do (
    echo Looking for port %%p...
    set FOUND=0
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%p " ^| findstr "LISTENING" 2^>nul') do (
        set /a FOUND+=1
        echo   Killing PID: %%a
        taskkill /F /PID %%a >nul 2>&1
    )
    if !FOUND! equ 0 echo   Not running
)

echo.
echo ============================================
echo   Done
echo ============================================
pause
