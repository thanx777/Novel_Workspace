@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
echo ============================================
echo   Backend (uvicorn) on http://127.0.0.1:8000
echo ============================================
python -m uvicorn main:app --host 127.0.0.1 --port 8000
if errorlevel 1 (
    echo.
    echo [ERROR] Backend failed! Possible causes:
    echo   1) Port 8000 is in use
    echo   2) main.py has import/syntax errors
    echo   3) Missing dependencies: pip install -r requirements.txt
    echo.
)
echo.
echo Window closes in 10s...
timeout /t 10 /nobreak
