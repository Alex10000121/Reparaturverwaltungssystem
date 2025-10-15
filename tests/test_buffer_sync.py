# test_buffer_sync.py
import json, sqlite3, pathlib
from PyQt6.QtCore import QDate

# Robuster Import der CreateTab-View (unterstützt verschiedene Projektstrukturen)
try:
    from app.frontend.tabs.create_tab import CreateTab
except ModuleNotFoundError:
    try:
        from app.frontend.tabs.create_tab import CreateTab
    except ModuleNotFoundError:
        from app.frontend.tabs.create_tab import CreateTab

# Robuster Import der Buffer-Funktionen
try:
    import app.backend.helpers.buffer as buffer_mod
    from app.backend.helpers.buffer import sync_buffer_once
except ModuleNotFoundError:
    import buffer as buffer_mod
    from app.backend.helpers.buffer import buffer
    from app.backend.helpers.buffer import sync_buffer_once


class ProxyConn:
    """
    Wrappt eine echte sqlite3.Connection und simuliert 'database is locked'
    nur für INSERT INTO cases. Alle anderen Aufrufe gehen an die echte Connection.
    Unterstützt Kontextmanager.
    """
    def __init__(self, real):
        self._real = real

    def execute(self, sql, *params):
        sql_upper = str(sql).strip().upper()
        if sql_upper.startswith("INSERT INTO CASES"):
            raise sqlite3.OperationalError("database is locked")
        return self._real.execute(sql, *params)

    # delegiere alle anderen Attribute/Methoden (executemany, executescript, cursor, etc.)
    def __getattr__(self, name):
        return getattr(self._real, name)

    def __enter__(self):
        self._real.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._real.__exit__(exc_type, exc, tb)


def _read_buffer_entries(buf_path: pathlib.Path):
    """
    Liest den Buffer robust ein.
    Unterstützt:
        - Liste von Entries: [ {...}, ... ]
        - Dict mit 'entries' + optionalem 'hash': { "entries": [...], "hash": "..." }
    Rückgabe: (entries_list, full_obj)
    """
    raw = json.loads(buf_path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "entries" in raw:
        return raw["entries"], raw
    elif isinstance(raw, list):
        return raw, {"entries": raw}
    else:
        raise AssertionError(f"Unerwartetes Buffer-Format: {type(raw)} -> {raw}")


def test_buffer_enqueue_and_sync(qtbot, conn, tmp_db_path):
    # 1) ProxyConn, der nur Inserts in cases blockiert
    proxy = ProxyConn(conn)

    # 2) Erfassung -> soll in den Buffer landen (keine Exception im UI)
    create = CreateTab(
        proxy,
        role="Techniker",
        clinics_csv="Viszeral,Thorax",
        submitter_default="Max",
    )
    qtbot.addWidget(create)

    create.clinic.setCurrentText("Viszeral")
    create.device.setText("Endoskop")
    create.wave.setText("123456 / SN654321")
    create.provider.setText("Tom Toolmann")
    create.reason.setText("Akku defekt")
    create.date_sub.setDate(QDate.currentDate())

    # Save triggert im Produktivcode: bei OperationalError -> Buffer enqueue
    create.on_save()

    # 3) Buffer-Datei prüfen
    buf_path = buffer_mod._buffer_path()
    assert isinstance(buf_path, (str, pathlib.Path))
    buf_path = pathlib.Path(buf_path)
    assert buf_path.exists(), "Buffer-Datei sollte nach enqueue existieren"

    entries, full = _read_buffer_entries(buf_path)
    assert len(entries) == 1, f"Buffer sollte 1 Eintrag haben, hat: {len(entries)} – Inhalt: {full}"
    assert entries[0].get("type") == "insert_case"

    # 4) "Neustart": neue echte Connection -> sync_buffer_once()
    conn2 = sqlite3.connect(tmp_db_path)
    conn2.execute("PRAGMA foreign_keys=ON")
    ok, fail = sync_buffer_once(conn2)
    assert ok == 1 and fail == 0, "Buffer sollte 1 Eintrag erfolgreich synchronisieren"

    # Nach Sync: Buffer leer (Struktur kann Dict bleiben)
    entries2, full2 = _read_buffer_entries(buf_path)
    assert entries2 == [], f"Buffer sollte nach erfolgreichem Sync leer sein, ist: {full2}"

    # 5) Case tatsächlich in DB?
    c = conn2.execute(
        "SELECT clinic, device_name, wave_number, status FROM cases ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert c is not None, "Es sollte mindestens ein Case nach dem Sync vorhanden sein"
    assert c[0] == "Viszeral"
    assert c[1] == "Endoskop"
    assert str(c[2]).startswith("123456")
    assert c[3] == "In Reparatur"
