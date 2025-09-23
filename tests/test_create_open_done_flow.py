from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import QCheckBox
from app.tabs.create_tab import CreateTab
from app.tabs.open_tab import OpenTab
from app.tabs.done_tab import DoneTab

def _find_checkbox(wrapper):
    # unsere Tabs verwenden einen zentrierenden Wrapper -> suche QCheckBox darin
    return wrapper.findChild(QCheckBox)

def test_flow_create_complete_reopen(qtbot, conn):
    # Tabs initialisieren (Techniker sieht Erfassen & Offene)
    create = CreateTab(conn, role="Techniker", clinics_csv="Viszeral,Thorax", submitter_default="Max Muster")
    open_tab = OpenTab(conn, role="Techniker", clinics_csv="Viszeral,Thorax", read_only=False)
    done_tab = DoneTab(conn, role="Techniker", clinics_csv="Viszeral,Thorax")

    qtbot.addWidget(create); qtbot.addWidget(open_tab); qtbot.addWidget(done_tab)

    # 1) Fall erfassen
    create.clinic.setCurrentText("Viszeral")
    create.device.setText("Endoskop")
    create.wave.setText("123456 / SN654321")
    create.provider.setText("Tom Toolmann")
    create.reason.setText("Akku defekt")
    create.date_sub.setDate(QDate.currentDate())

    create.on_save()

    # 2) Offene enthalten den neuen Fall
    open_tab.refresh()
    assert open_tab.table.rowCount() >= 1
    case_id = int(open_tab.table.item(0, 0).text())

    # 3) Checkbox "Erledigt?" klicken
    chk_wrapper = open_tab.table.cellWidget(0, 9)
    chk = _find_checkbox(chk_wrapper)
    assert chk is not None
    qtbot.mouseClick(chk, Qt.MouseButton.LeftButton)

    # 4) Jetzt sollte der Fall in "Erledigt" auftauchen
    done_tab.refresh()
    ids_done = [int(done_tab.table.item(r, 0).text()) for r in range(done_tab.table.rowCount())]
    assert case_id in ids_done

    # 5) Wieder öffnen in DoneTab
    row_idx = ids_done.index(case_id)
    chk_wrapper2 = done_tab.table.cellWidget(row_idx, 9)
    chk2 = _find_checkbox(chk_wrapper2)
    qtbot.mouseClick(chk2, Qt.MouseButton.LeftButton)

    # 6) Fall muss wieder bei Offenen auftauchen
    open_tab.refresh()
    ids_open = [int(open_tab.table.item(r, 0).text()) for r in range(open_tab.table.rowCount())]
    assert case_id in ids_open
