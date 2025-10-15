# test_open_tab_visibility.py
import pytest

# Robuster Import (alter Pfad, neuer Pfad, Fallback)
try:
    from app.frontend.tabs.open_tab import OpenTab
except ModuleNotFoundError:
    try:
        from app.frontend.tabs.open_tab import OpenTab
    except ModuleNotFoundError:
        from app.frontend.tabs.open_tab import OpenTab


def _insert_case(conn, clinic, device):
    with conn:
        conn.execute(
            """
            INSERT INTO cases
              (clinic, device_name, wave_number, submitter, service_provider, status, reason, date_submitted, date_returned, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (clinic, device, "W/123", "Max", "Tom Toolmann", "In Reparatur",
             "Defekt", "2024-01-01", None, None),
        )


def _refresh_open_tab(tab: OpenTab):
    """Unterstützt verschiedene Implementierungen (refresh / refresh_open / refresh_cases)."""
    for name in ("refresh_open", "refresh_cases", "refresh"):
        fn = getattr(tab, name, None)
        if callable(fn):
            fn()
            return
    raise AttributeError("OpenTab hat keine bekannte Refresh-Methode (refresh_open/refresh_cases/refresh)")


def _col_index_by_header(tab: OpenTab, header_name: str) -> int:
    """Findet die Spalte anhand des sichtbaren Header-Texts (Case-insensitive)."""
    headers = []
    for c in range(tab.table.columnCount()):
        item = tab.table.horizontalHeaderItem(c)
        text = (item.text() if item else "").strip()
        headers.append(text)
        if text.lower() == header_name.lower():
            return c
    # Fallback: bekannte Alternativen
    alt = {"Klinik": "Clinic", "Clinic": "Klinik"}
    want = alt.get(header_name, header_name)
    for c, text in enumerate(headers):
        if text.lower() == want.lower():
            return c
    raise AssertionError(f"Spalte '{header_name}' nicht gefunden. Header: {headers}")


def test_visibility_filters(qtbot, conn):
    # Testdaten
    _insert_case(conn, "Neuro",    "Endoskop A")
    _insert_case(conn, "Viszeral", "Endoskop B")
    _insert_case(conn, "Thorax",   "Endoskop C")
    _insert_case(conn, "Ortho",    "Endoskop D")

    # Techniker mit Viszeral,Thorax
    tab = OpenTab(conn, role="Techniker", clinics_csv="Viszeral,Thorax", read_only=False)
    qtbot.addWidget(tab)
    _refresh_open_tab(tab)

    clinic_col = _col_index_by_header(tab, "Klinik")

    clinics_in_view = []
    for r in range(tab.table.rowCount()):
        item = tab.table.item(r, clinic_col)
        if item:
            clinics_in_view.append(item.text())

    # Sichtbar dürfen nur die erlaubten Kliniken sein
    assert set(clinics_in_view).issubset({"Viszeral", "Thorax"})
    assert "Neuro" not in clinics_in_view and "Ortho" not in clinics_in_view
