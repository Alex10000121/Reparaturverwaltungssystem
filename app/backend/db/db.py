# db.py
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import List, Optional, Tuple

import bcrypt

# Pfad zur Datenbank
DB_PATH = Path(__file__).parent / "resources" / "app.db"

# Konstante Felder und Werte
ROLE_ADMIN = "Admin"
ROLE_TECH = "Techniker"
ROLE_VIEW = "Viewer"

STATUS_OPEN = "In Reparatur"
STATUS_DONE = "Abgeschlossen"

ALL_CLINICS_SENTINEL = "ALL"

SCHEMA = """
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash BLOB NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('Admin','Techniker','Viewer')),
    clinics TEXT NOT NULL DEFAULT 'ALL' -- 'ALL' oder CSV z. B. 'Neuro,Thorax'
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

SEED_USERS: List[Tuple[str, str, str, str]] = [
    ("admin", "admin", ROLE_ADMIN, ALL_CLINICS_SENTINEL),
    ("tech", "tech", ROLE_TECH, "Neuro"),
    ("view", "view", ROLE_VIEW, "Viszeral"),
]

SEED_CLINICS: List[str] = ["Neuro", "Viszeral", "Thorax", "Ortho"]


def _hash_password(plain: str) -> bytes:
    """Erzeugt einen bcrypt-Hash aus dem Klartextpasswort."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt())


def get_conn() -> sqlite3.Connection:
    """
    Stellt die Verbindung her, sorgt für sinnvolle PRAGMAs
    und fuehrt Schema, Migrationen, Indizes und Seed-Daten aus.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5.0, check_same_thread=False)

    # Wichtige PRAGMAs früh setzen
    conn.execute("PRAGMA journal_mode=WAL;")       # bessere Parallelitaet
    conn.execute("PRAGMA foreign_keys=ON;")        # Fremdschluessel erzwingen
    conn.execute("PRAGMA busy_timeout=5000;")      # Geduld bei Locks
    conn.execute("PRAGMA synchronous=NORMAL;")     # Vernuenftige Balance Haltbarkeit/Tempo
    conn.execute("PRAGMA temp_store=MEMORY;")      # temporaere Daten in RAM

    with conn:
        # Schema idempotent anwenden
        conn.executescript(SCHEMA)

        # Migrationen: fehlende Spalten nachziehen
        def _columns(table: str) -> List[str]:
            return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]

        cols_users = _columns("users")
        if "clinics" not in cols_users:
            conn.execute("ALTER TABLE users ADD COLUMN clinics TEXT NOT NULL DEFAULT 'ALL'")

        cols_cases = _columns("cases")
        if "clinic" not in cols_cases:
            conn.execute("ALTER TABLE cases ADD COLUMN clinic TEXT")
            conn.execute("UPDATE cases SET clinic='Neuro' WHERE clinic IS NULL")
        if "status" not in cols_cases:
            conn.execute("ALTER TABLE cases ADD COLUMN status TEXT NOT NULL DEFAULT 'In Reparatur'")
        if "date_returned" not in cols_cases:
            conn.execute("ALTER TABLE cases ADD COLUMN date_returned TEXT")
        if "created_by" not in cols_cases:
            conn.execute("ALTER TABLE cases ADD COLUMN created_by TEXT")
        if "closed_by" not in cols_cases:
            conn.execute("ALTER TABLE cases ADD COLUMN closed_by TEXT")

        # Hilfreiche Indizes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_clinic ON cases(clinic)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_status_id ON cases(status, id DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")

        # Seed-Daten nur einmal einspielen
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            for uname, pwd, role, clinics in SEED_USERS:
                conn.execute(
                    "INSERT INTO users(username, password_hash, role, clinics) VALUES(?,?,?,?)",
                    (uname, _hash_password(pwd), role, clinics),
                )

        existing = {row[0] for row in conn.execute("SELECT name FROM clinics").fetchall()}
        for name in SEED_CLINICS:
            if name not in existing:
                conn.execute("INSERT OR IGNORE INTO clinics(name) VALUES (?)", (name,))

    return conn


# ========= Clinics API =========

def list_clinics() -> List[str]:
    """Gibt alle Kliniken alphabetisch zurueck."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT name FROM clinics ORDER BY name COLLATE NOCASE"
    ).fetchall()
    return [r[0] for r in rows]


def add_clinic(name: str) -> None:
    """
    Fuegt eine neue Klinik hinzu und protokolliert dies im Audit-Log.
    Hinweis: Der Name sollte eindeutig sein.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("Klinikname darf nicht leer sein.")

    conn = get_conn()
    with conn:
        conn.execute("INSERT INTO clinics(name) VALUES (?)", (name,))
        conn.execute(
            "INSERT INTO audit_log(action, entity, details) VALUES(?,?,?)",
            ("clinic_create", "clinic", json.dumps({"name": name}, ensure_ascii=False)),
        )


def delete_clinic(name: str) -> None:
    """
    Loescht eine Klinik, sofern keine Faelle darauf verweisen.
    Nutzerrechte werden bereinigt, falls die Klinik dort aufgefuehrt war.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("Klinikname darf nicht leer sein.")

    conn = get_conn()
    cur = conn.cursor()

    # Abbrechen, wenn noch Fälle existieren
    count = cur.execute("SELECT COUNT(*) FROM cases WHERE clinic=?", (name,)).fetchone()[0]
    if count > 0:
        raise ValueError(f"Klinik '{name}' kann nicht geloescht werden, {count} Fall oder Faelle verweisen darauf.")

    with conn:
        # Klinik aus Nutzerrechten entfernen (nur wenn nicht ALL)
        users = cur.execute("SELECT id, clinics FROM users WHERE clinics != ?", (ALL_CLINICS_SENTINEL,)).fetchall()
        for uid, clinics_csv in users:
            parts = [c.strip() for c in (clinics_csv or "").split(",") if c.strip()]
            if name in parts:
                parts = [c for c in parts if c != name]
                new_csv = ",".join(parts)
                cur.execute("UPDATE users SET clinics=? WHERE id=?", (new_csv, uid))

        # Klinik löschen und Audit schreiben
        cur.execute("DELETE FROM clinics WHERE name=?", (name,))
        cur.execute(
            "INSERT INTO audit_log(action, entity, details) VALUES(?,?,?)",
            ("clinic_delete", "clinic", json.dumps({"name": name}, ensure_ascii=False)),
        )


# ========= Cases API =========

def add_case(
    conn: sqlite3.Connection,
    clinic: str,
    device_name: str,
    wave_number: Optional[str],
    submitter: Optional[str],
    service_provider: Optional[str],
    reason: Optional[str],
    date_submitted: Optional[str],
    created_by: Optional[str],
) -> int:
    """
    Legt einen neuen Fall an. Optional wird gespeichert, wer den Fall angelegt hat.
    Rückgabe: ID des neuen Falls.
    """
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO cases (
            clinic, device_name, wave_number, submitter, service_provider,
            status, reason, date_submitted, created_by
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            clinic,
            device_name,
            wave_number,
            submitter,
            service_provider,
            STATUS_OPEN,
            reason,
            date_submitted,
            created_by,
        ),
    )
    conn.commit()
    return cur.lastrowid


def mark_case_done(
    conn: sqlite3.Connection,
    case_id: int,
    returned_date: Optional[str] = None,
    closed_by: Optional[str] = None,
) -> None:
    """
    Setzt den Fall auf abgeschlossen, schreibt das Rückgabedatum und optional wer abgeschlossen hat.
    returned_date erwartet 'YYYY-MM-DD'. Wenn None, wird das heutige Datum gesetzt.
    Zusätzlich wird ein Eintrag ins Audit-Log geschrieben.
    """
    if not returned_date:
        returned_date = date.today().strftime("%Y-%m-%d")

    with conn:
        if closed_by is not None:
            conn.execute(
                "UPDATE cases SET status=?, date_returned=?, closed_by=? WHERE id=?",
                (STATUS_DONE, returned_date, closed_by, case_id),
            )
        else:
            conn.execute(
                "UPDATE cases SET status=?, date_returned=? WHERE id=?",
                (STATUS_DONE, returned_date, case_id),
            )

        conn.execute(
            "INSERT INTO audit_log(action, entity, entity_id, details) VALUES(?,?,?,?)",
            (
                "case_update",
                "case",
                case_id,
                json.dumps(
                    {"status": STATUS_DONE, "date_returned": returned_date, "closed_by": closed_by},
                    ensure_ascii=False,
                ),
            ),
        )


def delete_case(case_id: int) -> None:
    """
    Löscht einen Fall und protokolliert dies im Audit-Log.
    Es wird ein kurzer Vorab-Blick gespeichert, damit später nachvollziehbar bleibt,
    was entfernt wurde.
    """
    with get_conn() as c:
        row = c.execute(
            "SELECT clinic, device_name, wave_number FROM cases WHERE id=?",
            (case_id,),
        ).fetchone()
        c.execute("DELETE FROM cases WHERE id=?", (case_id,))
        c.execute(
            "INSERT INTO audit_log(action, entity, entity_id, details) VALUES(?,?,?,?)",
            (
                "case_delete",
                "case",
                case_id,
                json.dumps({"id": case_id, "preview": row}, ensure_ascii=False),
            ),
        )


# ========= Users API =========

def set_user_password(user_id: int, new_plain: str) -> None:
    """
    Setzt das Passwort eines Nutzers auf den angegebenen Klartext.
    Der bcrypt-Hash wird in users.password_hash gespeichert.
    Es erfolgt ein Eintrag im Audit-Log.
    """
    new_plain = (new_plain or "").strip()
    if len(new_plain) < 8:
        raise ValueError("Das Passwort muss mindestens 8 Zeichen lang sein.")

    hpw = bcrypt.hashpw(new_plain.encode("utf-8"), bcrypt.gensalt())
    with get_conn() as c:
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (hpw, user_id))
        c.execute(
            "INSERT INTO audit_log(action, entity, entity_id, details) VALUES(?,?,?,?)",
            (
                "user_password_reset",
                "user",
                user_id,
                json.dumps({"user_id": user_id}, ensure_ascii=False),
            ),
        )
# Pruning: Alte Einträge löschen, um DB klein zu halten

def prune_completed_cases(conn: sqlite3.Connection, keep: int = 1000) -> int:
    cur = conn.cursor()
    over = cur.execute(
        "SELECT MAX(COUNT(*), 0) FROM (SELECT 1 FROM cases WHERE status='Abgeschlossen')"
    ).fetchone()[0] - keep
    over = max(0, over or 0)
    if over <= 0:
        return 0
    ids = [r[0] for r in cur.execute("""
        SELECT id FROM cases
        WHERE status='Abgeschlossen'
        ORDER BY (date_returned IS NULL) ASC, date_returned ASC, id ASC
        LIMIT ?
    """, (over,)).fetchall()]
    if not ids:
        return 0
    q = ",".join("?" * len(ids))
    with conn:
        conn.execute(f"DELETE FROM cases WHERE id IN ({q})", ids)
    return len(ids)

def prune_audit_log(conn: sqlite3.Connection, keep: int = 50000) -> int:
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    over = max(0, total - keep)
    if over <= 0:
        return 0
    with conn:
        conn.execute("""
            DELETE FROM audit_log
            WHERE id IN (
                SELECT id FROM audit_log
                ORDER BY id ASC
                LIMIT ?
            )
        """, (over,))
    return over