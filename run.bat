@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Setting up Lookup...
  python -m venv .venv
  if errorlevel 1 (
    echo Python is required. Install it from python.org, then run this again.
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Could not install the app.
    pause
    exit /b 1
  )
)

start "" ".venv\Scripts\pythonw.exe" "%~dp0main.py"
