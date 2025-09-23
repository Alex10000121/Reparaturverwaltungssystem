import json, sqlite3
from PyQt6.QtCore import QDate
import app.buffer as buffer_mod
from app.tabs.create_tab import CreateTab
from app.buffer import sync_buffer_once

class ProxyConn:
    """Wrappt eine echte sqlite3.Connection und simuliert 'database is locked'
    nur für INSERT INTO cases. Alle anderen Aufrufe delegiert er an die echte
    Connection. Unterstützt Kontextmanager.
    """
    def __init__(self, real):
        self._real = real

    def execute(self, sql, *params):
        sql_upper = str(sql).strip().upper()
        if sql_upper.startswith("INSERT INTO CASES"):
            raise sqlite3.OperationalError("database is locked")
        return self._real.execute(sql, *params)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __enter__(self):
        self._real.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._real.__exit__(exc_type, exc, tb)

def test_buffer_enqueue_and_sync(qtbot, conn, tmp_db_path):
    # 1) Verwende ProxyConn, der Inserts in cases blockiert
    proxy = ProxyConn(conn)

    # 2) Erfassung -> geht in den Buffer
    create = CreateTab(proxy, role="Techniker", clinics_csv="Viszeral,Thorax", submitter_default="Max")
    qtbot.addWidget(create)
    create.clinic.setCurrentText("Viszeral")
    create.device.setText("Endoskop")
    create.wave.setText("123456 / SN654321")
    create.provider.setText("Tom Toolmann")
    create.reason.setText("Akku defekt")
    create.date_sub.setDate(QDate.currentDate())

    create.on_save()  # keine Exception -> landet im Buffer

    # Buffer-Datei prüfen
    buf_path = buffer_mod._buffer_path()
    data = json.loads(buf_path.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["type"] == "insert_case"

    # 3) "Neustart": neue echte Connection -> sync_buffer_once()
    conn2 = sqlite3.connect(tmp_db_path)
    conn2.execute("PRAGMA foreign_keys=ON")
    ok, fail = sync_buffer_once(conn2)
    assert ok == 1 and fail == 0

    # Nach Sync: Buffer leer
    data2 = json.loads(buf_path.read_text(encoding="utf-8"))
    assert data2 == []

    # Case tatsächlich in DB?
    c = conn2.execute("SELECT clinic, device_name, wave_number, status FROM cases").fetchone()
    assert c[0] == "Viszeral" and c[1] == "Endoskop" and c[2].startswith("123456") and c[3] == "In Reparatur"
