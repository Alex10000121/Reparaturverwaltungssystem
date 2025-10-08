import json, sqlite3, os, tempfile
from pathlib import Path


def _buffer_path() -> Path:
    return Path(__file__).resolve().parent.parent / "resources" / "buffer_queue.json"

def _load_buffer() -> list[dict]:
    p = _buffer_path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        try:
            p.rename(p.with_suffix(".json.bak"))
        except Exception:
            pass
        return []

def _save_buffer(entries: list[dict]) -> None:
    p = _buffer_path()
    p.parent.mkdir(parents=True, exist_ok=True)

    # Erst in eine temporäre Datei schreiben
    with tempfile.NamedTemporaryFile("w", delete=False, dir=p.parent, encoding="utf-8") as tmp:
        json.dump(entries, tmp, indent=2, ensure_ascii=False)
        tmp.flush()
        os.fsync(tmp.fileno())  # sicherstellen, dass alles auf Platte ist

    # Atomar ersetzen: entweder die alte Datei oder die neue, nie ein "halbes" File
    os.replace(tmp.name, p)
def enqueue_write(payload: dict):
    entries = _load_buffer(); entries.append(payload); _save_buffer(entries)

def _apply_buffer_entry(conn: sqlite3.Connection, entry: dict) -> None:
    etype = entry.get("type")
    if etype == "insert_case":
        fields = ["clinic","device_name","wave_number","submitter","service_provider",
                  "status","reason","date_submitted","date_returned","notes"]
        values = [entry.get(k) for k in fields]
        with conn:
            conn.execute(
                """INSERT INTO cases(clinic,device_name,wave_number,submitter,service_provider,status,reason,
                                      date_submitted,date_returned,notes)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""", values)
    elif etype == "update_case":
        with conn:
            conn.execute("UPDATE cases SET status=?, date_returned=? WHERE id=?",
                         (entry.get("status"), entry.get("date_returned"), entry["id"]))
    else:
        raise ValueError(f"Unbekannter Buffer-Typ: {etype}")

def sync_buffer_once(conn: sqlite3.Connection) -> tuple[int,int]:
    entries = _load_buffer()
    if not entries: return (0, 0)
    ok, failed = 0, []
    for i, e in enumerate(entries):
        try:
            _apply_buffer_entry(conn, e); ok += 1
        except Exception as ex:
            msg = str(ex).lower()
            if "locked" in msg or "busy" in msg:
                failed.extend(entries[i:]); break
            failed.append(e)
    _save_buffer(failed)
    return ok, len(failed)
