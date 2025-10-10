# app/tabs/done_tab.py
import csv
import json
import sqlite3
from datetime import datetime
from typing import List, Tuple, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QWidget, QLineEdit, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QCheckBox, QMessageBox, QHBoxLayout,
    QPushButton, QStyle, QHeaderView, QFileDialog, QSizePolicy
)

from app.backend.helpers.helpers import clinics_of_user
from app.backend.helpers.buffer import enqueue_write


class DoneTab(QWidget):
    case_reopened = pyqtSignal(int)
    case_deleted = pyqtSignal(int)

    COL_TAGE = 0
    COL_KLINIK = 1
    COL_GERAET = 2
    COL_WAVE = 3
    COL_ABGEBER = 4
    COL_TECHNIKER = 5
    COL_GRUND = 6
    COL_ABGABE = 7
    COL_ZURUECK = 8
    COL_CREATEDBY = 9
    COL_CLOSEDBY = 10
    COL_NOTES = 11
    COL_REOPEN = 12
    COL_DELETE = 13

    def __init__(self, conn: sqlite3.Connection, role: str, clinics_csv: str):
        super().__init__()
        self.conn = conn
        self.allowed = clinics_of_user(role, clinics_csv)
        self.read_only = (role == "Viewer")
        self.is_admin = (role == "Admin")

        self._created_by_expr, self._closed_by_expr, self._notes_expr = self._detect_column_exprs()

        self.search = QLineEdit(placeholderText="Suchen …")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.btn_export = QPushButton("Exportieren")
        self.btn_export.setFixedHeight(32)
        self.btn_export.clicked.connect(self._export_done_cases)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.search, stretch=1)
        top.addWidget(self.btn_export)

        self.table = QTableWidget()
        self.table.setColumnCount(14)
        self.table.setHorizontalHeaderLabels([
            "Tage in Reparatur", "Klinik", "Gerät", "Wave- / Seriennummer", "Abgeber", "Techniker",
            "Grund", "Abgabe", "Zurück", "Angelegt von", "Erledigt von", "Notizen",
            "Wieder öffnen?", "Löschen"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(True)

        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(self.COL_TAGE, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(self.COL_ABGABE, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(self.COL_ZURUECK, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setMinimumSectionSize(70)
        self.table.setColumnWidth(self.COL_TAGE, 165)
        self.table.setColumnWidth(self.COL_ABGABE, 130)
        self.table.setColumnWidth(self.COL_ZURUECK, 130)

        if not self.is_admin:
            self.table.setColumnHidden(self.COL_DELETE, True)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.table)

        self._first_refresh = True
        self.refresh()

    def _detect_column_exprs(self) -> tuple[str, str, str]:
        try:
            cur = self.conn.cursor()
            cur.execute("PRAGMA table_info(cases);")
            cols = {row[1] for row in cur.fetchall()}
        except Exception:
            cols = set()
        created_expr = "created_by" if "created_by" in cols else "''"
        closed_expr  = "closed_by"  if "closed_by"  in cols else "''"
        notes_expr   = "notes"      if "notes"      in cols else "''"
        return created_expr, closed_expr, notes_expr

    def _scope_filter_sql(self) -> tuple[str, tuple]:
        if self.allowed is None:
            return "WHERE status='Abgeschlossen'", ()
        qmarks = ",".join("?" * len(self.allowed))
        return f"WHERE status='Abgeschlossen' AND clinic IN ({qmarks})", tuple(self.allowed)

    def _fetch(self) -> List[Tuple]:
        where_sql, params = self._scope_filter_sql()
        cur = self.conn.cursor()
        rows = cur.execute(
            f"""SELECT id, clinic, device_name, wave_number, submitter, service_provider,
                        reason, date_submitted, date_returned,
                        {self._created_by_expr} AS created_by,
                        {self._closed_by_expr}  AS closed_by,
                        {self._notes_expr}      AS notes
                 FROM cases {where_sql}
                 ORDER BY id DESC""",
            params
        ).fetchall()
        return rows

    def _centered_widget(self, w) -> QWidget:
        wrapper = QWidget()
        lay = QHBoxLayout(wrapper)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(w)
        return wrapper

    def refresh(self):
        rows = self._fetch()

        q = self.search.text().strip().lower()
        if q:
            rows = [r for r in rows if any(
                (str(x or "").lower().find(q) >= 0)
                for x in (
                    r[self.COL_KLINIK], r[self.COL_GERAET], r[self.COL_WAVE], r[self.COL_ABGEBER],
                    r[self.COL_TECHNIKER], r[self.COL_GRUND], r[self.COL_ABGABE], r[self.COL_ZURUECK],
                    r[self.COL_CREATEDBY], r[self.COL_CLOSEDBY], r[self.COL_NOTES]
                )
            )]

        header = self.table.horizontalHeader()
        sort_section = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))

        for r, row in enumerate(rows):
            internal_id = int(row[0]) if row and row[0] is not None else 0

            for c in range(self.COL_REOPEN):
                val = row[c] if c < len(row) else None
                full_text = "" if val is None else str(val)

                if c == self.COL_TAGE:
                    # 🔧 WICHTIG: DisplayRole als INT setzen → numerische Sortierung
                    days = self._days_between(str(row[self.COL_ABGABE] or ""), str(row[self.COL_ZURUECK] or ""))
                    item = QTableWidgetItem()
                    if days is None:
                        item.setData(Qt.ItemDataRole.DisplayRole, -1)  # sentinel, bleibt numerisch
                        item.setToolTip("Kein gültiger Zeitraum (Abgabe oder Zurück fehlt)")
                    else:
                        item.setData(Qt.ItemDataRole.DisplayRole, int(days))
                        item.setToolTip(f"Insgesamt {int(days)} Tag(e) in Reparatur")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                else:
                    display = full_text
                    if c == self.COL_NOTES and len(full_text) > 200:
                        display = full_text[:200] + "…"
                    item = QTableWidgetItem(display)
                    item.setToolTip(full_text or "")
                    if c in (self.COL_ABGABE, self.COL_ZURUECK):
                        item.setData(Qt.ItemDataRole.UserRole, self._date_sort_key(full_text))
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    else:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, c, item)

            chk = QCheckBox()
            chk.setText("")
            chk.setEnabled(not self.read_only)
            chk.setProperty("case_id", internal_id)
            chk.clicked.connect(self._on_reopen_clicked)
            self.table.setCellWidget(r, self.COL_REOPEN, self._centered_widget(chk))

            if self.is_admin:
                btn = QPushButton()
                btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
                btn.setToolTip("Eintrag löschen")
                btn.clicked.connect(lambda _=False, cid=internal_id: self._on_delete(cid))
                self.table.setCellWidget(r, self.COL_DELETE, self._centered_widget(btn))

        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(self.COL_TAGE, max(self.table.columnWidth(self.COL_TAGE), 165))
        self.table.setColumnWidth(self.COL_ABGABE, max(self.table.columnWidth(self.COL_ABGABE), 130))
        self.table.setColumnWidth(self.COL_ZURUECK, max(self.table.columnWidth(self.COL_ZURUECK), 130))

        self.table.setSortingEnabled(True)
        if self._first_refresh:
            self.table.sortItems(self.COL_TAGE, Qt.SortOrder.DescendingOrder)
            self._first_refresh = False
        else:
            self.table.sortItems(sort_section, sort_order)

    def _export_done_cases(self):
        path, _ = QFileDialog.getSaveFileName(self, "CSV exportieren (erledigt)", "erledigt.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            where_sql, params = self._scope_filter_sql()
            cur = self.conn.cursor()
            rows = cur.execute(
                f"""
                SELECT id, clinic, device_name, wave_number, submitter, service_provider,
                       reason, date_submitted, date_returned
                FROM cases
                {where_sql}
                ORDER BY id DESC
                """,
                params,
            ).fetchall()

            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow([
                    "ID", "Klinik", "Gerät", "Wave- / Seriennummer",
                    "Abgeber", "Techniker", "Grund", "Abgabe", "Zurück"
                ])
                w.writerows(rows)

            QMessageBox.information(self, "Export", "Die erledigten Reparaturen wurden erfolgreich exportiert.")
        except Exception as e:
            QMessageBox.warning(self, "Export nicht möglich", f"Die CSV-Datei konnte nicht erstellt werden.\n\nDetails:\n{e}")

    def _on_reopen_clicked(self, checked: bool):
        if not checked:
            return
        sender = self.sender()
        if not isinstance(sender, QCheckBox):
            return
        case_id = sender.property("case_id")
        if case_id is None:
            return
        case_id = int(case_id)
        device_label = self._device_label(case_id)
        sender.setEnabled(False)

        def offline_reset():
            sender.blockSignals(True)
            sender.setChecked(False)
            sender.blockSignals(False)
            sender.setEnabled(True)
            QMessageBox.information(
                self, "Offline gespeichert",
                "Die Datenbank war nicht erreichbar. Die Änderung wird beim nächsten Start synchronisiert."
            )

        try:
            with self.conn:
                self._ensure_case_columns(["status", "date_returned", "closed_by"])
                self.conn.execute(
                    "UPDATE cases SET status='In Reparatur', date_returned=NULL, closed_by=NULL WHERE id=?",
                    (case_id,)
                )
                self.conn.execute(
                    "INSERT INTO audit_log(action, entity, entity_id, details) VALUES(?,?,?,?)",
                    ("case_update", "case", case_id, json.dumps(
                        {"status": "In Reparatur", "date_returned": None, "closed_by": None},
                        ensure_ascii=False
                    ))
                )
            QTimer.singleShot(0, lambda: self._after_reopen_success(case_id, device_label))
        except Exception:
            enqueue_write({
                "type": "update_case",
                "id": case_id,
                "date_returned": None,
                "status": "In Reparatur",
                "closed_by": None
            })
            QTimer.singleShot(0, offline_reset)

    def _on_delete(self, case_id: int):
        if not self.is_admin:
            return
        ok = QMessageBox.question(
            self, "Löschen bestätigen",
            f"Fall {case_id} wirklich löschen? Dieser Schritt kann nicht rückgängig gemacht werden."
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        try:
            with self.conn:
                self.conn.execute("DELETE FROM cases WHERE id=?", (case_id,))
                self.conn.execute(
                    "INSERT INTO audit_log(action, entity, entity_id, details) VALUES(?,?,?,?)",
                    ("case_delete", "case", case_id, json.dumps({"id": case_id}, ensure_ascii=False))
                )
            self.case_deleted.emit(case_id)
            self.refresh()
        except Exception:
            QMessageBox.warning(
                self,
                "Löschen nicht möglich",
                "Löschen ist derzeit nicht möglich, weil die Datenbank gesperrt ist. Bitte später erneut versuchen."
            )

    def _after_reopen_success(self, case_id: int, device_label: str):
        self.case_reopened.emit(case_id)
        self.refresh()
        QMessageBox.information(self, "Geöffnet", f"Gerät „{device_label}“ wurde wieder geöffnet.")

    def _date_sort_key(self, s: Optional[str]) -> int:
        if not s:
            return -10**9
        try:
            dt = datetime.fromisoformat(s.strip())
            return (dt - datetime(1970, 1, 1)).days
        except Exception:
            return -10**9

    def _days_between(self, start: Optional[str], end: Optional[str]) -> Optional[int]:
        if not start or not end:
            return None
        try:
            d1 = datetime.fromisoformat(start.strip())
            d2 = datetime.fromisoformat(end.strip())
            return max(0, (d2 - d1).days)
        except Exception:
            return None

    def _device_label(self, case_id: int) -> str:
        try:
            cur = self.conn.cursor()
            row = cur.execute(
                "SELECT device_name, wave_number FROM cases WHERE id=?",
                (case_id,)
            ).fetchone()
        except Exception:
            row = None
        if not row:
            return f"ID {case_id}"
        name, wave = row
        name = (name or "").strip()
        wave = (wave or "").strip()
        return f"{name} ({wave})" if wave else (name or f"ID {case_id}")

    def _ensure_case_columns(self, names: list[str]) -> None:
        cur = self.conn.cursor()
        cur.execute("PRAGMA table_info(cases);")
        existing = {row[1] for row in cur.fetchall()}
        for n in names:
            if n not in existing:
                self.conn.execute(f"ALTER TABLE cases ADD COLUMN {n} TEXT")
