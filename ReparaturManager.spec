# -*- mode: python ; coding: utf-8 -*-

import os
from PyInstaller.utils.hooks import collect_all

# Robuster Projektpfad (Fallback, falls __file__ fehlt)
try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    HERE = os.getcwd()

# PyQt6 komplett über offiziellen Hook
qt_datas, qt_bins, qt_hidden = collect_all('PyQt6')

datas = []
binaries = []
hiddenimports = ['bcrypt'] + list(qt_hidden)

datas += qt_datas
binaries += qt_bins

# Optionales App-Icon (EXE-Icon und als Ressource beilegen)
ICON_PATH = os.path.join(HERE, 'app', 'frontend', 'assets', 'app.ico')
has_icon = os.path.exists(ICON_PATH)
if has_icon:
    # Damit QIcon(...) zur Laufzeit die Datei findet
    datas += [(ICON_PATH, 'app/frontend/assets')]

a = Analysis(
    ['app\\main.py'],      # alternativ 'app/main.py'
    pathex=[HERE],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],      # keine Runtime-Hooks
    excludes=[],           # bewusst minimal; bei Bedarf hier Module ausschließen
    noarchive=False,
    optimize=1,            # leichte Optimierung
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ReparaturManager',
    debug=False,                               # Release-Build
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                                  # falls Probleme: auf False setzen
    upx_exclude=['vcruntime140.dll', 'vcruntime140_1.dll', 'ucrtbase.dll'],
    console=False,                             # GUI-App
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_PATH if has_icon else None,      # EXE-Icon
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=['vcruntime140.dll', 'vcruntime140_1.dll', 'ucrtbase.dll'],
    name='ReparaturManager',
)
