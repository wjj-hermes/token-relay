@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   Installing Python 3.8
echo ========================================
echo.

echo [1/3] Downloading Python 3.8...
powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.8.10/python-3.8.10-amd64.exe' -OutFile 'python-installer.exe'"
if not exist "python-installer.exe" (
    echo ERROR: Download failed!
    echo Please download manually from: https://www.python.org/ftp/python/3.8.10/python-3.8.10-amd64.exe
    pause
    exit /b 1
)

echo [2/3] Installing Python 3.8 (silent)...
python-installer.exe /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1
echo Waiting for installation to finish...
timeout /t 60 /nobreak >nul

echo [3/3] Cleaning up...
del python-installer.exe

echo.
echo ========================================
echo   Python installed! Please close this
echo   window and run deploy-server.bat
echo ========================================
pause
