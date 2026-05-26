@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   Token Relay Station - Deploy
echo ========================================
echo.

echo [1/5] Checking Python...
python --version
if errorlevel 1 (
    echo ERROR: Python not found!
    pause
    exit /b 1
)

echo [2/5] Checking pip...
python -m pip --version >nul 2>&1
if errorlevel 1 (
    echo pip not found, installing...
    python get-pip.py
    if errorlevel 1 (
        echo ERROR: Failed to install pip!
        pause
        exit /b 1
    )
)

echo [3/5] Creating data directory...
if not exist "data" mkdir data

echo [4/5] Installing dependencies...
python -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo ERROR: pip install failed!
    pause
    exit /b 1
)

echo [5/5] Setting environment variables...
set JWT_SECRET=tr-secret-%RANDOM%%RANDOM%%RANDOM%
set ADMIN_USERNAME=admin
set ADMIN_PASSWORD=Wj123321

echo.
echo ========================================
echo   All done! Starting server...
echo   Admin login: admin / Wj123321
echo   Open browser: http://103.217.186.144:8888
echo ========================================
echo.

netsh advfirewall firewall add rule name="TokenRelay" dir=in action=allow protocol=TCP localport=8888

python main.py
