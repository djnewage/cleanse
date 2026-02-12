# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Cleanse FastAPI backend.

Builds a one-dir bundle containing the Python interpreter, all dependencies
(torch, demucs, faster-whisper, uvicorn, etc.), and the application code.

Usage:
    cd backend && source venv/bin/activate
    pyinstaller cleanse-backend.spec --noconfirm
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Collect data files that libraries need at runtime
datas = []
datas += collect_data_files('faster_whisper')
datas += collect_data_files('demucs')
datas += collect_data_files('better_profanity')
datas += collect_data_files('pydub')
datas += collect_data_files('uvicorn')
datas += collect_data_files('imageio_ffmpeg')

# Hidden imports that PyInstaller's static analysis misses
hidden_imports = []
hidden_imports += collect_submodules('uvicorn')
hidden_imports += collect_submodules('faster_whisper')
hidden_imports += collect_submodules('demucs')
hidden_imports += collect_submodules('torch')
hidden_imports += collect_submodules('torchaudio')
hidden_imports += collect_submodules('pydub')
hidden_imports += collect_submodules('numpy')
hidden_imports += [
    'fastapi',
    'fastapi.middleware',
    'fastapi.middleware.cors',
    'starlette',
    'starlette.routing',
    'starlette.responses',
    'starlette.middleware',
    'starlette.middleware.cors',
    'pydantic',
    'pydantic.deprecated',
    'pydantic.deprecated.decorator',
    'better_profanity',
    'multipart',
    'python_multipart',
    'ctranslate2',
    'huggingface_hub',
    'requests',
    'certifi',
    'charset_normalizer',
    'idna',
    'urllib3',
    'anyio',
    'anyio._backends',
    'anyio._backends._asyncio',
    'sniffio',
    'h11',
    'httptools',
    'websockets',
    'watchfiles',
    'dotenv',
    'yaml',
    'imageio_ffmpeg',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'PIL',
        'notebook',
        'jupyter',
        'IPython',
        'av',
    ],
    noarchive=False,
    optimize=0,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='cleanse-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    target_arch=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='cleanse-backend',
)
