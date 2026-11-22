@echo off
cd /d %~dp0
echo === Build launcher exe (PyInstaller onefile, windowed, stdlib only) ===
if not exist .build-venv (
  echo Creating build venv...
  py -m venv .build-venv
)
call .build-venv\Scripts\activate.bat
pip install pyinstaller
pyinstaller --clean --noconfirm DettatoStudio.spec
echo.
echo Done: dist\DettatoStudio.exe  (put it next to uv.exe, app.py, requirements.txt)
pause
