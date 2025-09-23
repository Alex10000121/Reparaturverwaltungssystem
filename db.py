import sqlite3
from pathlib import Path
import bcrypt

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
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    with conn:
        conn.executescript(SCHEMA)

        # migrations (older dbs)
        cols_users = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if 'clinics' not in cols_users:
            conn.execute("ALTER TABLE users ADD COLUMN clinics TEXT NOT NULL DEFAULT 'ALL'")

        cols_cases = [r[1] for r in conn.execute("PRAGMA table_info(cases)").fetchall()]
        if 'clinic' not in cols_cases:
            conn.execute("ALTER TABLE cases ADD COLUMN clinic TEXT")
            conn.execute("UPDATE cases SET clinic='Neuro' WHERE clinic IS NULL")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_clinic ON cases(clinic)")

        # seed users
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            for uname, pwd, role, clinics in SEED_USERS:
                conn.execute("INSERT INTO users(username,password_hash,role,clinics) VALUES(?,?,?,?)",
                             (uname, _hash(pwd), role, clinics))
        # seed clinics
        existing = {row[0] for row in conn.execute("SELECT name FROM clinics").fetchall()}
        for name in SEED_CLINICS:
            if name not in existing:
                conn.execute("INSERT OR IGNORE INTO clinics(name) VALUES (?)", (name,))
    return conn

# ---- clinics API ----
def list_clinics():
    conn = get_conn()
    return [row[0] for row in conn.execute("SELECT name FROM clinics ORDER BY name COLLATE NOCASE").fetchall()]

def add_clinic(name: str):
    name = (name or "").strip()
    if not name:
        raise ValueError("Klinikname darf nicht leer sein.")
    conn = get_conn()
    with conn:
        conn.execute("INSERT INTO clinics(name) VALUES (?)", (name,))
        conn.execute("INSERT INTO audit_log(action, entity, details) VALUES(?,?,?)",
                     ("clinic_create","clinic", f'{{"name":"{name}"}}'))

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
        cur.execute("INSERT INTO audit_log(action, entity, details) VALUES(?,?,?)",
                    ("clinic_delete","clinic", f'{{"name":"{name}"}}'))
