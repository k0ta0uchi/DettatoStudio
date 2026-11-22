@echo off
cd /d %~dp0
if not exist venv (
  echo venv not found. Run setup_venv.bat first.
  pause
  exit /b 1
)
call venv\Scripts\activate.bat
start "" pythonw app.py %*
