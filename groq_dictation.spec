# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Groq Dictation."""

import os
import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('config.yaml', '.'),
    ],
    hiddenimports=[
        'pystray._win32',
        'PIL._tkinter_finder',
        'comtypes',
        'comtypes.stream',
        'webrtcvad',
        'pyperclip',
        'keyboard',
        'pynput',
        'pynput.keyboard',
        'pynput.keyboard._win32',
        'pynput.mouse',
        'pynput.mouse._win32',
        'yaml',
        'dotenv',
        'httpx',
        'httpcore',
        'h11',
        'certifi',
        'idna',
        'sniffio',
        'anyio',
        'anyio._backends',
        'anyio._backends._asyncio',
        'packaging',
        'packaging.version',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
        # 'tkinter',  # needed by overlay and settings_ui
        'unittest',
        'test',
        'xmlrpc',
        'pydoc',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='GroqDictation',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=os.path.join(os.environ.get('LOCALAPPDATA', ''), 'GroqDictation', '_runtime'),
    console=False,  # windowed (no console)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
