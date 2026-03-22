# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Groq Dictation — onedir mode (no _MEI temp extraction)."""

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
        ('.venv312/Lib/site-packages/sv_ttk', 'sv_ttk'),
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
        'tkinter',
        'tkinter.ttk',
        'tkinter.messagebox',
        '_tkinter',
        'sv_ttk',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
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

# Onedir mode: exe + DLLs in same folder, no temp extraction
exe = EXE(
    pyz,
    a.scripts,
    [],  # no binaries/datas in exe — they go into COLLECT
    name='AIPolyglotKit',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AIPolyglotKit',
)