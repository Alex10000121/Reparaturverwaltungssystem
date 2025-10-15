# test_create_open_done_flow.py
from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import QCheckBox

# Robuste Importe mit Fallbacks
try:
    from app.frontend.tabs.create_tab import CreateTab
    from app.frontend.tabs.open_tab import OpenTab
    from app.frontend.tabs.done_tab import DoneTab
except ModuleNotFoundError:
    try:
        from app.frontend.tabs.create_tab import CreateTab
        from app.frontend.tabs.open_tab import OpenTab
        from app.frontend.tabs.done_tab import DoneTab
    except ModuleNotFoundError:
        from app.frontend.tabs.create_tab import CreateTab
        from app.frontend.tabs.open_tab import OpenTab
        from app.frontend.tabs.done_tab import DoneTab


def _find_checkbox(wrapper):
    return wrapper.findChild(QCheckBox) if wrapper is not None else None


def _refresh_any(tab, *names):
    for n in names:
        fn = getattr(tab, n, None)
        if callable(fn):
            fn()
            return
    if hasattr(tab, "refresh") and callable(getattr(tab, "refresh")):
        tab.refresh()
        return
    raise AttributeError(f"Keine bekannte Refresh-Methode auf {tab.__class__.__name__} gefunden.")


def _col_index_by_header_contains(table, *substrings):
    """
    Findet eine Spalte, deren Headertext (case-insensitive) eine der Teilzeichenketten enthält.
    Beispiel: ("wave", "serien") findet "Wave- / Serienummer" oder "Wave- / Seriennummer".
    """
    headers = []
    subs = [s.lower() for s in substrings]
    for c in range(table.columnCount()):
        item = table.horizontalHeaderItem(c)
        text = (item.text() if item else "").strip()
        headers.append(text)
        low = text.lower()
        if any(s in low for s in subs):
            return c
    raise AssertionError(f"Keine Spalte gefunden, deren Header {substrings} enthält. Header: {headers}")


def _col_index_by_header_exact(table, *candidates):
    """
    Findet eine Spalte anhand exakter Kandidatennamen (case-insensitive).
    """
    headers = []
    lowers = [c.lower() for c in candidates]
    for c in range(table.columnCount()):
        item = table.horizontalHeaderItem(c)
        text = (item.text() if item else "").strip()
        headers.append(text)
        if text.lower() in lowers:
            return c
    raise AssertionError(f"Spalte {candidates} nicht gefunden. Header: {headers}")


def _find_row_by_values(table, want: dict) -> int:
    """
    Sucht die erste Tabellenzeile, die alle geforderten Werte erfüllt.
    'want' ist ein Mapping {spalten_index: predicate}, wobei predicate(str)->bool ist.
    """
    rows = table.rowCount()
    for r in range(rows):
        ok = True
        for c, pred in want.items():
            item = table.item(r, c)
            text = (item.text() if item else "").strip() if item else ""
            if not pred(text):
                ok = False
                break
        if ok:
            return r
    raise AssertionError("Keine Zeile gefunden, die die Filterbedingungen erfüllt.")


def test_flow_create_complete_reopen(qtbot, conn):
    # Tabs initialisieren (Techniker sieht Erfassen & Offene & Erledigt)
    create = CreateTab(conn, role="Techniker", clinics_csv="Viszeral,Thorax", submitter_default="Max Muster")
    open_tab = OpenTab(conn, role="Techniker", clinics_csv="Viszeral,Thorax", read_only=False)
    done_tab = DoneTab(conn, role="Techniker", clinics_csv="Viszeral,Thorax")

    qtbot.addWidget(create)
    qtbot.addWidget(open_tab)
    qtbot.addWidget(done_tab)

    # --- 1) Fall erfassen ---
    clinic_val = "Viszeral"
    device_val = "Endoskop"
    wave_val_prefix = "123456"  # wir prüfen über startswith

    create.clinic.setCurrentText(clinic_val)
    create.device.setText(device_val)
    create.wave.setText(f"{wave_val_prefix} / SN654321")
    create.provider.setText("Tom Toolmann")
    create.reason.setText("Akku defekt")
    create.date_sub.setDate(QDate.currentDate())
    create.on_save()  # sollte ohne Exception funktionieren

    # --- 2) Offene enthalten den neuen Fall ---
    _refresh_any(open_tab, "refresh_open", "refresh_cases")
    assert open_tab.table.rowCount() >= 1

    # Spaltenindizes in OpenTab ermitteln
    col_clinic_open = _col_index_by_header_contains(open_tab.table, "klinik", "clinic")
    col_device_open = _col_index_by_header_contains(open_tab.table, "gerät", "device")
    col_wave_open   = _col_index_by_header_contains(open_tab.table, "wave", "serien")

    # Zeile mit unserem neuen Fall finden
    row_open = _find_row_by_values(
        open_tab.table,
        {
            col_clinic_open: lambda t: t == clinic_val,
            col_device_open: lambda t: t == device_val,
            col_wave_open:   lambda t: t.startswith(wave_val_prefix),
        },
    )

    # Checkbox-Spalte in OpenTab (Erledigt?) ermitteln und anklicken
    col_done_chk_open = _col_index_by_header_contains(open_tab.table, "erledigt", "done", "abschliess", "schliess")
    chk_wrapper = open_tab.table.cellWidget(row_open, col_done_chk_open)
    chk = _find_checkbox(chk_wrapper)
    assert chk is not None, "Checkbox-Widget in OpenTab nicht gefunden"
    qtbot.mouseClick(chk, Qt.MouseButton.LeftButton)

    # --- 3) Jetzt sollte der Fall in "Erledigt" auftauchen ---
    _refresh_any(done_tab, "refresh_done", "refresh_cases")
    assert done_tab.table.rowCount() >= 1

    # Spaltenindizes in DoneTab ermitteln
    col_clinic_done = _col_index_by_header_contains(done_tab.table, "klinik", "clinic")
    col_device_done = _col_index_by_header_contains(done_tab.table, "gerät", "device")
    col_wave_done   = _col_index_by_header_contains(done_tab.table, "wave", "serien")

    # Zeile in DoneTab wiederfinden
    row_done = _find_row_by_values(
        done_tab.table,
        {
            col_clinic_done: lambda t: t == clinic_val,
            col_device_done: lambda t: t == device_val,
            col_wave_done:   lambda t: t.startswith(wave_val_prefix),
        },
    )

    # Checkbox-Spalte im DoneTab (Wieder öffnen?) ermitteln und anklicken
    col_reopen_chk_done = _col_index_by_header_contains(done_tab.table, "wieder öffnen", "reopen", "wieder", "öffnen")
    chk_wrapper2 = done_tab.table.cellWidget(row_done, col_reopen_chk_done)
    chk2 = _find_checkbox(chk_wrapper2)
    assert chk2 is not None, "Checkbox-Widget in DoneTab nicht gefunden"
    qtbot.mouseClick(chk2, Qt.MouseButton.LeftButton)

    # --- 4) Fall muss wieder bei Offenen auftauchen ---
    _refresh_any(open_tab, "refresh_open", "refresh_cases")

    # Zeile erneut in Offenen finden (falls Sortierung/Filter abweicht)
    row_open_again = _find_row_by_values(
        open_tab.table,
        {
            col_clinic_open: lambda t: t == clinic_val,
            col_device_open: lambda t: t == device_val,
            col_wave_open:   lambda t: t.startswith(wave_val_prefix),
        },
    )
    assert row_open_again >= 0