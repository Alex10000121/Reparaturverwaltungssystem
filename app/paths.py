# app/paths.py
from __future__ import annotations
import sys, os
from pathlib import Path

APP_DIR_NAME = "ReparaturManager"

def is_frozen() -> bool:
    return getattr(sys, "frozen", False) is not False

def base_dir() -> Path:
    # Ort der laufenden App: im dev (PyCharm) = Projektordner,
    # im EXE-Modus = entpackter Temp-Ordner (sys._MEIPASS)
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path.cwd()))
    return Path(__file__).resolve().parents[1]  # …/app -> Projektroot

def user_data_dir() -> Path:
    # stabiler, beschreibbarer Ort für DB/Buffer/Logs
    base = os.getenv("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    p = Path(base) / APP_DIR_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p

def resource_path(rel: str) -> Path:
    """
    Lese-Ressourcen (Icons, Vorlagen) finden:
    - dev: relativ zum Projekt
    - exe: relativ zum _MEIPASS-Ordner
    """
    return base_dir() / rel
