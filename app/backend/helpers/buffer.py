import json, sqlite3, os, tempfile, hashlib
from pathlib import Path


# -------------------------------------------------
# Pfadfunktionen
# -------------------------------------------------
def _buffer_path() -> Path:
    return Path(__file__).resolve().parent.parent / "." / "db" / "resources" / "buffer_queue.json"


# -------------------------------------------------
# Hash-Helfer
# -------------------------------------------------
def _calc_hash(entries: list[dict]) -> str:
    """Berechnet einen SHA256-Hash über den Inhalt."""
    return hashlib.sha256(json.dumps(entries, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


# -------------------------------------------------
# Lesen & Schreiben mit Integritätsprüfung
# -------------------------------------------------
def _load_buffer() -> list[dict]:
    """Lädt den Buffer und prüft den Hash – bei Manipulation wird eine leere Liste zurückgegeben."""
    p = _buffer_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        entries = data.get("entries", [])
        expected_hash = data.get("hash")
        actual_hash = _calc_hash(entries)

        if expected_hash != actual_hash:
            print("⚠️ WARNUNG: Buffer-Datei wurde möglicherweise manipuliert – verworfen.")
            p.rename(p.with_suffix(".json.corrupt"))
            return []

        return entries
    except Exception as ex:
        print(f"⚠️ Fehler beim Laden des Buffers: {ex}")
        try:
            p.rename(p.with_suffix(".json.bak"))
        except Exception:
            pass
        return []


def _save_buffer(entries: list[dict]) -> None:
    """Speichert den Buffer mit Integritätshash atomar."""
    p = _buffer_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "entries": entries,
        "hash": _calc_hash(entries)
    }

    # Temporäre Datei -> atomar ersetzen
    with tempfile.NamedTemporaryFile("w", delete=False, dir=p.parent, encoding="utf-8") as tmp:
        json.dump(payload, tmp, indent=2, ensure_ascii=False)
        tmp.flush()
        os.fsync(tmp.fileno())
    os.replace(tmp.name, p)


# -------------------------------------------------
# Buffer-Operationen
# -------------------------------------------------
def enqueue_write(payload: dict):
    """Schreibt einen neuen Datensatz in den Buffer."""
    entries = _load_buffer()
    entries.append(payload)
    _save_buffer(entries)


def _apply_buffer_entry(conn: sqlite3.Connection, entry: dict) -> None:
    etype = entry.get("type")

    if etype == "insert_case":
        fields = [
            "clinic", "device_name", "wave_number", "submitter", "service_provider",
            "status", "reason", "date_submitted", "date_returned", "notes", "created_by"
        ]
        values = [entry.get(k) for k in fields]
        with conn:
            conn.execute(
                """INSERT INTO cases(clinic,device_name,wave_number,submitter,service_provider,
                                      status,reason,date_submitted,date_returned,notes,created_by)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                values
            )

    elif etype == "update_case":
        with conn:
            conn.execute(
                "UPDATE cases SET status=?, date_returned=?, closed_by=? WHERE id=?",
                (entry.get("status"), entry.get("date_returned"), entry.get("closed_by"), entry["id"])
            )

    elif etype == "delete_case":
        with conn:
            conn.execute("DELETE FROM cases WHERE id=?", (entry["id"],))
            conn.execute(
                "INSERT INTO audit_log(action, entity, entity_id, details) VALUES(?,?,?,?)",
                ("case_delete", "case", entry["id"], json.dumps({"id": entry["id"]}, ensure_ascii=False))
            )

    else:
        raise ValueError(f"Unbekannter Buffer-Typ: {etype}")


def sync_buffer_once(conn: sqlite3.Connection) -> tuple[int, int]:
    """Versucht, alle Buffer-Einträge mit der DB zu synchronisieren."""
    entries = _load_buffer()
    if not entries:
        return (0, 0)

    ok, failed = 0, []
    for i, e in enumerate(entries):
        try:
            _apply_buffer_entry(conn, e)
            ok += 1
        except Exception as ex:
            msg = str(ex).lower()
            if "locked" in msg or "busy" in msg:
                failed.extend(entries[i:])
                break
            failed.append(e)

    _save_buffer(failed)
    return ok, len(failed)
