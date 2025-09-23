import json, sqlite3
from typing import Optional
from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QLineEdit, QTextEdit, QComboBox, QDateEdit, QPushButton, QVBoxLayout, QFormLayout, QMessageBox
from app.helpers import clinic_choices_for
from app.buffer import enqueue_write

class CreateTab(QWidget):
    case_created = pyqtSignal()

    def __init__(self, conn: sqlite3.Connection, role: str, clinics_csv: str, submitter_default: Optional[str] = None):
        super().__init__()
        self.conn = conn; self.role = role; self.clinics_csv = clinics_csv

        self.device = QLineEdit(); self.device.setPlaceholderText("z. B. Endoskop")
        self.wave = QLineEdit(); self.wave.setPlaceholderText("z. B. 123456 / SN654321")
        self.submitter = QLineEdit()
        if submitter_default: self.submitter.setText(submitter_default)
        self.submitter.setPlaceholderText("z. B. Max Muster (änderbar)")
        self.provider = QLineEdit(); self.provider.setPlaceholderText("z. B. Tom Toolmann")
        self.clinic = QComboBox(); self._reload_clinics()
        self.reason = QLineEdit(); self.reason.setPlaceholderText("z. B. Akku defekt")
        self.date_sub = QDateEdit(); self.date_sub.setCalendarPopup(True); self.date_sub.setDate(QDate.currentDate())
        self.notes = QTextEdit()

        form = QFormLayout()
        form.addRow("Klinik*", self.clinic)
        form.addRow("Gerät*", self.device)
        form.addRow("Wavenummer / Seriennummer*", self.wave)
        form.addRow("Abgeber*", self.submitter)
        form.addRow("Techniker*", self.provider)
        form.addRow("Grund*", self.reason)
        form.addRow("Abgabe-Datum*", self.date_sub)
        form.addRow("Notizen", self.notes)

        self.btn_save = QPushButton("Erfassen"); self.btn_save.clicked.connect(self.on_save)
        lay = QVBoxLayout(self); lay.addLayout(form); lay.addWidget(self.btn_save, alignment=Qt.AlignmentFlag.AlignRight)

    def _reload_clinics(self):
        self.clinic.clear()
        for name in clinic_choices_for(self.role, self.clinics_csv):
            self.clinic.addItem(name)

    def _clear_form(self):
        for w in (self.device, self.wave, self.provider, self.reason):
            w.clear(); w.setStyleSheet("")
        self.notes.clear()
        self.date_sub.setDate(QDate.currentDate())

    def _mark_invalid(self, widget):
        widget.setStyleSheet("border: 1px solid #d9534f; box-shadow: 0 0 0 3px rgba(217,83,79,.15);")
        widget.setFocus()

    def on_save(self):
        # Pflichtfelder
        clinic = self.clinic.currentText().strip()
        device = self.device.text().strip() or ""
        wave = self.wave.text().strip() or ""
        submitter = self.submitter.text().strip() or ""
        provider = self.provider.text().strip() or ""
        reason = self.reason.text().strip() or ""
        date_submitted_str = self.date_sub.date().toString("yyyy-MM-dd")

        # Inline-Validierung (sofort am Feld)
        if not clinic: QMessageBox.warning(self, "Validierung", "Bitte eine Klinik wählen."); return
        if not device: self._mark_invalid(self.device); return
        if not wave: self._mark_invalid(self.wave); return
        if not submitter: self._mark_invalid(self.submitter); return
        if not provider: self._mark_invalid(self.provider); return
        if not reason: self._mark_invalid(self.reason); return

        creator_id = getattr(self, "current_user_id", None)  # sollte vom Login gesetzt sein

        payload = {
            "clinic": clinic,
            "device_name": device,
            "wave_number": wave,
            "submitter": submitter,
            "service_provider": provider,
            "status": "In Reparatur",
            "reason": reason,
            "date_submitted": date_submitted_str,
            "date_returned": None,
            "notes": self.notes.toPlainText().strip() or None,
            "created_by": creator_id,  # NEU
        }

        try:
            with self.conn:
                try:
                    # Bevorzugter Insert MIT created_by/closed_by
                    cur = self.conn.execute(
                        """INSERT INTO cases(
                               clinic,device_name,wave_number,submitter,service_provider,status,reason,
                               date_submitted,date_returned,notes,created_by,closed_by
                           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            payload["clinic"], payload["device_name"], payload["wave_number"], payload["submitter"],
                            payload["service_provider"], payload["status"], payload["reason"],
                            payload["date_submitted"], payload["date_returned"], payload["notes"],
                            payload["created_by"], None
                        )
                    )
                except sqlite3.OperationalError as e:
                    # Falls die Spalten noch nicht existieren: einmalig anlegen und erneut versuchen
                    msg = str(e).lower()
                    if "no such column: created_by" in msg or "has no column named created_by" in msg:
                        self.conn.execute("ALTER TABLE cases ADD COLUMN created_by INTEGER REFERENCES users(id)")
                        self.conn.execute("ALTER TABLE cases ADD COLUMN closed_by INTEGER REFERENCES users(id)")
                        cur = self.conn.execute(
                            """INSERT INTO cases(
                                   clinic,device_name,wave_number,submitter,service_provider,status,reason,
                                   date_submitted,date_returned,notes,created_by,closed_by
                               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (
                                payload["clinic"], payload["device_name"], payload["wave_number"], payload["submitter"],
                                payload["service_provider"], payload["status"], payload["reason"],
                                payload["date_submitted"], payload["date_returned"], payload["notes"],
                                payload["created_by"], None
                            )
                        )
                    else:
                        raise

                case_id = cur.lastrowid
                self.conn.execute(
                    "INSERT INTO audit_log(action, entity, entity_id, details) VALUES(?,?,?,?)",
                    ("case_create", "case", case_id, json.dumps(payload, ensure_ascii=False))
                )

            self._clear_form()
            QMessageBox.information(self, "Erfasst", "Fall wurde erfasst (Status: In Reparatur).")
            self.case_created.emit()

        except Exception:
            # Offline-Puffer: jetzt inkl. created_by
            enqueue_write(dict(payload, type="insert_case"))
            self._clear_form()
            QMessageBox.information(
                self, "Offline gespeichert",
                "Die DB war nicht erreichbar/gesperrt.\nDer Fall wurde offline gespeichert und wird beim NÄCHSTEN Start synchronisiert."
            )
