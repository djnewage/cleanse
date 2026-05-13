#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

# Build the Python backend into a standalone executable using PyInstaller.
# Output: backend\dist\cleanse-backend\  (one-dir bundle, cleanse-backend.exe inside)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$BackendDir = Join-Path $ProjectRoot 'backend'

Write-Host '==> Building Python backend with PyInstaller...'

Push-Location $BackendDir
try {
    $VenvDir = Join-Path $BackendDir 'venv'
    if (-not (Test-Path $VenvDir)) {
        Write-Error 'backend\venv not found. Run scripts\setup-python.ps1 first.'
        exit 1
    }

    $Pip = Join-Path $VenvDir 'Scripts\pip.exe'
    $Python = Join-Path $VenvDir 'Scripts\python.exe'

    & $Pip install pyinstaller --quiet

    $DistBackend = Join-Path $BackendDir 'dist\cleanse-backend'
    $BuildBackend = Join-Path $BackendDir 'build\cleanse-backend'
    if (Test-Path $DistBackend) { Remove-Item -Recurse -Force $DistBackend }
    if (Test-Path $BuildBackend) { Remove-Item -Recurse -Force $BuildBackend }

    & $Python -m PyInstaller cleanse-backend.spec --noconfirm

    Write-Host '==> Backend built successfully: backend\dist\cleanse-backend\'
    Write-Host '==> Test with: backend\dist\cleanse-backend\cleanse-backend.exe --port 8765'
}
finally {
    Pop-Location
}
