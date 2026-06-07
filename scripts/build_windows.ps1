# 在 Windows 上打包 DPT 为单文件 .exe
# 用法: powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Root "main.py"))) {
    $Root = Get-Location
}
Set-Location $Root
Write-Host "Project root: $Root"

python -m pip install -r requirements-build.txt

if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }

python -m PyInstaller --noconfirm DPT.spec

$exe = Get-ChildItem -Path "dist" -Filter "*.exe" | Select-Object -First 1
if ($exe) {
    Write-Host ""
    Write-Host "Build OK: $($exe.FullName)"
    Write-Host "Size: $([math]::Round($exe.Length / 1MB, 1)) MB"
} else {
    Write-Error "dist\*.exe not found"
    exit 1
}
