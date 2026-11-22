$ErrorActionPreference = "Stop"
Set-Location "J:\dettato-gui"
$zip = "J:\dettato-gui\uv-win.zip"
curl.exe -L -o $zip "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
Expand-Archive -Path $zip -DestinationPath "J:\dettato-gui\uv-tmp" -Force
Get-ChildItem "J:\dettato-gui\uv-tmp" -Recurse -Filter uv.exe | Select-Object -First 1 | Copy-Item -Destination "J:\dettato-gui\uv.exe" -Force
Remove-Item $zip -Force; Remove-Item "J:\dettato-gui\uv-tmp" -Recurse -Force
& "J:\dettato-gui\uv.exe" --version
