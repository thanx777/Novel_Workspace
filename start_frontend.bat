@echo off
chcp 65001 >nul
cd /d "%~dp0frontend"
echo ============================================
echo   Frontend (vite) on http://localhost:5176
echo ============================================
npm run dev -- --port 5176
if errorlevel 1 (
    echo.
    echo [ERROR] Frontend failed! Possible causes:
    echo   1) Port 5176 is in use
    echo   2) Missing node_modules: npm install
    echo.
)
echo.
echo Window closes in 10s...
timeout /t 10 /nobreak
