from app.main import Main

def _tab_titles(widget):
    return [widget.tabText(i) for i in range(widget.count())]

def test_main_tabs_for_admin(qtbot, conn):
    win = Main(user_id=1, role="Admin", clinics_csv="ALL", username="admin")
    qtbot.addWidget(win)
    titles = _tab_titles(win.tabs)
    # Admin hat Admin + (Erfassen) + Offene + Erledigt
    assert "Admin" in titles and "Offene Reparaturen" in titles and "Erledigt" in titles
    assert "Erfassen" in titles  # Admin darf erfassen

def test_main_tabs_for_viewer(qtbot, conn):
    win = Main(user_id=3, role="Viewer", clinics_csv="Viszeral", username="viewer")
    qtbot.addWidget(win)
    titles = _tab_titles(win.tabs)
    # Viewer hat KEIN Erfassen, KEIN Admin
    assert "Erfassen" not in titles and "Admin" not in titles
    assert "Offene Reparaturen" in titles and "Erledigt" in titles
