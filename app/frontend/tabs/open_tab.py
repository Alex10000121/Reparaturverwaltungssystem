# app/tabs/open_tab.py
import csv
import json
import sqlite3
from datetime import datetime, timezone
from typing import List, Tuple, Optional

from PyQt6.QtCore import QDate, Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QBrush, QFontMetrics
from PyQt6.QtWidgets import (
    QWidget, QLineEdit, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QCheckBox, QAbstractItemView, QMessageBox, QHBoxLayout, QHeaderView,
    QPushButton, QFileDialog, QSizePolicy, QStyle
)

from app.backend.helpers.helpers import clinics_of_user
from app.backend.helpers.buffer import enqueue_write

DATE_INPUT_FORMATS = (
    "%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S",
    "%d.%m.%Y", "%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S",
)


class OpenTab(QWidget):
    case_completed = pyqtSignal(int)

    # Spalten-Indices (Anzeige)
    COL_TAGE = 0
    COL_CLINIC = 1
    COL_DEVICE = 2
    COL_WAVE = 3
    COL_SUBMITTER = 4
    COL_PROVIDER = 5
    COL_REASON = 6
    COL_ABGABE = 7
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

        # Suche
        self.search = QLineEdit(placeholderText="Suchen …")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Export rechts neben der Suche
        self.btn_export = QPushButton("Exportieren")
        self.btn_export.setFixedHeight(32)
        self.btn_export.clicked.connect(self._export_open_cases)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.search, stretch=1)
        top.addWidget(self.btn_export)

        # Tabelle
        self.table = QTableWidget()
        self.table.setColumnCount(11)
        self.table.setHorizontalHeaderLabels([
            "Tage offen", "Klinik", "Gerät", "Wave- / Serienummer", "Abgeber", "Techniker",
            "Grund", "Abgabe", "Angelegt von", "Notizen", "Erledigt?"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(True)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        # Header einstellen
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)  # auto nach Inhalt und Header
        hdr.setStretchLastSection(True)                                    # letzte Spalte füllt Rest
        hdr.setTextElideMode(Qt.TextElideMode.ElideNone)                   # Header nie abschneiden
        hdr.setMinimumSectionSize(50)
        # Bei Sortwechsel erste Spalte neu vermessen und fixieren (Sortpfeil kann Breite ändern)
        hdr.sortIndicatorChanged.connect(lambda *_: self._lock_first_header_width())

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.table)

        self._first_refresh = True
        self.refresh()
        # Direkt nach dem ersten Aufbau nochmals fixieren
        self._lock_first_header_width()

    # ---------------- Schema / Meta ----------------
    def _detect_column_exprs(self) -> tuple[str, str]:
        try:
            cur = self.conn.cursor()
            cur.execute("PRAGMA table_info(cases);")
            cols = {row[1] for row in cur.fetchall()}
        except Exception:
            cols = set()
        created_expr = "created_by" if "created_by" in cols else "''"
        notes_expr = "notes" if "notes" in cols else "''"
        return created_expr, notes_expr

    # ---------------- Daten ----------------
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

    # ---------------- UI ----------------
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
                          r[self.COL_SUBMITTER], r[self.COL_PROVIDER],
                          r[self.COL_CREATED_BY], r[self.COL_NOTES])
            )]

        # Sortierzustand merken
        header = self.table.horizontalHeader()
        sort_section = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))

        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                full_text = "" if val is None else str(val)

                if c == self.COL_TAGE:
                    # numerisch sortierbar: Integer im DisplayRole
                    date_str = str(row[self.COL_ABGABE] or "")
                    days_open = self._days_since(date_str)
                    item = QTableWidgetItem()
                    if days_open is None:
                        item.setData(Qt.ItemDataRole.DisplayRole, -1)  # sentinel, bleibt numerisch
                        item.setToolTip("Kein gültiges Abgabedatum")
                    else:
                        item.setData(Qt.ItemDataRole.DisplayRole, int(days_open))
                        item.setToolTip(f"{int(days_open)} Tag(e) seit Abgabe")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                else:
                    text = full_text
                    if c == self.COL_NOTES and len(full_text) > 200:
                        text = full_text[:200] + "…"
                    item = QTableWidgetItem(text)
                    item.setToolTip(full_text or "Keine Notiz vorhanden")
                    if c == self.COL_ABGABE:
                        item.setData(Qt.ItemDataRole.UserRole, self._date_to_julian(full_text))
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    else:
                        # linksbündig für alle übrigen Spalten
                        item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, c, item)

            # Checkbox „Erledigt?“ (zentriert)
            chk = QCheckBox()
            chk.setEnabled(not self.read_only)
            chk.setTristate(False)
            chk.setChecked(False)
            chk.setProperty("case_id", int(row[0]))
            chk.clicked.connect(self._on_done_clicked)
            self.table.setCellWidget(r, self.COL_DONE, self._centered_checkbox_widget(chk))

            # Farbe für „Tage offen“
            self._apply_age_color_to_row(r)

        # Auto nach Inhalt berechnen
        self.table.resizeColumnsToContents()
        # Danach erste Spalte robust machen: korrekte Mindestbreite berechnen und fixieren
        self._lock_first_header_width()

        self.table.setSortingEnabled(True)
        if self._first_refresh:
            self.table.sortItems(self.COL_TAGE, Qt.SortOrder.DescendingOrder)
            self._first_refresh = False
        else:
            self.table.sortItems(sort_section, sort_order)

    def _lock_first_header_width(self):
        """Sorgt dafür, dass 'Tage offen' nie abgeschnitten wird, auch mit Sortpfeil."""
        hdr = self.table.horizontalHeader()

        # kurz automatisch messen lassen
        hdr.setSectionResizeMode(self.COL_TAGE, QHeaderView.ResizeMode.ResizeToContents)
        self.table.resizeColumnToContents(self.COL_TAGE)

        need = self._needed_header_width(self.COL_TAGE)
        # harte Untergrenze (passt zu Standard-Themes; gern auf 190 oder 200 erhöhen, wenn nötig)
        MIN_HEADER0 = 180
        width = max(self.table.columnWidth(self.COL_TAGE), need, MIN_HEADER0)

        # fixieren, damit andere Spalten diese Breite nicht wieder verkleinern
        hdr.setSectionResizeMode(self.COL_TAGE, QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(self.COL_TAGE, width)

        # übrige Spalten weiterhin dynamisch
        for c in range(self.table.columnCount()):
            if c != self.COL_TAGE:
                hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)

        hdr.setStretchLastSection(True)

    def _needed_header_width(self, col: int) -> int:
        """Breite, die der Headertext real braucht (inkl. Sortpfeil nur wenn aktiv) und Padding."""
        hdr = self.table.horizontalHeader()
        item = self.table.horizontalHeaderItem(col)
        if not item:
            return self.table.columnWidth(col)

        # Textbreite mit dem aktuellen Header-Font
        fm: QFontMetrics = hdr.fontMetrics()
        text_w = fm.horizontalAdvance(item.text())

        # Sortpfeil nur berücksichtigen, wenn diese Spalte die aktuelle Sortspalte ist
        sort_w = 0
        if hdr.sortIndicatorSection() == col:
            sort_w = self.style().pixelMetric(QStyle.PixelMetric.PM_HeaderMarkSize, None, hdr) or 0

        # etwas Puffer für linkes/rechtes Padding und Reserve
        padding_lr = 32
        extra = 16

        return text_w + sort_w + padding_lr + extra

    # ---------------- Export ----------------
    def _export_open_cases(self):
        path, _ = QFileDialog.getSaveFileName(self, "CSV exportieren (offen)", "offene.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            where_sql, params = self._scope_filter_sql()
            cur = self.conn.cursor()
            rows = cur.execute(
                f"""
                SELECT id, clinic, device_name, wave_number, submitter,
                       service_provider, reason, date_submitted
                FROM cases
                {where_sql}
                ORDER BY id DESC
                """,
                params,
            ).fetchall()

            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["ID", "Klinik", "Gerät", "Wave- / Serienummer", "Abgeber", "Techniker", "Grund", "Abgabe"])
                w.writerows(rows)

            QMessageBox.information(self, "Export", "Die offenen Reparaturen wurden erfolgreich exportiert.")
        except Exception as e:
            QMessageBox.warning(self, "Export nicht möglich", f"Die CSV-Datei konnte nicht erstellt werden.\n\nDetails:\n{e}")

    # ---------------- Abschluss ----------------
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
        device_label = self._device_label(case_id)
        sender.setEnabled(False)
        today = QDate.currentDate().toString("yyyy-MM-dd")

        try:
            with self.conn:
                self._ensure_case_columns(["status", "date_returned", "closed_by"])
                self.conn.execute(
                    "UPDATE cases SET status='Abgeschlossen', date_returned=?, closed_by=? WHERE id=?",
                    (today, self.current_username, case_id)
                )
                self.conn.execute(
                    "INSERT INTO audit_log(action, entity, entity_id, details) VALUES(?,?,?,?)",
                    ("case_update", "case", case_id, json.dumps(
                        {"status": "Abgeschlossen", "date_returned": today, "closed_by": self.current_username},
                        ensure_ascii=False
                    ))
                )
            QTimer.singleShot(0, lambda: self._after_done_success(case_id, device_label))
        except Exception:
            enqueue_write({
                "type": "update_case",
                "id": case_id,
                "date_returned": today,
                "status": "Abgeschlossen",
                "closed_by": self.current_username,
            })
            QTimer.singleShot(0, lambda: self._after_done_offline(sender))

    def _after_done_success(self, case_id: int, label: str):
        self.case_completed.emit(case_id)
        self.refresh()
        QMessageBox.information(self, "Erledigt", f"Gerät „{label}“ wurde abgeschlossen und verschoben.")

    def _after_done_offline(self, checkbox: QCheckBox):
        checkbox.blockSignals(True)
        checkbox.setChecked(False)
        checkbox.blockSignals(False)
        checkbox.setEnabled(True)
        QMessageBox.information(
            self,
            "Offline gespeichert",
            "Die Änderung wurde lokal gespeichert und wird beim nächsten Start automatisch synchronisiert."
        )

    # ---------------- Farb-Logik ----------------
    def _apply_age_color_to_row(self, row_index: int) -> None:
        date_str = self._cell_text(row_index, self.COL_ABGABE)
        days_open = self._days_since(date_str)
        brush = self._brush_for_days(days_open)
        if brush:
            it = self.table.item(row_index, self.COL_TAGE)
            if it:
                it.setBackground(brush)

    # ---------------- Helper ----------------
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

    def _cell_text(self, row: int, col: int) -> Optional[str]:
        it = self.table.item(row, col)
        return it.text() if it else None

    def _date_to_julian(self, s: Optional[str]) -> int:
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
            return QBrush(QColor(0, 200, 0))
        if days <= 60:
            return QBrush(QColor(255, 200, 0))
        return QBrush(QColor(220, 0, 0))

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
