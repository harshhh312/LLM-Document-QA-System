@echo off
setlocal enabledelayedexpansion
title NexusDoc AI Startup

echo ============================================================
echo NexusDoc AI - Chat ^& Insights App Startup Script (Windows)
echo ============================================================
echo.

:: 1. Check Python installation
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in your system PATH.
    echo Please download and install Python 3.8+ from https://www.python.org/
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

:: 2. Check if Ollama is running
echo Checking Ollama status...
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe" >NUL
if %errorlevel% equ 0 (
    echo [OK] Ollama is already running.
) else (
    echo [WARNING] Ollama is not running in the background.
    echo Attempting to launch Ollama automatically...
    start "" ollama >nul 2>&1
    if %errorlevel% neq 0 (
        echo [WARNING] Could not start Ollama automatically.
        echo Please ensure Ollama is installed and running manually.
    ) else (
        echo [OK] Ollama started. Waiting 3 seconds for it to initialize...
        timeout /t 3 >nul
    )
)

:: 3. Install/upgrade Python dependencies
echo.
echo Installing and verifying dependencies from requirements.txt...
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [WARNING] pip command failed. Attempting with standard python pip execution...
    python -m pip install --user -r requirements.txt
)

:: 4. Start the backend server
echo.
echo ============================================================
echo Starting NexusDoc AI RAG server...
echo Access the application web interface at: http://localhost:8000
echo ============================================================
echo.
python run.py

pause
