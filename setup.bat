@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   Token Relay - One-Click Setup
echo ========================================
echo.

REM === Step 1: Check Python ===
python --version >nul 2>&1
if errorlevel 1 (
    echo [!] Python not found.
    echo.
    echo Please install Python 3.8 first:
    echo   Download: https://www.python.org/ftp/python/3.8.10/python-3.8.10-amd64.exe
    echo   IMPORTANT: Check "Add Python 3.8 to PATH" during install!
    echo.
    echo After install, close this window and run setup.bat again.
    pause
    exit /b 1
)

echo [OK] Python found:
python --version
echo.

REM === Step 2: Install pip if missing ===
python -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [!] pip not found, installing...
    python get-pip.py
    if errorlevel 1 (
        echo [X] Failed to install pip!
        pause
        exit /b 1
    )
    echo [OK] pip installed.
)
echo.

REM === Step 3: Install dependencies ===
echo Installing dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [X] Failed to install dependencies!
    pause
    exit /b 1
)
echo [OK] Dependencies installed.
echo.

REM === Step 4: Create data dir ===
if not exist "data" mkdir data

REM === Step 5: Open firewall ===
echo Opening firewall port 8888...
netsh advfirewall firewall add rule name="TokenRelay" dir=in action=allow protocol=TCP localport=8888 >nul 2>&1
echo [OK] Firewall configured.
echo.

REM === Step 6: Set env vars and start ===
set JWT_SECRET=tr-%RANDOM%%RANDOM%%RANDOM%
set ADMIN_USERNAME=admin
set ADMIN_PASSWORD=Wj123321

echo ========================================
echo   Setup complete! Starting server...
echo.
echo   URL:    http://103.217.186.144:8888
echo   Admin:  admin / Wj123321
echo ========================================
echo.

python main.py
pause
