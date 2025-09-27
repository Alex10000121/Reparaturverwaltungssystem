# app/tabs/create_tab.py
import json, sqlite3
from typing import Optional
from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QLineEdit, QTextEdit, QComboBox, QDateEdit, QPushButton,
    QVBoxLayout, QFormLayout, QMessageBox
)
from app.helpers import clinic_choices_for
from app.buffer import enqueue_write

MAX_INPUT_CHARS = 50  # harte Obergrenze für *alle* Eingabefelder


class CreateTab(QWidget):
    case_created = pyqtSignal()

    def __init__(
        self,
        conn: sqlite3.Connection,
        role: str,
        clinics_csv: str,
        submitter_default: Optional[str] = None,
        current_username: Optional[str] = None,  # wird in 'created_by' gespeichert (DB: TEXT)
    ):
        super().__init__()
        self.conn = conn
        self.role = role
        self.clinics_csv = clinics_csv
        self.current_username = current_username or ""

        # --- Felder ---
        self.device = QLineEdit(); self.device.setPlaceholderText("z. B. Endoskop"); self.device.setMaxLength(MAX_INPUT_CHARS)
        self.wave = QLineEdit(); self.wave.setPlaceholderText("z. B. 123456 / SN654321"); self.wave.setMaxLength(MAX_INPUT_CHARS)
        self.submitter = QLineEdit(); self.submitter.setPlaceholderText("z. B. Max Muster (änderbar)"); self.submitter.setMaxLength(MAX_INPUT_CHARS)
        if submitter_default:
            self.submitter.setText(submitter_default[:MAX_INPUT_CHARS])  # sicherheitshalber kappen
        self.provider = QLineEdit(); self.provider.setPlaceholderText("z. B. Tom Toolmann"); self.provider.setMaxLength(MAX_INPUT_CHARS)
        self.clinic = QComboBox(); self._reload_clinics()
        self.reason = QLineEdit(); self.reason.setPlaceholderText("z. B. Akku defekt"); self.reason.setMaxLength(MAX_INPUT_CHARS)
        self.date_sub = QDateEdit(); self.date_sub.setCalendarPopup(True); self.date_sub.setDate(QDate.currentDate())

        self.notes = QTextEdit()
        self.notes.setPlaceholderText(f"Notizen (max. {MAX_INPUT_CHARS} Zeichen)")
        # Live-Limit für QTextEdit (auch bei Paste)
        self.notes.textChanged.connect(self._enforce_notes_limit)

        # --- Layout ---
        form = QFormLayout()
        form.addRow("Klinik*", self.clinic)
        form.addRow("Gerät*", self.device)
        form.addRow("Wave- / Serienummer*", self.wave)  # <-- Bezeichnung geändert
        form.addRow("Abgeber*", self.submitter)
        form.addRow("Techniker*", self.provider)
        form.addRow("Grund*", self.reason)
        form.addRow("Abgabe-Datum*", self.date_sub)
        form.addRow("Notizen", self.notes)

        self.btn_save = QPushButton("Erfassen")
        self.btn_save.clicked.connect(self.on_save)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.btn_save, alignment=Qt.AlignmentFlag.AlignRight)

    # ----------------- UI Helpers -----------------
    def _reload_clinics(self):
        self.clinic.clear()
        for name in clinic_choices_for(self.role, self.clinics_csv):
            self.clinic.addItem(name)

    def _clear_form(self):
        for w in (self.device, self.wave, self.provider, self.reason, self.submitter):
            w.clear(); w.setStyleSheet("")
        self.notes.clear()
        self.date_sub.setDate(QDate.currentDate())

    def _mark_invalid(self, widget):
        widget.setStyleSheet("border: 1px solid #d9534f; box-shadow: 0 0 0 3px rgba(217,83,79,.15);")
        widget.setFocus()

    def _enforce_notes_limit(self):
        """Verhindert Eingaben über MAX_INPUT_CHARS (auch bei Paste)."""
        text = self.notes.toPlainText()
        if len(text) <= MAX_INPUT_CHARS:
            return
        cursor = self.notes.textCursor()
        pos = cursor.position()
        overflow = len(text) - MAX_INPUT_CHARS
        new_pos = max(0, min(MAX_INPUT_CHARS, pos - overflow))

        self.notes.blockSignals(True)
        self.notes.setPlainText(text[:MAX_INPUT_CHARS])
        cursor.setPosition(new_pos)
        self.notes.setTextCursor(cursor)
        self.notes.blockSignals(False)

    # ----------------- Persistenz -----------------
    def _ensure_columns(self):
        """Sichert optionale Spalten ab (kompatibel zu älteren DBs)."""
        cur = self.conn.cursor()
        cur.execute("PRAGMA table_info(cases);")
        existing = {row[1] for row in cur.fetchall()}
        with self.conn:
            if "created_by" not in existing:
                self.conn.execute("ALTER TABLE cases ADD COLUMN created_by TEXT")
            if "closed_by" not in existing:
                self.conn.execute("ALTER TABLE cases ADD COLUMN closed_by TEXT")

    # ----------------- Aktionen -----------------
    def on_save(self):
        # Pflichtfelder lesen & prüfen (defensiv erneut kappen)
        clinic = self.clinic.currentText().strip()
        device = self.device.text().strip()[:MAX_INPUT_CHARS]
        wave = self.wave.text().strip()[:MAX_INPUT_CHARS]
        submitter = self.submitter.text().strip()[:MAX_INPUT_CHARS]
        provider = self.provider.text().strip()[:MAX_INPUT_CHARS]
        reason = self.reason.text().strip()[:MAX_INPUT_CHARS]
        date_submitted_str = self.date_sub.date().toString("yyyy-MM-dd")

        if not clinic:
            QMessageBox.warning(self, "Validierung", "Bitte eine Klinik wählen."); return
        if not device:
            self._mark_invalid(self.device); return
        if not wave:
            self._mark_invalid(self.wave); return
        if not submitter:
            self._mark_invalid(self.submitter); return
        if not provider:
            self._mark_invalid(self.provider); return
        if not reason:
            self._mark_invalid(self.reason); return

        # Notizen bereits live limitiert – hier defensiv kappen
        _notes_full = self.notes.toPlainText().strip()
        notes = _notes_full[:MAX_INPUT_CHARS] if _notes_full else None

        payload = {
            "clinic": clinic,
            "device_name": device,
            "wave_number": wave or None,
            "submitter": submitter or None,
            "service_provider": provider or None,
            "status": "In Reparatur",
            "reason": reason or None,
            "date_submitted": date_submitted_str,
            "date_returned": None,
            "notes": notes,
            "created_by": self.current_username or None,  # TEXT (Benutzername)
        }

        # Insert (robust mit Spalten-Sicherung)
        try:
            self._ensure_columns()
            with self.conn:
                cur = self.conn.execute(
                    """INSERT INTO cases(
                           clinic, device_name, wave_number, submitter, service_provider,
                           status, reason, date_submitted, date_returned, notes, created_by, closed_by
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        payload["clinic"], payload["device_name"], payload["wave_number"], payload["submitter"],
                        payload["service_provider"], payload["status"], payload["reason"],
                        payload["date_submitted"], payload["date_returned"], payload["notes"],
                        payload["created_by"], None
                    )
                )
                case_id = cur.lastrowid
                self.conn.execute(
                    "INSERT INTO audit_log(action, entity, entity_id, details) VALUES(?,?,?,?)",
                    ("case_create", "case", case_id, json.dumps(payload, ensure_ascii=False))
                )

            self._clear_form()
            QMessageBox.information(self, "Erfasst", "Fall wurde erfasst (Status: In Reparatur).")
            self.case_created.emit()

        except Exception:
            # Offline-Puffer
            enqueue_write(dict(payload, type="insert_case"))
            self._clear_form()
            QMessageBox.information(
                self, "Offline gespeichert",
                "Die DB war nicht erreichbar/gesperrt.\nDer Fall wurde offline gespeichert und wird beim NÄCHSTEN Start synchronisiert."
            )
