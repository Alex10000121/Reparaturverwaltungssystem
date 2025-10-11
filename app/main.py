# app/main.py
import sys
import os
import sqlite3

from PyQt6.QtWidgets import QApplication, QMainWindow, QTabWidget, QStatusBar, QMessageBox
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon

from app.backend.db.db import get_conn
from app.frontend.theme import apply_app_theme, apply_system_theme
from app.backend.helpers.buffer import sync_buffer_once
from app.frontend.widgets.login import Login
from app.frontend.tabs.create_tab import CreateTab
from app.frontend.tabs.open_tab import OpenTab
from app.frontend.tabs.done_tab import DoneTab
from app.frontend.tabs.admin_tab import AdminTab


def _base_dir() -> str:
    """Projektbasis ermitteln, auch im gefrorenen Zustand."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return base
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(relative: str) -> str:
    """Ressourcenpfad auflösen, egal ob Entwicklung oder Bundle."""
    return os.path.join(_base_dir(), relative)


class Main(QMainWindow):
    def __init__(self, user_id: int, role: str, clinics_csv: str, username: str):
        super().__init__()

        self.setWindowTitle("Reparaturverwaltungssoftware")
        self.resize(1280, 860)
        self.setWindowState(Qt.WindowState.WindowMaximized)

        # zentrales DB Handle
        self.conn: sqlite3.Connection = get_conn()

        self.user_id = user_id
        self.role = role
        self.clinics_csv = clinics_csv
        self.username = username

        # App Icon auch am Hauptfenster setzen (Taskleiste, Alt-Tab)
        icon_file = resource_path(os.path.join("app", "frontend", "assets", "app.ico"))
        if os.path.exists(icon_file):
            self.setWindowIcon(QIcon(icon_file))

        # Start Sync des Offline Puffers
        ok = fail = 0
        try:
            ok, fail = sync_buffer_once(self.conn)
        except Exception as e:
            QMessageBox.information(self, "Start Sync", f"Start Sync nicht abgeschlossen:\n{e}")

        sb_msg = f"Start Sync: {ok} synchronisiert" + (f", {fail} offen" if fail else "")

        # Tabs aufbauen
        self.tabs = QTabWidget()

        def on_clinics_changed_cb():
            if hasattr(self, "tab_create"):
                self.tab_create._reload_clinics()

        # Admin Tab
        if self.role == "Admin":
            self.tab_admin = AdminTab(
                self.conn,
                current_user_id=self.user_id,
                on_clinics_changed=on_clinics_changed_cb,
            )
            self.tabs.addTab(self.tab_admin, "Admin")

        # Erfassen Tab
        if self.role != "Viewer":
            self.tab_create = CreateTab(
                self.conn,
                role=self.role,
                clinics_csv=self.clinics_csv,
                submitter_default=self.username,
                current_username=self.username,
                current_user_id=self.user_id,  # für Audit user_id
            )
            self.tab_create.case_created.connect(self._on_case_created)
            self.tabs.addTab(self.tab_create, "Erfassen")

        # Offene und Erledigt
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
            current_user_id=self.user_id,
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

        # Theme initial setzen und auf Systemwechsel reagieren
        apply_system_theme()
        try:
            QApplication.styleHints().colorSchemeChanged.connect(apply_system_theme)
        except Exception:
            pass

        # erste Daten laden
        self.tab_open.refresh()
        self.tab_done.refresh()

        # sauberen Shutdown registrieren
        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self._shutdown)

    # Ereignisse aus Tabs
    def _on_case_created(self):
        self.tab_open.refresh()
        self.tabs.setCurrentWidget(self.tab_open)

    def _on_case_completed(self, _cid: int):
        self.tab_done.refresh()

    def _on_case_reopened(self, _cid: int):
        self.tab_open.refresh()

    # sauberes Beenden
    def closeEvent(self, event):
        self._shutdown()
        super().closeEvent(event)

    def _shutdown(self):
        """Schreibt anstehende Änderungen, versucht den Offline Puffer zu synchronisieren und schließt die DB."""
        if not hasattr(self, "conn") or self.conn is None:
            return
        try:
            try:
                sync_buffer_once(self.conn)
            except Exception:
                pass

            try:
                self.conn.commit()
            except Exception:
                pass

            # Bei WAL Betrieb sauber checkpointen
            try:
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except Exception:
                pass
        finally:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None


def run():
    app = QApplication(sys.argv)
    apply_app_theme(app)

    # App Icon global setzen
    icon_file = resource_path(os.path.join("app", "frontend", "assets", "app.ico"))
    if os.path.exists(icon_file):
        app.setWindowIcon(QIcon(icon_file))

    try:
        app.styleHints().colorSchemeChanged.connect(lambda: apply_app_theme(app))
    except Exception:
        pass

    login = Login()
    # auch beim Login das Icon sicherstellen
    if os.path.exists(icon_file):
        login.setWindowIcon(QIcon(icon_file))
    login.show()
    app.exec()

    if getattr(login, "authed", None):
        uid, role, clinics_csv = login.authed
        uname = login.user.text().strip()
        win = Main(uid, role, clinics_csv, uname)
        # Icon auch im Hauptfenster setzen, falls Theme oder Desktopumgebung dies erwartet
        if os.path.exists(icon_file):
            win.setWindowIcon(QIcon(icon_file))
        win.show()
        sys.exit(app.exec())


if __name__ == "__main__":
    run()
