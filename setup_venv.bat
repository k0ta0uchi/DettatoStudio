@echo off
cd /d %~dp0
echo === Dettato Studio setup (venv) ===
where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Install Python 3.10+ from https://www.python.org/downloads/
  pause
  exit /b 1
)
python --version
if not exist venv (
  echo Creating venv...
  python -m venv venv
)
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
echo Installing dependencies (torch + dettato, first time takes a while)...
pip install -r requirements.txt
echo.
echo Done. Run run.bat to start.
pause
