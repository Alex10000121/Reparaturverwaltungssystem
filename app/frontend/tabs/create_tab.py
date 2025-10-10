# app/tabs/create_tab.py
from __future__ import annotations

import json
import sqlite3
from typing import Optional

from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QLineEdit, QTextEdit, QComboBox, QDateEdit, QPushButton,
    QVBoxLayout, QFormLayout, QMessageBox
)

from app.backend.helpers.helpers import clinic_choices_for
    # Ermittelt die erlaubten Kliniken für die aktuelle Rolle
from app.backend.helpers.buffer import enqueue_write
    # Fällt offline auf einen lokalen Puffer zurück, der später synchronisiert wird


MAX_INPUT_CHARS = 30  # harte Obergrenze für alle Eingabefelder


class CreateTab(QWidget):
    """
    Neuer Fall erfassen:
    - Pflichtfelder mit Live-Limits
    - Klinikauswahl anhand Rolle/Rechte
    - Audit-Eintrag bei Erfolg
    - Offline-Puffer, falls die Datenbank gerade nicht erreichbar ist
    """
    case_created = pyqtSignal()

    def __init__(
        self,
        conn: sqlite3.Connection,
        role: str,
        clinics_csv: str,
        submitter_default: Optional[str] = None,
        current_username: Optional[str] = None,  # landet als created_by in der DB
    ):
        super().__init__()
        self.conn = conn
        self.role = role
        self.clinics_csv = clinics_csv
        self.current_username = current_username or ""

        # --- Felder ---
        self.device = QLineEdit()
        self.device.setPlaceholderText("z. B. Endoskop")
        self.device.setMaxLength(MAX_INPUT_CHARS)

        self.wave = QLineEdit()
        self.wave.setPlaceholderText("z. B. 123456 / SN654321")
        self.wave.setMaxLength(MAX_INPUT_CHARS)

        self.submitter = QLineEdit()
        self.submitter.setPlaceholderText("z. B. Max Muster (änderbar)")
        self.submitter.setMaxLength(MAX_INPUT_CHARS)
        if submitter_default:
            self.submitter.setText(submitter_default[:MAX_INPUT_CHARS])

        self.provider = QLineEdit()
        self.provider.setPlaceholderText("z. B. Tom Toolmann")
        self.provider.setMaxLength(MAX_INPUT_CHARS)

        self.clinic = QComboBox()
        self._reload_clinics()

        self.reason = QLineEdit()
        self.reason.setPlaceholderText("z. B. Akku defekt")
        self.reason.setMaxLength(MAX_INPUT_CHARS)

        self.date_sub = QDateEdit()
        self.date_sub.setCalendarPopup(True)
        self.date_sub.setDate(QDate.currentDate())

        self.notes = QTextEdit()
        self.notes.setPlaceholderText(f"Notizen (max. {MAX_INPUT_CHARS} Zeichen)")
        self.notes.textChanged.connect(self._enforce_notes_limit)  # begrenzt auch Einfügen

        # --- Layout ---
        form = QFormLayout()
        form.addRow("Klinik*", self.clinic)
        form.addRow("Gerät*", self.device)
        form.addRow("Wave- / Serienummer*", self.wave)
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

    # ================= UI-Helfer =================
    def _reload_clinics(self) -> None:
        """Befüllt die Klinikauswahl anhand der Rolle/Rechte."""
        self.clinic.clear()
        for name in clinic_choices_for(self.role, self.clinics_csv):
            self.clinic.addItem(name)

    def _clear_form(self) -> None:
        """Setzt alle Eingaben zurück."""
        for w in (self.device, self.wave, self.provider, self.reason, self.submitter):
            w.clear()
            w.setStyleSheet("")
        self.notes.clear()
        self.date_sub.setDate(QDate.currentDate())

    def _mark_invalid(self, widget) -> None:
        """Hebt ein ungültiges Feld sichtbar hervor."""
        widget.setStyleSheet(
            "border: 1px solid #d9534f; "
            "box-shadow: 0 0 0 3px rgba(217,83,79,.15);"
        )
        widget.setFocus()

    def _enforce_notes_limit(self) -> None:
        """Schneidet Notizen auf die Höchstlänge, Cursorposition bleibt möglichst stabil."""
        txt = self.notes.toPlainText()
        if len(txt) <= MAX_INPUT_CHARS:
            return
        cur = self.notes.textCursor()
        pos = cur.position()
        overflow = len(txt) - MAX_INPUT_CHARS
        self.notes.blockSignals(True)
        self.notes.setPlainText(txt[:MAX_INPUT_CHARS])
        pos = max(0, min(MAX_INPUT_CHARS, pos - overflow))
        cur.setPosition(pos)
        self.notes.setTextCursor(cur)
        self.notes.blockSignals(False)

    # ================ Persistenz ================
    def _ensure_columns(self) -> None:
        """
        Stellt sicher, dass optionale Spalten vorhanden sind.
        Erweitert ältere Datenbanken bei Bedarf.
        """
        cur = self.conn.cursor()
        cur.execute("PRAGMA table_info(cases);")
        existing = {row[1] for row in cur.fetchall()}
        with self.conn:
            if "created_by" not in existing:
                self.conn.execute("ALTER TABLE cases ADD COLUMN created_by TEXT")
            if "closed_by" not in existing:
                self.conn.execute("ALTER TABLE cases ADD COLUMN closed_by TEXT")

    # ================= Aktionen =================
    def on_save(self) -> None:
        """
        Validiert Eingaben, speichert den Fall und schreibt einen Audit-Eintrag.
        Bei vorübergehend fehlender Verbindung landet der Datensatz im Offline-Puffer.
        """
        # Pflichtfelder (defensiv erneut gekürzt)
        clinic = self.clinic.currentText().strip()
        device = self.device.text().strip()[:MAX_INPUT_CHARS]
        wave = self.wave.text().strip()[:MAX_INPUT_CHARS]
        submitter = self.submitter.text().strip()[:MAX_INPUT_CHARS]
        provider = self.provider.text().strip()[:MAX_INPUT_CHARS]
        reason = self.reason.text().strip()[:MAX_INPUT_CHARS]
        date_submitted_str = self.date_sub.date().toString("yyyy-MM-dd")

        if not clinic:
            QMessageBox.warning(self, "Validierung", "Bitte eine Klinik wählen.")
            return
        if not device:
            self._mark_invalid(self.device)
            return
        if not wave:
            self._mark_invalid(self.wave)
            return
        if not submitter:
            self._mark_invalid(self.submitter)
            return
        if not provider:
            self._mark_invalid(self.provider)
            return
        if not reason:
            self._mark_invalid(self.reason)
            return

        notes = (self.notes.toPlainText().strip() or None)
        if notes:
            notes = notes[:MAX_INPUT_CHARS]

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
            "created_by": self.current_username or None,
        }

        try:
            self._ensure_columns()
            with self.conn:
                cur = self.conn.execute(
                    """
                    INSERT INTO cases(
                        clinic, device_name, wave_number, submitter, service_provider,
                        status, reason, date_submitted, date_returned, notes, created_by, closed_by
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        payload["clinic"],
                        payload["device_name"],
                        payload["wave_number"],
                        payload["submitter"],
                        payload["service_provider"],
                        payload["status"],
                        payload["reason"],
                        payload["date_submitted"],
                        payload["date_returned"],
                        payload["notes"],
                        payload["created_by"],
                        None,
                    ),
                )
                case_id = cur.lastrowid
                self.conn.execute(
                    "INSERT INTO audit_log(action, entity, entity_id, details) VALUES(?,?,?,?)",
                    ("case_create", "case", case_id, json.dumps(payload, ensure_ascii=False)),
                )

            self._clear_form()
            QMessageBox.information(self, "Erfasst", "Fall wurde erfasst. Status: In Reparatur.")
            self.case_created.emit()

        except Exception:
            # Offline-Fallback: später synchronisieren
            enqueue_write(dict(payload, type="insert_case"))
            self._clear_form()
            QMessageBox.information(
                self,
                "Offline gespeichert",
                "Die Datenbank war nicht erreichbar oder gesperrt.\n"
                "Die Änderung wurde lokal gespeichert und beim nächsten Start synchronisiert.",
            )
