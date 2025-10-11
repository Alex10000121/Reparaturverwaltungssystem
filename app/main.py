# app/main.py
import sys
import sqlite3
from PyQt6.QtWidgets import QApplication, QMainWindow, QTabWidget, QStatusBar, QMessageBox
from PyQt6.QtCore import Qt

from app.backend.db.db import get_conn
from app.frontend.theme import apply_app_theme, apply_system_theme
from app.backend.helpers.buffer import sync_buffer_once
from app.frontend.widgets.login import Login
from app.frontend.tabs.create_tab import CreateTab
from app.frontend.tabs.open_tab import OpenTab
from app.frontend.tabs.done_tab import DoneTab
from app.frontend.tabs.admin_tab import AdminTab


class Main(QMainWindow):
    """Hauptfenster der Reparaturverwaltung."""

    def __init__(self, user_id: int, role: str, clinics_csv: str, username: str):
        super().__init__()
        self.setWindowTitle("Reparaturverwaltung")
        self.resize(1280, 860)
        self.setWindowState(Qt.WindowState.WindowMaximized)

        # Verbindung herstellen
        self.conn: sqlite3.Connection = get_conn()
        self.user_id = user_id
        self.role = role
        self.clinics_csv = clinics_csv
        self.username = username

        # Start-Synchronisierung (Puffer auf DB anwenden)
        ok = fail = 0
        try:
            ok, fail = sync_buffer_once(self.conn)
        except Exception as e:
            QMessageBox.information(
                self,
                "Start",
                f"Die Start-Synchronisierung konnte nicht vollständig ausgeführt werden.\n\nDetails:\n{e}"
            )
        sb_msg = (
            f"Start: {ok} Eintrag(e) übernommen"
            + (f", {fail} noch offen" if fail else "")
        )

        # Tabs erstellen
        self.tabs = QTabWidget()

        def on_clinics_changed_cb():
            if hasattr(self, "tab_create"):
                self.tab_create._reload_clinics()

        # Admin-Bereich
        if self.role == "Admin":
            self.tab_admin = AdminTab(
                self.conn, current_user_id=self.user_id, on_clinics_changed=on_clinics_changed_cb
            )
            self.tabs.addTab(self.tab_admin, "Admin")

        # Erfassungs-Tab
        if self.role != "Viewer":
            self.tab_create = CreateTab(
                self.conn,
                role=self.role,
                clinics_csv=self.clinics_csv,
                submitter_default=self.username,
                current_username=self.username,
                current_user_id=self.user_id,
            )
            self.tab_create.case_created.connect(self._on_case_created)
            self.tabs.addTab(self.tab_create, "Erfassen")

        # Offene / erledigte Reparaturen
        self.tab_open = OpenTab(
            self.conn,
            role=self.role,
            clinics_csv=self.clinics_csv,
            read_only=(self.role == "Viewer"),
            current_username=self.username,
            current_user_id=self.user_id,
        )
        self.tab_done = DoneTab(
            self.conn,
            role=self.role,
            clinics_csv=self.clinics_csv,
            current_user_id=self.user_id,t
        )

        self.tab_open.case_completed.connect(self._on_case_completed)
        self.tab_done.case_reopened.connect(self._on_case_reopened)

        self.tabs.addTab(self.tab_open, "Offene Reparaturen")
        self.tabs.addTab(self.tab_done, "Erledigt")

        self.setCentralWidget(self.tabs)

        # Statusleiste
        sb = QStatusBar()
        self.setStatusBar(sb)
        sb.showMessage(sb_msg, 5000)

        # Theme anwenden
        apply_system_theme()
        try:
            QApplication.styleHints().colorSchemeChanged.connect(apply_system_theme)
        except Exception:
            pass

        # Initiale Aktualisierung
        self.tab_open.refresh()
        self.tab_done.refresh()

    def _on_case_created(self):
        self.tab_open.refresh()
        self.tabs.setCurrentWidget(self.tab_open)

    def _on_case_completed(self, _cid: int):
        self.tab_done.refresh()

    def _on_case_reopened(self, _cid: int):
        self.tab_open.refresh()


def run():
    """Startet die Anwendung: Theme setzen, Login anzeigen, Hauptfenster öffnen."""
    app = QApplication(sys.argv)
    apply_app_theme(app)

    try:
        app.styleHints().colorSchemeChanged.connect(lambda: apply_app_theme(app))
    except Exception:
        pass

    login = Login()
    login.show()
    app.exec()

    if getattr(login, "authed", None):
        uid, role, clinics_csv = login.authed
        uname = login.user.text().strip()
        win = Main(uid, role, clinics_csv, uname)
        win.show()
        sys.exit(app.exec())

    sys.exit(0)


if __name__ == "__main__":
    run()
