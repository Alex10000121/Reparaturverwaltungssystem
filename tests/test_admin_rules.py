# test_admin_tab_permissions.py
import pytest

# Robust import: unterstützt beide möglichen Modulpfade (app.frontend.tabs vs app.tabs)
try:
    from app.frontend.tabs.admin_tab import AdminTab  # alter Pfad
except ModuleNotFoundError:
    try:
        from app.frontend.tabs.admin_tab import AdminTab       # neuer Pfad (so wie in deiner Datei gekennzeichnet)
    except ModuleNotFoundError:
        from app.frontend.tabs.admin_tab import AdminTab                # Fallback, falls Tests im gleichen Ordner laufen

def _select_row_by_id(tab: AdminTab, user_id: int) -> int | None:
    """Hilfsfunktion: wählt die Zeile mit der gegebenen ID aus und gibt den Row-Index zurück."""
    for r in range(tab.table.rowCount()):
        item = tab.table.item(r, 0)
        if item and item.text() == str(user_id):
            tab.table.selectRow(r)
            return r
    return None

def test_admin_cannot_demote_self(qtbot, conn):
    tab = AdminTab(conn, current_user_id=1)
    qtbot.addWidget(tab)

    # Tabelle initial füllen (Konstruktor ruft zwar schon refresh_users(), hier zur Sicherheit nochmal)
    tab.refresh_users()

    # eigene Zeile finden (ID=1)
    row = _select_row_by_id(tab, 1)
    assert row is not None, "Admin (ID=1) sollte in der Tabelle vorhanden sein"

    # Versuch: Selbst-Degradierung
    tab.role_edit.setCurrentText("Viewer")
    tab.on_save_selected()

    # Erwartung: Rolle bleibt Admin
    role = conn.execute("SELECT role FROM users WHERE id=1").fetchone()[0]
    assert role == "Admin"

def test_admin_cannot_delete_self(qtbot, conn):
    tab = AdminTab(conn, current_user_id=1)
    qtbot.addWidget(tab)

    tab.refresh_users()

    row = _select_row_by_id(tab, 1)
    assert row is not None, "Admin (ID=1) sollte in der Tabelle vorhanden sein"

    # Versuch: sich selbst löschen (soll durch Schutzlogik verhindert werden, ohne Confirm-Dialog)
    tab.on_delete_selected()

    count = conn.execute("SELECT COUNT(*) FROM users WHERE id=1").fetchone()[0]
    assert count == 1, "Eigenlöschung des Admins darf nicht möglich sein"
