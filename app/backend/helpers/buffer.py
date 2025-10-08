# Offline-Puffer für DB-Schreibvorgänge (atomar, robust, schema-sicher)
# (Ergänzt 'created_by' aus 'submitter' für JSON-Fälle; DB-Schema wird NICHT verändert.)

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import List, Dict, Tuple


# ------------------------------------------------------------
# Pfad-Handling
# ------------------------------------------------------------

def _buffer_path() -> Path:
    """
    Pfad zur JSON-Pufferdatei. Liegt relativ zu diesem Modul unter:
    app/backend/resources/buffer_queue.json
    """
    return Path(__file__).resolve().parent.parent / "resources" / "buffer_queue.json"


# ------------------------------------------------------------
# JSON I/O (robust + atomar)
# ------------------------------------------------------------

def _load_buffer() -> List[Dict]:
    p = _buffer_path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        # Defektes JSON vorsichtig sichern und mit leerer Queue fortfahren
        try:
            p.rename(p.with_suffix(".json.bak"))
        except Exception:
            pass
        return []


def _save_buffer(entries: List[Dict]) -> None:
    """
    Schreibt die Queue atomar: erst in temporäre Datei, dann os.replace().
    So vermeiden wir halbgeschriebene Dateien.
    """
    p = _buffer_path()
    p.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile("w", delete=False, dir=p.parent, encoding="utf-8") as tmp:
        json.dump(entries, tmp, indent=2, ensure_ascii=False)
        tmp.flush()
        os.fsync(tmp.fileno())
    os.replace(tmp.name, p)


# ------------------------------------------------------------
# Normalisierung der Payloads (nur Inhalte; kein Schema-Ändern)
# ------------------------------------------------------------

def _normalize_entry(entry: Dict) -> Dict:
    """
    Ergänzt fehlende Felder sinnvoll, ohne DB-Schema zu ändern.
    - Für insert_case: setzt 'created_by' aus 'submitter' (falls nicht vorhanden).
    """
    if entry.get("type") == "insert_case":
        if not entry.get("created_by"):
            entry["created_by"] = (
                entry.get("submitter")
                or entry.get("username")
                or entry.get("user")
                or entry.get("owner")
            )
    return entry


def enqueue_write(payload: Dict) -> None:
    """
    Fügt eine Operation in die Puffer-Queue ein (z. B. bei gesperrter DB).
    """
    payload = _normalize_entry(dict(payload))  # Kopie normalisieren
    entries = _load_buffer()
    entries.append(payload)
    _save_buffer(entries)


# ------------------------------------------------------------
# Schema-Helfer
# ------------------------------------------------------------

def _cases_columns(conn: sqlite3.Connection) -> set[str]:
    """
    Liest Spaltennamen der Tabelle 'cases', um Inserts passend zum aktuellen Schema
    zu formulieren (keine Schema-Änderung).
    """
    cols: set[str] = set()
    for _cid, name, *_ in conn.execute("PRAGMA table_info(cases)"):
        cols.add(name)
    return cols


# ------------------------------------------------------------
# Anwenden einzelner Einträge
# ------------------------------------------------------------

def _apply_buffer_entry(conn: sqlite3.Connection, entry: Dict) -> None:
    """
    Wendet genau einen Queue-Eintrag auf die DB an.
    Bricht mit Exception ab, wenn 'locked/busy' o. ä., damit der Aufrufer die Queue stehen lässt.
    """
    entry = _normalize_entry(dict(entry))
    etype = entry.get("type")

    if etype == "insert_case":
        cols = _cases_columns(conn)

        # Gerät: verwende die Spalte, die existiert (device_name oder device)
        device_col: str | None = None
        if "device_name" in cols:
            device_col = "device_name"
        elif "device" in cols:
            device_col = "device"
        else:
            raise RuntimeError("Tabelle 'cases' hat weder 'device_name' noch 'device'.")

        # Basisspalten (nur solche verwenden, die tatsächlich existieren)
        desired_order: List[Tuple[str, str]] = [
            ("clinic", "clinic"),
            (device_col, "device_name"),  # Payload-Key wird unten über Fallback bedient
            ("wave_number", "wave_number"),
            ("submitter", "submitter"),
            ("service_provider", "service_provider"),
            ("status", "status"),
            ("reason", "reason"),
            ("date_submitted", "date_submitted"),
            ("date_returned", "date_returned"),
            ("notes", "notes"),
            # Wichtig: created_by nur, wenn vorhanden
            ("created_by", "created_by"),
        ]

        # Filtere auf existierende Spalten; sammle Werte in derselben Reihenfolge
        column_names: List[str] = []
        values: List[object] = []
        for col_name, payload_key in desired_order:
            if col_name is None:
                continue
            if col_name not in cols:
                continue

            if col_name == device_col:
                # Payload kann device_name ODER device enthalten
                val = entry.get("device_name")
                if val is None:
                    val = entry.get("device")
            else:
                val = entry.get(payload_key)

            column_names.append(col_name)
            values.append(val)

        if not column_names:
            raise RuntimeError("Kein geeignetes Spaltenziel für INSERT gefunden.")

        placeholders = ",".join("?" for _ in column_names)
        column_list = ",".join(column_names)

        with conn:
            conn.execute(
                f"INSERT INTO cases({column_list}) VALUES({placeholders})",
                values
            )

    elif etype == "update_case":
        with conn:
            conn.execute(
                "UPDATE cases SET status=?, date_returned=? WHERE id=?",
                (entry.get("status"), entry.get("date_returned"), entry["id"])
            )
    else:
        raise ValueError(f"Unbekannter Buffer-Typ: {etype}")


# ------------------------------------------------------------
# Öffentliche Sync-API
# ------------------------------------------------------------

def sync_buffer_once(conn: sqlite3.Connection) -> Tuple[int, int]:
    """
    Versucht, die Queue EINMAL von vorne abzuarbeiten.
    - Bei 'locked/busy' wird abgebrochen; restliche Einträge bleiben stehen.
    - Gibt (ok_count, failed_count) zurück.
    """
    entries = _load_buffer()
    if not entries:
        return (0, 0)

    ok = 0
    failed: List[Dict] = []

    for i, e in enumerate(entries):
        try:
            _apply_buffer_entry(conn, e)
            ok += 1
        except Exception as ex:
            msg = str(ex).lower()
            # „locked/busy“ => restliche Einträge stehen lassen, in der JSON verbleiben
            if "locked" in msg or "busy" in msg:
                failed.extend(entries[i:])
                break
            # anderer Fehler => diesen Eintrag überspringen, aber weitermachen
            failed.append(e)

    _save_buffer(failed)
    return ok, len(failed)
