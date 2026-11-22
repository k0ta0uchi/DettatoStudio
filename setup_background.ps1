# Hidden background setup: venv作成 + pip install（ログ: setup.log）
$ErrorActionPreference = "Continue"
Set-Location "J:\dettato-gui"
Start-Transcript -Path "J:\dettato-gui\setup.log" -Force
Write-Output "=== setup start $(Get-Date) ==="
if (-not (Test-Path "venv")) {
  python -m venv venv
  Write-Output "venv created"
}
& ".\venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\venv\Scripts\python.exe" -m pip install -r requirements.txt
Write-Output "=== setup done $(Get-Date) ==="
& ".\venv\Scripts\python.exe" -c "import PySide6, numpy, soundfile, mido; print('IMPORT OK')"
try { & ".\venv\Scripts\python.exe" -c "import dettato; print('DETTATO OK')" } catch { Write-Output "dettato import check failed (log参照)" }
Stop-Transcript
