from typing import Optional, Tuple
import bcrypt
from db import get_conn

def authenticate(username: str, password: str) -> Optional[Tuple[int,str,str]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, role, clinics, password_hash FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    if row and bcrypt.checkpw(password.encode("utf-8"), row[3]):
        try:
            conn.execute("INSERT INTO audit_log(user_id, action, entity, details) VALUES(?,?,?,?)",
                         (row[0], "login_success", "user", f'{{"username":"{username}"}}'))
            conn.commit()
        except Exception:
            pass
        return (row[0], row[1], row[2])
    return None

def list_users():
    conn = get_conn()
    return conn.execute("SELECT id, username, role, clinics FROM users ORDER BY username COLLATE NOCASE").fetchall()

def add_user(username: str, password: str, role: str, clinics: str):
    conn = get_conn()
    with conn:
        ph = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        conn.execute("INSERT INTO users(username,password_hash,role,clinics) VALUES(?,?,?,?)", (username,ph,role,clinics))
        conn.execute("INSERT INTO audit_log(action, entity, details) VALUES(?,?,?)",
                     ("user_create", "user", f'{{"username":"{username}","role":"{role}","clinics":"{clinics}"}}'))

def update_user_clinics(user_id: int, clinics: str):
    conn = get_conn()
    with conn:
        conn.execute("UPDATE users SET clinics=? WHERE id=?", (clinics, user_id))
        conn.execute("INSERT INTO audit_log(action, entity, entity_id, details) VALUES(?,?,?,?)",
                     ("user_update", "user", user_id, f'{{"clinics":"{clinics}"}}'))

def delete_user(user_id: int):
    conn = get_conn()
    with conn:
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.execute("INSERT INTO audit_log(action, entity, entity_id) VALUES(?,?,?)",
                     ("user_delete", "user", user_id))
