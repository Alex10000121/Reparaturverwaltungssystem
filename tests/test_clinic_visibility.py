from app.tabs.open_tab import OpenTab

def _insert_case(conn, clinic, device):
    with conn:
        conn.execute("""INSERT INTO cases
        (clinic, device_name, wave_number, submitter, service_provider, status, reason, date_submitted, date_returned, notes)
        VALUES(?,?,?,?,?,?,?,?,?,?)""" ,
        (clinic, device, "W/123", "Max", "Tom Toolmann", "In Reparatur", "Defekt", "2024-01-01", None, None))

def test_visibility_filters(qtbot, conn):
    # Daten
    _insert_case(conn, "Neuro", "Endoskop A")
    _insert_case(conn, "Viszeral", "Endoskop B")
    _insert_case(conn, "Thorax", "Endoskop C")
    _insert_case(conn, "Ortho", "Endoskop D")

    # Techniker mit Viszeral,Thorax
    tab = OpenTab(conn, role="Techniker", clinics_csv="Viszeral,Thorax", read_only=False)
    qtbot.addWidget(tab)
    tab.refresh()

    clinics_in_view = [tab.table.item(r,1).text() for r in range(tab.table.rowCount())]
    assert set(clinics_in_view).issubset({"Viszeral", "Thorax"})
    assert "Neuro" not in clinics_in_view and "Ortho" not in clinics_in_view
