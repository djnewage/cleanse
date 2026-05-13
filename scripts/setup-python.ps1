#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$BackendDir = Join-Path $ProjectDir 'backend'

Write-Host '=== Cleanse - Python Backend Setup ==='

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    $python = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $python) {
    Write-Error 'python not found. Install Python 3.10+ from https://www.python.org/downloads/ (or winget install Python.Python.3.11).'
    exit 1
}
$PythonExe = $python.Source

$pyVer = & $PythonExe -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
Write-Host "Found Python $pyVer"

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Warning 'ffmpeg not found on PATH. static-ffmpeg will fetch a bundled copy on first run, but a system install is recommended (winget install Gyan.FFmpeg).'
}

$VenvDir = Join-Path $BackendDir 'venv'
if (-not (Test-Path $VenvDir)) {
    Write-Host 'Creating virtual environment...'
    & $PythonExe -m venv $VenvDir
} else {
    Write-Host 'Virtual environment already exists.'
}

$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$VenvPip = Join-Path $VenvDir 'Scripts\pip.exe'

Write-Host 'Upgrading pip...'
& $VenvPython -m pip install --upgrade pip -q

$LockFile = Join-Path $BackendDir 'requirements.lock'
$ReqFile = Join-Path $BackendDir 'requirements.txt'
if (Test-Path $LockFile) {
    Write-Host 'Using backend/requirements.lock (frozen)'
    & $VenvPip install -r $LockFile
} else {
    Write-Host 'No lockfile; using requirements.txt'
    & $VenvPip install -r $ReqFile
}

# PyPI's default torch on Windows is CPU-only. If an NVIDIA GPU is present,
# replace with the CUDA build for ~20x faster Demucs separation.
# Detect via nvidia-smi (always ships with the NVIDIA driver).
$CudaTorch = $env:CLEANSE_CUDA_TORCH
if (-not $CudaTorch) { $CudaTorch = 'auto' }  # auto | 1 | 0

$hasNvidiaGpu = $false
if ($CudaTorch -ne '0') {
    $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($smi) { $hasNvidiaGpu = $true }
}

if ($hasNvidiaGpu -or $CudaTorch -eq '1') {
    Write-Host ''
    Write-Host 'NVIDIA GPU detected - installing CUDA-enabled torch (~2.7GB download)...'
    Write-Host '  Set CLEANSE_CUDA_TORCH=0 to skip and keep CPU-only torch.'
    & $VenvPip install --upgrade torch==2.7.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu126
    if ($LASTEXITCODE -ne 0) {
        Write-Warning 'CUDA torch install failed; keeping CPU-only torch. Separation will be slow on GPU hardware.'
    }
} else {
    Write-Host ''
    Write-Host 'No NVIDIA GPU detected - using CPU-only torch.'
    Write-Host '  (Separation takes ~10 min per song on CPU. Set CLEANSE_CUDA_TORCH=1 to force CUDA install.)'
}

Write-Host ''
Write-Host '=== Setup complete! ==='
Write-Host 'To start the backend manually:'
Write-Host "  $VenvPython $BackendDir\main.py --port 8765"
