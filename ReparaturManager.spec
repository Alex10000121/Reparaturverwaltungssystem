# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

pyqt6_datas, pyqt6_bins, pyqt6_hidden = collect_all("PyQt6")
bcrypt_datas, bcrypt_bins, bcrypt_hidden = collect_all("bcrypt")
# Optional, falls nötig:
# cffi_datas, cffi_bins, cffi_hidden = collect_all("cffi")

block_cipher = None

a = Analysis(
    ['app/main.py'],
    pathex=[os.path.abspath('.')],
    binaries=pyqt6_bins + bcrypt_bins,  # + cffi_bins
    datas=pyqt6_datas + bcrypt_datas + [  # + cffi_datas
        # ('resources/buffer_queue.json', 'resources'),
        # ('icons/app.ico', 'icons'),
    ],
    hiddenimports=pyqt6_hidden + bcrypt_hidden + [
        'bcrypt',
        # *cffi_hidden  # falls oben aktiviert
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ReparaturManager',
    icon='icons/app.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,

    # ↓↓↓ hier anpassen ↓↓↓
    upx=False,                 # UPX ausschalten
    upx_exclude=[],
    console=False,              # Für Debug-Ausgabe aktivieren
    # ↑↑↑ nachher wieder False setzen, wenn alles läuft ↑↑↑

    runtime_tmpdir=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='ReparaturManager'
)
