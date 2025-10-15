# test_main_tabs.py
import pytest

# Robuster Import, funktioniert egal ob app/main.py oder main.py
try:
    from app.main import Main
except ModuleNotFoundError:
    from app.main import Main


def _tab_titles(widget):
    """Liest alle Tab-Titel aus einem QTabWidget aus."""
    return [widget.tabText(i) for i in range(widget.count())]


def test_main_tabs_for_admin(qtbot, conn):
    """Admin sollte Zugriff auf alle Tabs haben (Admin, Erfassen, Offene, Erledigt)."""
    win = Main(user_id=1, role="Admin", clinics_csv="ALL", username="admin")
    qtbot.addWidget(win)

    titles = _tab_titles(win.tabs)
    lowered = [t.lower() for t in titles]

    # Muss Tabs für Administration, offene und erledigte Fälle sowie Erfassung enthalten
    assert any("admin" in t for t in lowered), f"Fehlender 'Admin'-Tab: {titles}"
    assert any("offen" in t for t in lowered), f"Fehlender 'Offene Reparaturen'-Tab: {titles}"
    assert any("erled" in t for t in lowered), f"Fehlender 'Erledigt'-Tab: {titles}"
    assert any("erfass" in t for t in lowered), f"Fehlender 'Erfassen'-Tab: {titles}"


def test_main_tabs_for_viewer(qtbot, conn):
    """Viewer darf keine Daten erfassen oder Admin-Aufgaben sehen, aber offene und erledigte Fälle."""
    win = Main(user_id=3, role="Viewer", clinics_csv="Viszeral", username="viewer")
    qtbot.addWidget(win)

    titles = _tab_titles(win.tabs)
    lowered = [t.lower() for t in titles]

    # Viewer darf keine Admin- oder Erfassungs-Tabs haben
    assert not any("admin" in t for t in lowered), f"Viewer sollte keinen Admin-Tab haben: {titles}"
    assert not any("erfass" in t for t in lowered), f"Viewer sollte keinen Erfassen-Tab haben: {titles}"

    # Muss Offene und Erledigte Tabs haben
    assert any("offen" in t for t in lowered), f"Fehlender 'Offene Reparaturen'-Tab: {titles}"
    assert any("erled" in t for t in lowered), f"Fehlender 'Erledigt'-Tab: {titles}"
