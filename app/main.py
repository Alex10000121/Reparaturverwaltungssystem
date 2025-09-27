# app/main.py
import sys, sqlite3, csv
from PyQt6.QtWidgets import QApplication, QMainWindow, QTabWidget, QToolBar, QStatusBar, QFileDialog, QMessageBox
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt
from db import get_conn
from app.theme import apply_app_theme, apply_system_theme
from app.buffer import sync_buffer_once
from app.widgets.login import Login
from app.tabs.create_tab import CreateTab
from app.tabs.open_tab import OpenTab
from app.tabs.done_tab import DoneTab
from app.tabs.admin_tab import AdminTab


class Main(QMainWindow):
    def __init__(self, user_id: int, role: str, clinics_csv: str, username: str):
        super().__init__()
        self.setWindowTitle("Reparaturverwaltungssoftware")
        self.resize(1280, 860)
        self.conn: sqlite3.Connection = get_conn()
        self.user_id, self.role, self.clinics_csv, self.username = user_id, role, clinics_csv, username
        self.setWindowState(Qt.WindowState.WindowMaximized)

        ok, fail = (0, 0)
        try:
            ok, fail = sync_buffer_once(self.conn)
        except Exception as e:
            QMessageBox.information(self, "Start-Sync", f"Start-Sync nicht abgeschlossen:\n{e}")
        sb_msg = f"Start-Sync: {ok} synchronisiert" + (f", {fail} offen" if fail else "")

        tb = QToolBar("Aktionen"); self.addToolBar(tb)
        act_export_open = QAction("Offene exportieren", self)
        act_export_done = QAction("Erledigte exportieren", self)
        act_export_open.triggered.connect(self.export_open)
        act_export_done.triggered.connect(self.export_done)
        tb.addAction(act_export_open); tb.addAction(act_export_done)

        self.tabs = QTabWidget()

        def on_clinics_changed_cb():
            if hasattr(self, "tab_create"):
                self.tab_create._reload_clinics()

        if self.role == "Admin":
            self.tab_admin = AdminTab(self.conn, current_user_id=self.user_id, on_clinics_changed=on_clinics_changed_cb)
            self.tabs.addTab(self.tab_admin, "Admin")

        if self.role != "Viewer":
            self.tab_create = CreateTab(
                self.conn,
                role=self.role,
                clinics_csv=self.clinics_csv,
                submitter_default=self.username,
                current_username=self.username,
            )
            self.tab_create.case_created.connect(self._on_case_created)
            self.tabs.addTab(self.tab_create, "Erfassen")

        self.tab_open = OpenTab(
            self.conn,
            role=self.role,
            clinics_csv=self.clinics_csv,
            read_only=(self.role == "Viewer"),
            current_username=self.username,
        )
        self.tab_done = DoneTab(self.conn, role=self.role, clinics_csv=self.clinics_csv)
        self.tab_open.case_completed.connect(self._on_case_completed)
        self.tab_done.case_reopened.connect(self._on_case_reopened)

        self.tabs.addTab(self.tab_open, "Offene Reparaturen")
        self.tabs.addTab(self.tab_done, "Erledigt")
        self.setCentralWidget(self.tabs)

        sb = QStatusBar(); self.setStatusBar(sb); sb.showMessage(sb_msg, 5000)

        apply_system_theme()
        try:
            QApplication.styleHints().colorSchemeChanged.connect(apply_system_theme)
        except Exception:
            pass

        self.tab_open.refresh(); self.tab_done.refresh()

    def _on_case_created(self):
        self.tab_open.refresh()
        self.tabs.setCurrentWidget(self.tab_open)

    def _on_case_completed(self, _cid: int):
        self.tab_done.refresh()

    def _on_case_reopened(self, _cid: int):
        self.tab_open.refresh()

    # --- Export ---
    def export_open(self):
        path, _ = QFileDialog.getSaveFileName(self, "CSV exportieren (offen)", "offene.csv", "CSV (*.csv)")
        if not path: return
        cur = self.conn.cursor()
        if self.role == "Admin" or self.clinics_csv == "ALL":
            rows = cur.execute(
                """SELECT id, clinic, device_name, wave_number, submitter, service_provider, reason, date_submitted
                   FROM cases WHERE status='In Reparatur' ORDER BY id DESC"""
            ).fetchall()
        else:
            allowed = [c.strip() for c in self.clinics_csv.split(",") if c.strip()]
            qmarks = ",".join("?"*len(allowed))
            rows = cur.execute(
                f"""SELECT id, clinic, device_name, wave_number, submitter, service_provider, reason, date_submitted
                    FROM cases WHERE status='In Reparatur' AND clinic IN ({qmarks}) ORDER BY id DESC""",
                tuple(allowed)
            ).fetchall()
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["ID","Klinik","Gerät","Wave- / Serienummer","Abgeber","Techniker","Grund","Abgabe"])  # <-- geändert
            w.writerows(rows)
        QMessageBox.information(self, "Export", "Export abgeschlossen.")

    def export_done(self):
        path, _ = QFileDialog.getSaveFileName(self, "CSV exportieren (erledigt)", "erledigt.csv", "CSV (*.csv)")
        if not path: return
        cur = self.conn.cursor()
        if self.role == "Admin" or self.clinics_csv == "ALL":
            rows = cur.execute(
                """SELECT id, clinic, device_name, wave_number, submitter, service_provider, reason,
                          date_submitted, date_returned
                   FROM cases WHERE status='Abgeschlossen' ORDER BY id DESC"""
            ).fetchall()
        else:
            allowed = [c.strip() for c in self.clinics_csv.split(",") if c.strip()]
            qmarks = ",".join("?"*len(allowed))
            rows = cur.execute(
                f"""SELECT id, clinic, device_name, wave_number, submitter, service_provider, reason,
                           date_submitted, date_returned
                    FROM cases WHERE status='Abgeschlossen' AND clinic IN ({qmarks}) ORDER BY id DESC""",
                tuple(allowed)
            ).fetchall()
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["ID","Klinik","Gerät","Wave- / Serienummer","Abgeber","Techniker","Grund","Abgabe","Zurück"])  # <-- geändert
            w.writerows(rows)
        QMessageBox.information(self, "Export", "Export abgeschlossen.")


def run():
    app = QApplication(sys.argv)
    apply_app_theme(app)
    try:
        app.styleHints().colorSchemeChanged.connect(lambda: apply_app_theme(app))
    except Exception:
        pass

    login = Login(); login.show(); app.exec()
    if getattr(login, 'authed', None):
        uid, role, clinics_csv = login.authed
        uname = login.user.text().strip()
        win = Main(uid, role, clinics_csv, uname)
        win.show()
        sys.exit(app.exec())

if __name__ == "__main__":
    run()
