import json, sqlite3
from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QLineEdit, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QCheckBox, QAbstractItemView, QMessageBox, QHBoxLayout
)
from app.helpers import clinics_of_user
from app.buffer import enqueue_write

class OpenTab(QWidget):
    case_completed = pyqtSignal(int)

    def __init__(self, conn: sqlite3.Connection, role: str, clinics_csv: str, read_only: bool):
        super().__init__()
        self.conn = conn
        self.read_only = read_only
        self.allowed = clinics_of_user(role, clinics_csv)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Suchen ...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)

        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels([
            "ID","Klinik","Gerät","Wavenummer / Seriennummer","Abgeber","Techniker",
            "Grund","Abgabe","Zurück","Erledigt?"
        ])
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setStretchLastSection(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self.search)
        layout.addWidget(self.table)

        self.refresh()

    def _scope_filter_sql(self):
        if self.allowed is None:
            return "WHERE status='In Reparatur'", ()
        qmarks = ",".join("?" * len(self.allowed))
        return f"WHERE status='In Reparatur' AND clinic IN ({qmarks})", tuple(self.allowed)

    def _fetch(self):
        where_sql, params = self._scope_filter_sql()
        cur = self.conn.cursor()
        rows = cur.execute(
            f"""SELECT id, clinic, device_name, wave_number, submitter, service_provider,
                        reason, date_submitted, date_returned
                 FROM cases {where_sql}
                 ORDER BY id DESC""",
            params
        ).fetchall()
        return rows

    def _centered_checkbox_widget(self, checkbox: QCheckBox) -> QWidget:
        # Checkbox mittig in der Zelle ausrichten
        wrapper = QWidget()
        lay = QHBoxLayout(wrapper)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(checkbox)
        return wrapper

    def refresh(self):
        rows = self._fetch()
        q = self.search.text().strip().lower()
        if q:
            rows = [r for r in rows if any((str(x or "").lower().find(q) >= 0) for x in (r[1], r[2], r[3], r[4], r[5]))]
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row + (None,)):
                if c < 9:
                    text = "" if val is None else str(val)
                    item = QTableWidgetItem(text)
                    item.setToolTip(text)
                    if c == 0:  # ID
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    elif c in (7, 8):  # Datumsspalten
                        item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter)
                    else:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                    self.table.setItem(r, c, item)
                else:
                    chk = QCheckBox()
                    chk.setText("")  # kein Text in der Zelle, Überschrift kommt aus Header
                    chk.setEnabled(not self.read_only)
                    case_id = int(row[0])

                    def on_checked(state, cid=case_id, widget=chk):
                        if state != 2:
                            return
                        today = QDate.currentDate().toString("yyyy-MM-dd")
                        try:
                            with self.conn:
                                self.conn.execute(
                                    "UPDATE cases SET status='Abgeschlossen', date_returned=? WHERE id=?",
                                    (today, cid)
                                )
                                self.conn.execute(
                                    "INSERT INTO audit_log(action, entity, entity_id, details) VALUES(?,?,?,?)",
                                    ("case_update", "case", cid, json.dumps(
                                        {"status": "Abgeschlossen", "date_returned": today}, ensure_ascii=False
                                    ))
                                )
                            self.refresh()
                            self.case_completed.emit(cid)
                            QMessageBox.information(self, "Erledigt", f"Fall {cid} wurde abgeschlossen.")
                        except Exception:
                            enqueue_write({"type": "update_case", "id": cid,
                                           "date_returned": today, "status": "Abgeschlossen"})
                            QMessageBox.information(
                                self, "Offline gespeichert",
                                "Die DB war nicht erreichbar/gesperrt.\nDie Änderung wurde offline gespeichert und wird beim NÄCHSTEN Start synchronisiert."
                            )
                            widget.blockSignals(True); widget.setChecked(False); widget.blockSignals(False)

                    chk.stateChanged.connect(on_checked)
                    self.table.setCellWidget(r, 9, self._centered_checkbox_widget(chk))

        self.table.resizeColumnsToContents()
