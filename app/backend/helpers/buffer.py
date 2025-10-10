from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ============================================
# Pfade und Ablage
# ============================================

def _buffer_path() -> Path:
    """
    Liefert den Speicherort der Pufferdatei.
    Hinweis: Du kannst den Pfad bei Bedarf zentral hier anpassen,
    zum Beispiel um ihn in einen AppData-Ordner zu verlegen.
    """
    return Path(__file__).resolve().parent.parent / "." / "db" / "resources" / "buffer_queue.json"


# ============================================
# Hash-Helfer
# ============================================

def _calc_hash(entries: List[Dict]) -> str:
    """
    Berechnet einen SHA256-Hash über den Inhalt der Einträge.
    Der Hash deckt nur die Liste der Einträge ab, nicht die umgebenden Metadaten.
    """
    payload = json.dumps(entries, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ============================================
# Lesen und Schreiben mit Integritätsprüfung
# ============================================

def _load_buffer() -> List[Dict]:
    """
    Lädt den Puffer und prüft den Integritätshash.
    Wenn die Prüfung fehlschlägt oder die Datei defekt ist, wird eine leere Liste zurückgegeben.
    Die defekte Datei wird umbenannt, damit sie nicht weiter stört.
    """
    p = _buffer_path()
    if not p.exists():
        return []

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        entries = data.get("entries", [])
        expected_hash = data.get("hash")
        actual_hash = _calc_hash(entries)

        if expected_hash != actual_hash:
            # Datei wurde verändert oder unvollständig gespeichert – zur Seite legen
            try:
                p.rename(p.with_suffix(".json.corrupt"))
            except Exception:
                pass
            return []

        # Sicherheitsnetz: nur Listen zulassen
        if not isinstance(entries, list):
            return []

        return entries

    except Exception:
        # Datei unlesbar oder JSON fehlerhaft – zur Seite legen und mit leerem Puffer weitermachen
        try:
            p.rename(p.with_suffix(".json.bak"))
        except Exception:
            pass
        return []


def _save_buffer(entries: List[Dict]) -> None:
    """
    Speichert den Puffer atomar mit Integritätshash.
    Der Schreibvorgang nutzt eine temporäre Datei und ersetzt danach die Zieldatei in einem Schritt.
    """
    p = _buffer_path()
    p.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "entries": entries,
        "hash": _calc_hash(entries),
    }

    # Temporäre Datei schreiben, auf Festplatte sichern, dann atomar ersetzen
    with tempfile.NamedTemporaryFile("w", delete=False, dir=p.parent, encoding="utf-8") as tmp:
        json.dump(payload, tmp, indent=2, ensure_ascii=False)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_name = tmp.name

    os.replace(tmp_name, p)


# ============================================
# Puffer-Operationen
# ============================================

def enqueue_write(payload: Dict) -> None:
    """
    Hängt einen neuen Datensatz an den lokalen Puffer an.
    Beispiel: {"type": "insert_case", ...}
    """
    entries = _load_buffer()
    entries.append(payload)
    _save_buffer(entries)


# ============================================
# Anwenden einzelner Puffer-Einträge
# ============================================

_INSERT_FIELDS: Tuple[str, ...] = (
    "clinic", "device_name", "wave_number", "submitter", "service_provider",
    "status", "reason", "date_submitted", "date_returned", "notes", "created_by",
)

def _apply_buffer_entry(conn: sqlite3.Connection, entry: Dict) -> None:
    """
    Wendet genau einen Puffer-Eintrag auf die Datenbank an.
    Unterstützte Typen:
      - insert_case
      - update_case
      - delete_case
    """
    etype = entry.get("type")

    if etype == "insert_case":
        # Pflichtfelder prüfen
        if not entry.get("clinic"):
            raise ValueError("Feld 'clinic' fehlt oder ist leer.")
        if not entry.get("device_name"):
            raise ValueError("Feld 'device_name' fehlt oder ist leer.")

        values = [entry.get(k) for k in _INSERT_FIELDS]
        with conn:
            conn.execute(
                """
                INSERT INTO cases(
                    clinic, device_name, wave_number, submitter, service_provider,
                    status, reason, date_submitted, date_returned, notes, created_by
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                values,
            )

    elif etype == "update_case":
        cid = entry.get("id")
        if cid is None:
            raise ValueError("Feld 'id' fehlt für update_case.")
        with conn:
            conn.execute(
                "UPDATE cases SET status=?, date_returned=?, closed_by=? WHERE id=?",
                (
                    entry.get("status"),
                    entry.get("date_returned"),
                    entry.get("closed_by"),
                    cid,
                ),
            )

    elif etype == "delete_case":
        cid = entry.get("id")
        if cid is None:
            raise ValueError("Feld 'id' fehlt für delete_case.")
        with conn:
            conn.execute("DELETE FROM cases WHERE id=?", (cid,))
            conn.execute(
                "INSERT INTO audit_log(action, entity, entity_id, details) VALUES(?,?,?,?)",
                (
                    "case_delete",
                    "case",
                    cid,
                    json.dumps({"id": cid}, ensure_ascii=False),
                ),
            )

    else:
        raise ValueError(f"Unbekannter Puffer-Typ: {etype}")


# ============================================
# Synchronisation
# ============================================

def sync_buffer_once(conn: sqlite3.Connection) -> Tuple[int, int]:
    """
    Versucht, alle Puffer-Einträge mit der Datenbank zu synchronisieren.
    Rückgabe: (Anzahl erfolgreich, Anzahl verblieben)

    Verhalten bei Problemen:
    - Wenn ein Eintrag wegen Sperren oder Busy nicht verarbeitet werden kann,
      wird ab diesem Punkt abgebrochen und der Rest bleibt im Puffer.
    - Einträge mit anderen Fehlern werden übersprungen und verbleiben ebenfalls.
    """
    entries = _load_buffer()
    if not entries:
        return 0, 0

    ok_count = 0
    failed: List[Dict] = []

    for i, e in enumerate(entries):
        try:
            _apply_buffer_entry(conn, e)
            ok_count += 1
        except Exception as ex:
            msg = str(ex).lower()
            if "locked" in msg or "busy" in msg:
                # Datenbank gerade beschäftigt – Rest später erneut versuchen
                failed.extend(entries[i:])
                break
            failed.append(e)

    _save_buffer(failed)
    return ok_count, len(failed)
