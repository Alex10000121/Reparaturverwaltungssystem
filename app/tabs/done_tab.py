# app/tabs/done_tab.py
import json
import sqlite3
from datetime import datetime
from typing import List, Tuple, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QWidget, QLineEdit, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QCheckBox, QMessageBox, QHBoxLayout
)

from app.helpers import clinics_of_user
from app.buffer import enqueue_write


class DoneTab(QWidget):
    """Abgeschlossene Fälle: standardmäßig nach Rückgabedatum DESC (neueste oben),
       Sortieren per Header-Klick, Suche, 'Wieder öffnen?' Checkbox.
       Spalten: ID, Klinik, Gerät, Wave- / Serienummer, Abgeber, Techniker, Grund,
                Abgabe, Zurück, Angelegt von, Erledigt von, Notizen, Wieder öffnen?
    """
    case_reopened = pyqtSignal(int)

    # Spalten-Indices (0-basiert)
    COL_ID = 0
    COL_ABGABE = 7
    COL_ZURUECK = 8
    COL_CREATEDBY = 9
    COL_CLOSEDBY = 10
    COL_NOTES = 11
    COL_REOPEN = 12

    def __init__(self, conn: sqlite3.Connection, role: str, clinics_csv: str):
        super().__init__()
        self.conn = conn
        self.allowed = clinics_of_user(role, clinics_csv)
        self.read_only = (role == "Viewer")

        self._created_by_expr, self._closed_by_expr, self._notes_expr = self._detect_column_exprs()

        self.search = QLineEdit(placeholderText="Suchen ...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)

        self.table = QTableWidget()
        self.table.setColumnCount(13)
        self.table.setHorizontalHeaderLabels([
            "ID", "Klinik", "Gerät", "Wave- / Serienummer", "Abgeber", "Techniker",
            "Grund", "Abgabe", "Zurück", "Angelegt von", "Erledigt von", "Notizen", "Wieder öffnen?"
        ])
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(True)  # Sortieren per Header-Klick

        lay = QVBoxLayout(self)
        lay.addWidget(self.search)
        lay.addWidget(self.table)

        self._first_refresh = True
        self.refresh()

    # ---------- Schema/Meta ----------
    def _detect_column_exprs(self) -> tuple[str, str, str]:
        """Sichere SQL-Ausdrücke für created_by/closed_by/notes (Fallback: '')."""
        try:
            cur = self.conn.cursor()
            cur.execute("PRAGMA table_info(cases);")
            cols = {row[1] for row in cur.fetchall()}
        except Exception:
            cols = set()
        created_expr = "created_by" if "created_by" in cols else "''"
        closed_expr = "closed_by" if "closed_by" in cols else "''"
        notes_expr = "notes" if "notes" in cols else "''"
        return created_expr, closed_expr, notes_expr

    # ---------- Datenbeschaffung ----------
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

    # ---------- UI ----------
    def _centered_checkbox_widget(self, checkbox: QCheckBox) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(checkbox)
        return w

    def refresh(self):
        rows = self._fetch()

        # Freitextsuche
        q = self.search.text().strip().lower()
        if q:
            rows = [r for r in rows if any(
                (str(x or "").lower().find(q) >= 0)
                for x in (
                    r[1], r[2], r[3], r[4], r[5], r[6],
                    r[self.COL_ABGABE], r[self.COL_ZURUECK],
                    r[self.COL_CREATEDBY], r[self.COL_CLOSEDBY], r[self.COL_NOTES]
                )
            )]

        # Sortiereinstellungen merken (Benutzerauswahl erhalten)
        header = self.table.horizontalHeader()
        sort_section = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))

        for r, row in enumerate(rows):
            # 0..11 sind Textspalten
            for c in range(self.COL_REOPEN):
                val = row[c]
                text = "" if val is None else str(val)
                # Notizen elidieren (alte Datensätze könnten lang sein)
                display = (text[:200] + "…") if (c == self.COL_NOTES and len(text) > 200) else text

                item = QTableWidgetItem(display)
                item.setToolTip(text)

                # Sortier-Key (UserRole) setzen für korrekte Sortierung
                if c == self.COL_ID:
                    try:
                        item.setData(Qt.ItemDataRole.UserRole, int(text or "0"))
                    except ValueError:
                        item.setData(Qt.ItemDataRole.UserRole, 0)
                elif c in (self.COL_ABGABE, self.COL_ZURUECK):
                    item.setData(Qt.ItemDataRole.UserRole, self._date_sort_key(text))

                # Ausrichtung
                if c == self.COL_ID:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                elif c in (self.COL_ABGABE, self.COL_ZURUECK):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter)
                else:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, c, item)

            # 12: Wieder öffnen? (zentriert)
            chk = QCheckBox()
            chk.setTristate(False)
            chk.setChecked(False)
            chk.setText("")
            chk.setEnabled(not self.read_only)
            chk.setProperty("case_id", int(row[self.COL_ID]))
            chk.clicked.connect(self._on_reopen_clicked)
            self.table.setCellWidget(r, self.COL_REOPEN, self._centered_checkbox_widget(chk))

        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)

        # Erstes Mal: Standard-Sortierung -> Rückgabedatum absteigend (neueste oben)
        if self._first_refresh:
            self.table.sortItems(self.COL_ZURUECK, Qt.SortOrder.DescendingOrder)
            self._first_refresh = False
        else:
            # Benutzer-Sortierung beibehalten
            self.table.sortItems(sort_section, sort_order)

    # ---------- Reopen (crash-safe via deferred UI) ----------
    def _on_reopen_clicked(self, checked: bool):
        if not checked:
            return
        sender = self.sender()
        if not isinstance(sender, QCheckBox):
            return
        cid = sender.property("case_id")
        if cid is None:
            return

        case_id = int(cid)
        device_label = self._device_label(case_id)  # Gerät vorab auflösen
        sender.setEnabled(False)

        def defer_offline_reset():
            sender.blockSignals(True)
            sender.setChecked(False)
            sender.blockSignals(False)
            sender.setEnabled(True)
            QMessageBox.information(
                self, "Offline gespeichert",
                "Die DB war nicht erreichbar/gesperrt.\nDie Änderung wurde offline gespeichert und wird beim NÄCHSTEN Start synchronisiert."
            )

        try:
            with self.conn:
                # Spalten robust nachrüsten (falls sehr alte DB)
                self._ensure_case_columns(["status", "date_returned", "closed_by"])

                # Status zurück auf "In Reparatur", Rückgabedatum/closed_by leeren
                self.conn.execute(
                    "UPDATE cases SET status='In Reparatur', date_returned=NULL, closed_by=NULL WHERE id=?",
                    (case_id,)
                )
                # Audit
                self.conn.execute(
                    "INSERT INTO audit_log(action, entity, entity_id, details) VALUES(?,?,?,?)",
                    ("case_update", "case", case_id, json.dumps(
                        {"status": "In Reparatur", "date_returned": None, "closed_by": None},
                        ensure_ascii=False
                    ))
                )

            QTimer.singleShot(0, lambda cid=case_id, label=device_label: self._after_reopen_success(cid, label))

        except Exception:
            # Offline-Fallback
            enqueue_write({
                "type": "update_case",
                "id": case_id,
                "date_returned": None,
                "status": "In Reparatur",
                "closed_by": None
            })
            QTimer.singleShot(0, defer_offline_reset)

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

    def _after_reopen_success(self, case_id: int, device_label: str):
        self.case_reopened.emit(case_id)
        self.refresh()
        QMessageBox.information(self, "Geöffnet", f"Gerät „{device_label}“ wurde wieder geöffnet.")

    # ---------- Sort-Helper ----------
    def _date_sort_key(self, s: Optional[str]) -> int:
        """Konvertiert Datum (yyyy-mm-dd oder ähnliche) in 'Tage seit 1970-01-01' für stabile Sortierung.
           Leere/ungültige Werte -> sehr kleiner Key (damit bei DESC ganz unten)."""
        if not s:
            return -10**9
        s = s.strip()
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y"):
            try:
                dt = datetime.strptime(s, fmt)
                return (dt - datetime(1970, 1, 1)).days
            except ValueError:
                continue
        # Fallback: ISO-like
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return (dt.replace(tzinfo=None) - datetime(1970, 1, 1)).days
        except Exception:
            return -10**9

    # ---------- Helpers ----------
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
