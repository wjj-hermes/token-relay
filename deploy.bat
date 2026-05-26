@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo   Token Relay Station
echo ========================================
echo.
echo [1/2] Installing dependencies...
pip install -r requirements.txt -q
echo [2/2] Starting server...
echo.
python main.py
