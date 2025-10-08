# Offline-Puffer für DB-Schreibvorgänge (atomar, robust, schema-sicher)
# Unterstützt insert_case (mit created_by), update_case (mit closed_by), delete_case.
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
    Pfad zur JSON-Pufferdatei.
    Liegt relativ zu diesem Modul unter: app/backend/resources/buffer_queue.json
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
    - insert_case: setzt 'created_by' aus submitter (oder alternativen Feldern), falls fehlt.
    - update_case/delete_case: keine automatische Ableitung nötig.
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
    Liest Spaltennamen der Tabelle 'cases', um Inserts/Updates passend zum aktuellen Schema
    zu formulieren (keine Schema-Änderung).
    """
    cols: set[str] = set()
    for _cid, name, *_ in conn.execute("PRAGMA table_info(cases)"):
        cols.add(name)
    return cols


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND lower(name)=lower(?) LIMIT 1",
        (name,)
    ).fetchone()
    return row is not None


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
        cols = _cases_columns(conn)

        # Dynamisch SET-Klausel bauen: status und date_returned immer, closed_by optional
        set_cols: List[str] = []
        params: List[object] = []

        if "status" in cols and "status" in entry:
            set_cols.append("status=?")
            params.append(entry.get("status"))

        if "date_returned" in cols and "date_returned" in entry:
            set_cols.append("date_returned=?")
            params.append(entry.get("date_returned"))

        # Ergänzung: closed_by mit übernehmen, wenn vorhanden und Spalte existiert
        if "closed_by" in cols and entry.get("closed_by") is not None:
            set_cols.append("closed_by=?")
            params.append(entry.get("closed_by"))

        if not set_cols:
            # Nichts zu aktualisieren – still ignorieren
            return

        params.append(entry["id"])  # WHERE id=?

        with conn:
            conn.execute(
                f"UPDATE cases SET {', '.join(set_cols)} WHERE id=?",
                tuple(params)
            )

    elif etype == "delete_case":
        case_id = entry["id"]
        with conn:
            conn.execute("DELETE FROM cases WHERE id=?", (case_id,))
            # Optionales Audit, falls Tabelle vorhanden
            if _table_exists(conn, "audit_log"):
                details = {"deleted_by": entry.get("deleted_by")}
                conn.execute(
                    "INSERT INTO audit_log(action, entity, entity_id, details) VALUES(?,?,?,?)",
                    ("case_delete", "case", case_id, json.dumps(details, ensure_ascii=False))
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
