from app.tabs.admin_tab import AdminTab

def test_admin_cannot_demote_self(qtbot, conn):
    tab = AdminTab(conn, current_user_id=1)
    qtbot.addWidget(tab)
    tab.refresh()
    # eigene Zeile finden (ID=1)
    target_row = None
    for r in range(tab.table.rowCount()):
        if tab.table.item(r, 0).text() == "1":
            target_row = r; break
    assert target_row is not None
    tab.table.selectRow(target_row)
    tab.role_edit.setCurrentText("Viewer")
    tab.on_save_selected()
    role = conn.execute("SELECT role FROM users WHERE id=1").fetchone()[0]
    assert role == "Admin"

def test_admin_cannot_delete_self(qtbot, conn):
    tab = AdminTab(conn, current_user_id=1)
    qtbot.addWidget(tab)
    tab.refresh()
    row = None
    for r in range(tab.table.rowCount()):
        if tab.table.item(r, 0).text() == "1":
            row = r; break
    tab.table.selectRow(row)
    tab.on_delete_selected()
    assert conn.execute("SELECT COUNT(*) FROM users WHERE id=1").fetchone()[0] == 1
