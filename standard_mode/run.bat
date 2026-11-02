@echo off 
cd /d "%~dp0" 
echo ============================================ 
echo   Lemon Code - TRAE Competition Demo 
echo ============================================ 
echo. 
python --version >nul 2>&1 
if errorlevel 1 ( 
    echo [ERROR] Python not found! 
    echo Please install Python 3.10+ from: 
    echo https://www.python.org/downloads/ 
    echo. 
    echo IMPORTANT: Check "Add Python to PATH" during install! 
    pause 
    exit /b 1 
) 
 
echo [Step 1/3] Creating virtual environment... 
python -m venv .venv 
 
echo [Step 2/3] Installing dependencies... 
.venv\Scripts\pip install -r requirements.txt -q 
 
echo [Step 3/3] Starting Lemon Code... 
.venv\Scripts\python main.py 
pause 
