$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$zip = Join-Path $PSScriptRoot "uv-win.zip"
curl.exe -L -o $zip "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
Expand-Archive -Path $zip -DestinationPath (Join-Path $PSScriptRoot "uv-tmp") -Force
Get-ChildItem (Join-Path $PSScriptRoot "uv-tmp") -Recurse -Filter uv.exe | Select-Object -First 1 | Copy-Item -Destination (Join-Path $PSScriptRoot "uv.exe") -Force
Remove-Item $zip -Force; Remove-Item (Join-Path $PSScriptRoot "uv-tmp") -Recurse -Force
& (Join-Path $PSScriptRoot "uv.exe") --version
