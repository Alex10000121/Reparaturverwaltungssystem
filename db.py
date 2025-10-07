# db.py
import sqlite3
from pathlib import Path
import bcrypt
import json
from datetime import date

DB_PATH = Path(__file__).parent / "resources" / "app.db"

SCHEMA = """
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash BLOB NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('Admin','Techniker','Viewer')),
    clinics TEXT NOT NULL DEFAULT 'ALL' -- 'ALL' or CSV e.g. 'Neuro,Thorax'
);

CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic TEXT NOT NULL,
    device_name TEXT NOT NULL,
    wave_number TEXT,
    submitter TEXT,
    service_provider TEXT,
    status TEXT NOT NULL CHECK (status IN ('In Reparatur','Abgeschlossen')) DEFAULT 'In Reparatur',
    reason TEXT,
    date_submitted TEXT,
    date_returned TEXT,
    created_by TEXT,   -- wer den Fall angelegt hat (Benutzername)
    closed_by TEXT,    -- wer den Fall abgeschlossen hat (Benutzername)
    notes TEXT
);

CREATE TABLE IF NOT EXISTS clinics (
    name TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    user_id INTEGER,
    action TEXT NOT NULL,
    entity TEXT,
    entity_id INTEGER,
    details TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
);
"""

SEED_USERS = [
    ("admin","admin","Admin","ALL"),
    ("tech","tech","Techniker","Neuro"),
    ("view","view","Viewer","Viszeral"),
]

SEED_CLINICS = ["Neuro","Viszeral","Thorax","Ortho"]

def _hash(pw: str) -> bytes:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt())

def get_conn():
    # Ordner für DB sicherstellen (schreibbar, z. B. unter AppData)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Verbindung mit Timeout; check_same_thread=False, wenn du sie threadübergreifend nutzt
    conn = sqlite3.connect(DB_PATH, timeout=5.0, check_same_thread=False)

    # --- WICHTIG: PRAGMAs VOR der ersten Transaktion setzen ---
    # WAL = bessere Parallelität, weniger Locks
    conn.execute("PRAGMA journal_mode=WAL;")
    # Foreign Keys erzwingen (SQLite ist standardmäßig OFF)
    conn.execute("PRAGMA foreign_keys=ON;")
    # Zusätzlicher Busy-Timeout (ergänzt das connect(timeout=...))
    conn.execute("PRAGMA busy_timeout=5000;")
    # Haltbarkeit/Performance-Balance für WAL
    conn.execute("PRAGMA synchronous=NORMAL;")

    # Ab hier alles atomar (Commit/Rollback durch Context Manager)
    with conn:
        # Schema anwenden (idempotent gestaltet annehmen)
        conn.executescript(SCHEMA)

        # ---------- migrations (older dbs) ----------
        # users
        cols_users = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if 'clinics' not in cols_users:
            conn.execute("ALTER TABLE users ADD COLUMN clinics TEXT NOT NULL DEFAULT 'ALL'")

        # cases
        cols_cases = [r[1] for r in conn.execute("PRAGMA table_info(cases)").fetchall()]
        if 'clinic' not in cols_cases:
            conn.execute("ALTER TABLE cases ADD COLUMN clinic TEXT")
            conn.execute("UPDATE cases SET clinic='Neuro' WHERE clinic IS NULL")
        if 'status' not in cols_cases:
            conn.execute("ALTER TABLE cases ADD COLUMN status TEXT NOT NULL DEFAULT 'In Reparatur'")
        if 'date_returned' not in cols_cases:
            conn.execute("ALTER TABLE cases ADD COLUMN date_returned TEXT")
        if 'created_by' not in cols_cases:
            conn.execute("ALTER TABLE cases ADD COLUMN created_by TEXT")
        if 'closed_by' not in cols_cases:
            conn.execute("ALTER TABLE cases ADD COLUMN closed_by TEXT")

        # ---------- hilfreiche Indizes ----------
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_clinic ON cases(clinic)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status)")
        # optional sinnvoll:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_status_id ON cases(status, id DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")

        # ---------- seed data ----------
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            for uname, pwd, role, clinics in SEED_USERS:
                conn.execute(
                    "INSERT INTO users(username,password_hash,role,clinics) VALUES(?,?,?,?)",
                    (uname, _hash(pwd), role, clinics)
                )

        existing = {row[0] for row in conn.execute("SELECT name FROM clinics").fetchall()}
        for name in SEED_CLINICS:
            if name not in existing:
                conn.execute("INSERT OR IGNORE INTO clinics(name) VALUES (?)", (name,))

    return conn



# ---- clinics API ----
def list_clinics():
    conn = get_conn()
    return [row[0] for row in conn.execute(
        "SELECT name FROM clinics ORDER BY name COLLATE NOCASE"
    ).fetchall()]

def add_clinic(name: str):
    name = (name or "").strip()
    if not name:
        raise ValueError("Klinikname darf nicht leer sein.")
    conn = get_conn()
    with conn:
        conn.execute("INSERT INTO clinics(name) VALUES (?)", (name,))
        conn.execute(
            "INSERT INTO audit_log(action, entity, details) VALUES(?,?,?)",
            ("clinic_create","clinic", json.dumps({"name": name}, ensure_ascii=False))
        )

def delete_clinic(name: str):
    """Löscht eine Klinik, sofern keine Fälle diese Klinik verwenden.
       Bereinigt Benutzer-Clinics-CSV (entfernt die Klinik aus den Rechte-Listen)."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Klinikname darf nicht leer sein.")
    conn = get_conn()
    cur = conn.cursor()
    # Blockieren, wenn noch Fälle existieren
    count = cur.execute("SELECT COUNT(*) FROM cases WHERE clinic=?", (name,)).fetchone()[0]
    if count > 0:
        raise ValueError(f"Klinik '{name}' kann nicht gelöscht werden – {count} Fall/Fälle referenziert.")
    with conn:
        # Klinik aus Nutzerrechten entfernen (für Nutzer ohne 'ALL')
        users = cur.execute("SELECT id, clinics FROM users WHERE clinics!='ALL'").fetchall()
        for uid, clinics in users:
            parts = [c.strip() for c in (clinics or "").split(",") if c.strip()]
            if name in parts:
                parts = [c for c in parts if c != name]
                new_csv = ",".join(parts)
                cur.execute("UPDATE users SET clinics=? WHERE id=?", (new_csv, uid))
        # Klinik löschen
        cur.execute("DELETE FROM clinics WHERE name=?", (name,))
        cur.execute(
            "INSERT INTO audit_log(action, entity, details) VALUES(?,?,?)",
            ("clinic_delete","clinic", json.dumps({"name": name}, ensure_ascii=False))
        )


# ---- cases API ----
def add_case(conn: sqlite3.Connection, clinic: str, device_name: str,
             wave_number: str | None, submitter: str | None, service_provider: str | None,
             reason: str | None, date_submitted: str | None,
             created_by: str | None) -> int:
    """
    Legt einen neuen Fall an und speichert optional den anlegenden Benutzer (created_by).
    Gibt die neue ID zurück.
    """
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO cases (clinic, device_name, wave_number, submitter, service_provider,
                           status, reason, date_submitted, created_by)
        VALUES (?, ?, ?, ?, ?, 'In Reparatur', ?, ?, ?)
        """,
        (clinic, device_name, wave_number, submitter, service_provider, reason, date_submitted, created_by)
    )
    conn.commit()
    return cur.lastrowid


def mark_case_done(conn: sqlite3.Connection, case_id: int,
                   returned_date: str | None = None,
                   closed_by: str | None = None) -> None:
    """
    Setzt den Fall auf 'Abgeschlossen', schreibt das Rückgabedatum und optional 'closed_by'
    und loggt ins audit_log. returned_date: 'YYYY-MM-DD' (falls None -> heute).
    """
    if not returned_date:
        returned_date = date.today().strftime("%Y-%m-%d")

    with conn:
        if closed_by is not None:
            conn.execute(
                "UPDATE cases SET status='Abgeschlossen', date_returned=?, closed_by=? WHERE id=?",
                (returned_date, closed_by, case_id)
            )
        else:
            conn.execute(
                "UPDATE cases SET status='Abgeschlossen', date_returned=? WHERE id=?",
                (returned_date, case_id)
            )
        conn.execute(
            "INSERT INTO audit_log(action, entity, entity_id, details) VALUES(?,?,?,?)",
            ("case_update", "case", case_id, json.dumps(
                {"status": "Abgeschlossen", "date_returned": returned_date, "closed_by": closed_by},
                ensure_ascii=False
            ))
        )

def delete_case(case_id: int):
    """Löscht einen Fall. Protokolliert im audit_log."""
    with get_conn() as c:
        # optional: Details vor dem Löschen ziehen (für Audit)
        row = c.execute("SELECT clinic, device_name, wave_number FROM cases WHERE id=?", (case_id,)).fetchone()
        c.execute("DELETE FROM cases WHERE id=?", (case_id,))
        c.execute(
            "INSERT INTO audit_log(action, entity, entity_id, details) VALUES(?,?,?,?)",
            ("case_delete", "case", case_id, json.dumps({"id": case_id, "preview": row}, ensure_ascii=False))
        )

