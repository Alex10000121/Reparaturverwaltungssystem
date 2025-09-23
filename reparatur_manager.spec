# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

# Sammle PyQt6 vollständig (Plugins, Styles, Daten)
pyqt6_datas, pyqt6_bins, pyqt6_hidden = collect_all("PyQt6")
# Sammle bcrypt vollständig (inkl. _bcrypt.pyd)
bcrypt_datas, bcrypt_bins, bcrypt_hidden = collect_all("bcrypt")

block_cipher = None

a = Analysis(
    ['app/main.py'],
    pathex=[],
    binaries=pyqt6_bins + bcrypt_bins,
    datas=pyqt6_datas + bcrypt_datas + [
        # Beispiel: weitere Dateien einpacken (Quelle, Zielordner im Paket)
        # ('resources/buffer_queue.json', 'resources'),
        # ('icons/app.ico', 'icons'),
    ],
    hiddenimports=pyqt6_hidden + bcrypt_hidden + [
        'bcrypt',   # zusätzliche Sicherheit für den Import
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ReparaturManager',
    icon='icons\\app.ico',   # falls kein Icon vorhanden: Zeile entfernen oder Pfad anpassen
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,               # falls UPX nicht installiert -> auf False setzen
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # GUI-App (ohne Konsole)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# One-Folder Ausgabe (startet schneller). Wenn du One-File möchtest, bau lieber per CLI mit -F
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name='ReparaturManager')
