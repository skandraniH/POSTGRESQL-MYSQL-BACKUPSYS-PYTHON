@echo off
:: Get the current directory path
set "current_dir=%cd%"

:: Check if already running as admin
net session >nul 2>&1
if %errorLevel% == 0 (
    echo Already running as admin, launching app...
    cd /d "%current_dir%"
    python app.py
    pause
    exit /b
)

:: If not admin, relaunch with UAC prompt
echo Requesting administrator privileges...
powershell -Command "Start-Process cmd -ArgumentList '/k cd /d \"%current_dir%\" && python app.py' -Verb RunAs"