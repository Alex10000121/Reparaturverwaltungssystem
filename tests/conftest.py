import sys, pathlib, sqlite3, pytest

# --- Projekt-Root importierbar machen ---
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_SQL = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password TEXT,
  role TEXT NOT NULL,
  clinics TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clinics (
  name TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS cases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  clinic TEXT NOT NULL,
  device_name TEXT NOT NULL,
  wave_number TEXT NOT NULL,
  submitter TEXT NOT NULL,
  service_provider TEXT NOT NULL,
  status TEXT NOT NULL,
  reason TEXT NOT NULL,
  date_submitted TEXT NOT NULL,
  date_returned TEXT,
  notes TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  action TEXT NOT NULL,
  entity TEXT NOT NULL,
  entity_id INTEGER,
  details TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

DEFAULT_CLINICS = ["Neuro", "Viszeral", "Thorax", "Ortho"]

@pytest.fixture(scope="session")
def tmp_db_path(tmp_path_factory):
    return tmp_path_factory.mktemp("db") / "test_repairs.db"

@pytest.fixture(autouse=True)
def patch_db_auth_and_buffer(tmp_db_path, monkeypatch, tmp_path):
    # db.get_conn auf die Test-DB umbiegen
    from app.backend.db.db import db as real_db
    def get_conn_override():
        conn = sqlite3.connect(tmp_db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    monkeypatch.setattr(real_db, "get_conn", get_conn_override, raising=True)

    # Falls db-Hilfsfunktionen fehlen, hier bereitstellen/überschreiben
    def list_clinics():
        with get_conn_override() as c:
            return [r[0] for r in c.execute("SELECT name FROM clinics ORDER BY name").fetchall()]
    def add_clinic(name: str):
        with get_conn_override() as c:
            c.execute("INSERT INTO clinics(name) VALUES(?)", (name,))
    def delete_clinic(name: str):
        with get_conn_override() as c:
            c.execute("DELETE FROM clinics WHERE name=?", (name,))
    monkeypatch.setattr(real_db, "list_clinics", list_clinics, raising=False)
    monkeypatch.setattr(real_db, "add_clinic", add_clinic, raising=False)
    monkeypatch.setattr(real_db, "delete_clinic", delete_clinic, raising=False)

    # auth-Funktionen auf Test-DB umbiegen
    from app.backend import auth as real_auth
    def add_user(username, password, role, clinics):
        with get_conn_override() as c:
            c.execute("INSERT INTO users(username,password,role,clinics) VALUES(?,?,?,?)",
                      (username, password, role, clinics))
    def delete_user(user_id):
        with get_conn_override() as c:
            c.execute("DELETE FROM users WHERE id=?", (user_id,))
    def list_users():
        with get_conn_override() as c:
            return list(c.execute("SELECT id, username, role, clinics FROM users ORDER BY username ASC").fetchall())
    def authenticate(username, password):
        with get_conn_override() as c:
            row = c.execute("SELECT id, role, clinics FROM users WHERE username=? AND password=?",
                            (username, password)).fetchone()
            return tuple(row) if row else None
    monkeypatch.setattr(real_auth, "add_user", add_user, raising=True)
    monkeypatch.setattr(real_auth, "delete_user", delete_user, raising=True)
    monkeypatch.setattr(real_auth, "list_users", list_users, raising=True)
    monkeypatch.setattr(real_auth, "authenticate", authenticate, raising=True)

    # Buffer-Datei auf temporären Ort umbiegen
    import app.backend.helpers.buffer as buffer_mod
    buf_path = tmp_path / "buffer_queue.json"
    def patched_buffer_path():
        return buf_path
    monkeypatch.setattr(buffer_mod, "_buffer_path", patched_buffer_path, raising=True)

    # DB vorbereiten
    conn = get_conn_override()
    with conn:
        conn.executescript(SCHEMA_SQL)
        conn.executemany("INSERT OR IGNORE INTO clinics(name) VALUES(?)",
                         [(n,) for n in DEFAULT_CLINICS])
        conn.execute("INSERT OR IGNORE INTO users(id, username, password, role, clinics) VALUES(1,'admin','admin','Admin','ALL')")
        conn.execute("INSERT OR IGNORE INTO users(id, username, password, role, clinics) VALUES(2,'tech','tech','Techniker','Viszeral,Thorax')")
        conn.execute("INSERT OR IGNORE INTO users(id, username, password, role, clinics) VALUES(3,'viewer','viewer','Viewer','Viszeral')")

    yield

@pytest.fixture
def conn(tmp_db_path):
    c = sqlite3.connect(tmp_db_path)
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
    finally:
        c.close()
