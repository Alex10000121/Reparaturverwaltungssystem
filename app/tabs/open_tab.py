# app/tabs/open_tab.py
import json
import sqlite3
from datetime import datetime, timezone
from typing import List, Tuple, Optional

from PyQt6.QtCore import QDate, Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import (
    QWidget, QLineEdit, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QCheckBox, QAbstractItemView, QMessageBox, QHBoxLayout
)

from app.helpers import clinics_of_user
from app.buffer import enqueue_write

DATE_INPUT_FORMATS = (
    "%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S",
    "%d.%m.%Y", "%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S",
)


class OpenTab(QWidget):
    case_completed = pyqtSignal(int)

    # Spalten-Indices
    COL_ID = 0
    COL_CLINIC = 1
    COL_DEVICE = 2
    COL_WAVE = 3
    COL_SUBMITTER = 4
    COL_PROVIDER = 5
    COL_REASON = 6
    OPEN_DATE_COL = 7          # "Abgabe"
    COL_CREATED_BY = 8
    COL_NOTES = 9
    COL_DONE = 10

    def __init__(
        self,
        conn: sqlite3.Connection,
        role: str,
        clinics_csv: str,
        read_only: bool,
        current_username: Optional[str] = None,
    ):
        super().__init__()
        self.conn = conn
        self.read_only = read_only
        self.allowed = clinics_of_user(role, clinics_csv)
        self.current_username = current_username or ""
        self._created_by_expr, self._notes_expr = self._detect_column_exprs()

        self.search = QLineEdit(placeholderText="Suchen ...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)

        self.table = QTableWidget()
        self.table.setColumnCount(11)
        self.table.setHorizontalHeaderLabels([
            "ID", "Klinik", "Gerät", "Wave- / Serienummer", "Abgeber", "Techniker",
            "Grund", "Abgabe", "Angelegt von", "Notizen", "Erledigt?"
        ])
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSortingEnabled(True)  # Sortieren per Header-Klick

        lay = QVBoxLayout(self)
        lay.addWidget(self.search)
        lay.addWidget(self.table)

        self._first_refresh = True
        self.refresh()

    # ---------------------------
    # Schema/Meta
    # ---------------------------
    def _detect_column_exprs(self) -> tuple[str, str]:
        """Erkennt Spalten für 'Angelegt von' (created_by) und 'Notizen' (notes); Fallback: leerer String."""
        try:
            cur = self.conn.cursor()
            cur.execute("PRAGMA table_info(cases);")
            cols = {row[1] for row in cur.fetchall()}
        except Exception:
            cols = set()
        created_expr = "created_by" if "created_by" in cols else "''"
        notes_expr = "notes" if "notes" in cols else "''"
        return created_expr, notes_expr

    # ---------------------------
    # Datenbeschaffung + Filter
    # ---------------------------
    def _scope_filter_sql(self) -> tuple[str, tuple]:
        if self.allowed is None:
            return "WHERE status='In Reparatur'", ()
        qmarks = ",".join("?" * len(self.allowed))
        return f"WHERE status='In Reparatur' AND clinic IN ({qmarks})", tuple(self.allowed)

    def _fetch(self) -> List[Tuple]:
        where_sql, params = self._scope_filter_sql()
        cur = self.conn.cursor()
        rows = cur.execute(
            f"""SELECT id, clinic, device_name, wave_number, submitter, service_provider,
                        reason, date_submitted, {self._created_by_expr} AS created_by, {self._notes_expr} AS notes
                 FROM cases {where_sql}
                 ORDER BY id DESC""",
            params
        ).fetchall()
        return rows

    # ---------------------------
    # Rendering / UI
    # ---------------------------
    def _centered_checkbox_widget(self, checkbox: QCheckBox) -> QWidget:
        wrapper = QWidget()
        lay = QHBoxLayout(wrapper)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(checkbox)
        return wrapper

    def refresh(self):
        rows = self._fetch()

        # Textsuche
        q = self.search.text().strip().lower()
        if q:
            rows = [r for r in rows if any(
                (str(x or "").lower().find(q) >= 0)
                for x in (r[self.COL_CLINIC], r[self.COL_DEVICE], r[self.COL_WAVE],
                          r[self.COL_SUBMITTER], r[self.COL_PROVIDER], r[self.COL_CREATED_BY], r[self.COL_NOTES])
            )]

        # Sortierinfo (beibehalten)
        header = self.table.horizontalHeader()
        sort_section = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))

        for r, row in enumerate(rows):
            # Textspalten
            for c, val in enumerate(row):
                full_text = "" if val is None else str(val)
                display_text = full_text
                if c == self.COL_NOTES and len(full_text) > 200:
                    display_text = full_text[:200] + "…"

                item = QTableWidgetItem(display_text)
                item.setToolTip(full_text)

                # Sortier-Keys
                if c == self.COL_ID:
                    try:
                        item.setData(Qt.ItemDataRole.UserRole, int(full_text or "0"))
                    except ValueError:
                        item.setData(Qt.ItemDataRole.UserRole, 0)
                elif c == self.OPEN_DATE_COL:
                    item.setData(Qt.ItemDataRole.UserRole, self._date_to_julian(full_text))

                # Ausrichtung
                if c == self.COL_ID:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                elif c == self.OPEN_DATE_COL:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter)
                else:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, c, item)

            # Checkbox "Erledigt?" (zentriert)
            chk = QCheckBox()
            chk.setEnabled(not self.read_only)
            chk.setTristate(False)
            chk.setChecked(False)
            chk.setText("")
            chk.setProperty("case_id", int(row[self.COL_ID]))
            chk.clicked.connect(self._on_done_clicked)
            self.table.setCellWidget(r, self.COL_DONE, self._centered_checkbox_widget(chk))

            # ID-Zelle nach Alter einfärben
            self._apply_age_color_to_row(r)

        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)

        # Standard: älteste (am längsten offen) oben
        if self._first_refresh:
            self.table.sortItems(self.OPEN_DATE_COL, Qt.SortOrder.AscendingOrder)
            self._first_refresh = False
        else:
            # Benutzerwahl beibehalten
            self.table.sortItems(sort_section, sort_order)

    # ---------------------------
    # Abschluss-Checkbox Handler
    # ---------------------------
    def _on_done_clicked(self, checked: bool):
        if not checked:
            return
        sender = self.sender()
        if not isinstance(sender, QCheckBox):
            return
        cid = sender.property("case_id")
        if cid is None:
            return

        case_id = int(cid)
        device_label = self._device_label(case_id)  # Gerät für die Meldung auflösen
        sender.setEnabled(False)
        today = QDate.currentDate().toString("yyyy-MM-dd")

        try:
            with self.conn:
                # Spalten ggf. nachrüsten
                self._ensure_case_columns(["status", "date_returned", "closed_by"])
                # Status + Rückgabedatum + wer erledigt hat
                self.conn.execute(
                    "UPDATE cases SET status='Abgeschlossen', date_returned=?, closed_by=? WHERE id=?",
                    (today, self.current_username, case_id)
                )
                # Audit
                self.conn.execute(
                    "INSERT INTO audit_log(action, entity, entity_id, details) VALUES(?,?,?,?)",
                    ("case_update", "case", case_id, json.dumps(
                        {"status": "Abgeschlossen", "date_returned": today, "closed_by": self.current_username},
                        ensure_ascii=False
                    ))
                )

            QTimer.singleShot(0, lambda cid=case_id, label=device_label: self._after_done_success(cid, label))

        except Exception:
            # Offline-Fallback
            enqueue_write({
                "type": "update_case",
                "id": case_id,
                "date_returned": today,
                "status": "Abgeschlossen",
                "closed_by": self.current_username,
            })
            QTimer.singleShot(0, lambda: self._after_done_offline(sender))

    def _after_done_success(self, case_id: int, device_label: str):
        self.case_completed.emit(case_id)
        self.refresh()
        QMessageBox.information(self, "Erledigt", f"Gerät „{device_label}“ wurde abgeschlossen und verschoben.")

    def _after_done_offline(self, checkbox: QCheckBox):
        checkbox.blockSignals(True)
        checkbox.setChecked(False)
        checkbox.blockSignals(False)
        checkbox.setEnabled(True)
        QMessageBox.information(
            self, "Offline gespeichert",
            "Die DB war nicht erreichbar/gesperrt.\nDie Änderung wurde offline gespeichert und wird beim NÄCHSTEN Start synchronisiert."
        )

    # ---------------------------
    # Farblogik (nur ID-Spalte)
    # ---------------------------
    def _apply_age_color_to_row(self, row_index: int) -> None:
        date_str = self._cell_text(row_index, self.OPEN_DATE_COL)
        days_open = self._days_since(date_str)
        brush = self._brush_for_days(days_open)
        if brush:
            it = self.table.item(row_index, self.COL_ID)
            if it:
                it.setBackground(brush)

    # ---------------------------
    # Helpers
    # ---------------------------
    def _device_label(self, case_id: int) -> str:
        """Liest eine sprechende Gerätebezeichnung für Meldungen (z. B. 'Endoskop (123456)')."""
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
        label = (name or "").strip() or f"ID {case_id}"
        wave = (wave or "").strip()
        return f"{label} ({wave})" if wave else label

    def _cell_text(self, row: int, col: int) -> Optional[str]:
        if row < 0 or col < 0 or col >= self.table.columnCount():
            return None
        it = self.table.item(row, col)
        return it.text() if it else None

    def _date_to_julian(self, s: Optional[str]) -> int:
        """Konvertiert Datum in 'Tage seit 1970-01-01' für sortierbaren Key."""
        if not s:
            return 10**9
        s = s.strip()

        dt: Optional[datetime] = None
        try:
            dt = datetime.strptime(s, "%Y-%m-%d")
        except Exception:
            for fmt in DATE_INPUT_FORMATS[1:]:
                try:
                    dt = datetime.strptime(s, fmt)
                    break
                except Exception:
                    continue
        if dt is None:
            return 10**9
        return (dt - datetime(1970, 1, 1)).days

    def _days_since(self, date_str: Optional[str]) -> Optional[int]:
        if not date_str:
            return None
        dt = self._parse_date(date_str)
        if not dt:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return max(0, (now - dt).days)

    def _parse_date(self, s: str) -> Optional[datetime]:
        s = s.strip()
        for fmt in DATE_INPUT_FORMATS:
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    def _brush_for_days(self, days: Optional[int]) -> Optional[QBrush]:
        if days is None:
            return None
        if days <= 30:
            return QBrush(QColor(0, 200, 0))     # kräftiges Grün
        if days <= 60:
            return QBrush(QColor(255, 200, 0))   # kräftiges Gelb/Orange
        return QBrush(QColor(220, 0, 0))         # kräftiges Rot

    def _ensure_case_columns(self, names: list[str]) -> None:
        cur = self.conn.cursor()
        cur.execute("PRAGMA table_info(cases);")
        existing = {row[1] for row in cur.fetchall()}
        for n in names:
            if n not in existing:
                if n == "status":
                    self.conn.execute("ALTER TABLE cases ADD COLUMN status TEXT DEFAULT 'In Reparatur'")
                elif n == "date_returned":
                    self.conn.execute("ALTER TABLE cases ADD COLUMN date_returned TEXT")
                elif n == "closed_by":
                    self.conn.execute("ALTER TABLE cases ADD COLUMN closed_by TEXT")
                else:
                    self.conn.execute(f"ALTER TABLE cases ADD COLUMN {n} TEXT")
