# auth.py
from typing import Optional, Tuple, Dict
import sqlite3
import bcrypt
import json
import datetime

from db import get_conn

# --- Konfiguration ---
MAX_FAILED_ATTEMPTS = 5          # nach so vielen Fehlversuchen ...
LOCKOUT_MINUTES = 15             # ... für so viele Minuten sperren
BCRYPT_ROUNDS = 12               # Kostenfaktor für neue Passwörter

# Dummy-Hash gegen Benutzer-Enumeration / Timing-Unterschiede
_DUMMY_PASSWORD = b"__dummy_password_for_timing__"
_DUMMY_HASH = bcrypt.hashpw(_DUMMY_PASSWORD, bcrypt.gensalt(rounds=BCRYPT_ROUNDS))

# ---------- Hilfsfunktionen ----------

def _ensure_login_attempts_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS login_attempts (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        attempt_time TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

def _audit(conn: sqlite3.Connection, user_id: Optional[int], action: str, details: Dict) -> None:
    conn.execute(
        "INSERT INTO audit_log(user_id, action, entity, details) VALUES(?,?,?,?)",
        (user_id, action, "user", json.dumps(details, ensure_ascii=False))
    )

def _failed_attempts_count(conn: sqlite3.Connection, user_id: int, since_minutes: int) -> int:
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(minutes=since_minutes)).isoformat()
    cur = conn.execute(
        "SELECT COUNT(*) FROM login_attempts WHERE user_id = ? AND attempt_time > ?",
        (user_id, cutoff)
    )
    return cur.fetchone()[0]

def _add_failed_attempt(conn: sqlite3.Connection, user_id: int) -> None:
    now = datetime.datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO login_attempts(user_id, attempt_time) VALUES (?, ?)",
        (user_id, now)
    )

# ---------- Öffentliche Funktionen ----------

def authenticate(username: str, password: str) -> Optional[Tuple[int, str, str]]:
    """
    Authentifiziert den Benutzer.
    Rückgabe:
      - (user_id, role, clinics) bei Erfolg
      - None bei Fehlschlag oder Lockout
    """
    conn = get_conn()
    _ensure_login_attempts_table(conn)

    # Benutzer abrufen
    cur = conn.execute(
        "SELECT id, role, clinics, password_hash FROM users WHERE username = ?",
        (username,)
    )
    row = cur.fetchone()

    # Lockout prüfen (nur für existierenden Benutzer)
    user_id = row[0] if row else None
    if user_id is not None:
        if _failed_attempts_count(conn, user_id, LOCKOUT_MINUTES) >= MAX_FAILED_ATTEMPTS:
            # Optionales Audit
            try:
                with conn:
                    _audit(conn, user_id, "login_blocked", {"username": username, "reason": "too_many_attempts"})
            except Exception:
                pass
            return None

    # Passwort prüfen — immer durchführen (Dummy-Hash, wenn Benutzer nicht existiert)
    if row:
        hash_to_check = row[3]
    else:
        hash_to_check = _DUMMY_HASH

    if isinstance(hash_to_check, str):
        hash_bytes = hash_to_check.encode("utf-8")
    else:
        hash_bytes = hash_to_check

    try:
        ok = bcrypt.checkpw(password.encode("utf-8"), hash_bytes)
    except Exception:
        ok = False

    if ok and row:
        # Erfolg: Audit & Failed-Attempts aufräumen
        try:
            with conn:
                _audit(conn, row[0], "login_success", {"username": username})
                conn.execute("DELETE FROM login_attempts WHERE user_id = ?", (row[0],))
        except Exception:
            pass
        return (row[0], row[1], row[2])

    # Fehlschlag: protokollieren (falls Benutzer existiert, sonst nur generisch)
    try:
        with conn:
            if row:
                _add_failed_attempt(conn, row[0])
                attempts = _failed_attempts_count(conn, row[0], LOCKOUT_MINUTES)
                _audit(conn, row[0], "login_failure", {"username": username, "attempts_last_minutes": attempts})
            else:
                _audit(conn, None, "login_failure", {"username": username})
    except Exception:
        pass

    return None


def list_users():
    conn = get_conn()
    return conn.execute(
        "SELECT id, username, role, clinics FROM users ORDER BY username COLLATE NOCASE"
    ).fetchall()


def add_user(username: str, password: str, role: str, clinics: str):
    conn = get_conn()
    with conn:
        ph = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS))
        conn.execute(
            "INSERT INTO users(username,password_hash,role,clinics) VALUES(?,?,?,?)",
            (username, ph, role, clinics)
        )
        conn.execute(
            "INSERT INTO audit_log(action, entity, details) VALUES(?,?,?)",
            ("user_create", "user", json.dumps(
                {"username": username, "role": role, "clinics": clinics},
                ensure_ascii=False
            ))
        )


def update_user_clinics(user_id: int, clinics: str):
    conn = get_conn()
    with conn:
        conn.execute("UPDATE users SET clinics=? WHERE id=?", (clinics, user_id))
        conn.execute(
            "INSERT INTO audit_log(action, entity, entity_id, details) VALUES(?,?,?,?)",
            ("user_update", "user", user_id, json.dumps({"clinics": clinics}, ensure_ascii=False))
        )


def delete_user(user_id: int):
    conn = get_conn()
    with conn:
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.execute(
            "INSERT INTO audit_log(action, entity, entity_id) VALUES(?,?,?)",
            ("user_delete", "user", user_id)
        )
