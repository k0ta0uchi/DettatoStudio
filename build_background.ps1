$ErrorActionPreference = "Continue"
Set-Location "J:\dettato-gui"
Start-Transcript -Path "J:\dettato-gui\build.log" -Force
Write-Output "=== launcher build start $(Get-Date) ==="
if (-not (Test-Path ".build-venv")) { py -m venv .build-venv; Write-Output "build venv created" }
& ".\.build-venv\Scripts\python.exe" -m pip install --upgrade pip pyinstaller
& ".\.build-venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm DettatoStudio.spec
Write-Output "=== launcher build done $(Get-Date) ==="
if (Test-Path "dist\DettatoStudio.exe") { Write-Output "EXE EXISTS"; Get-Item "dist\DettatoStudio.exe" | Select-Object Length,FullName | Out-String }
Stop-Transcript
