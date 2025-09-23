from typing import Optional, Callable
import sqlite3, json
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit, QComboBox, QCheckBox,
    QPushButton, QTableWidget, QTableWidgetItem, QGroupBox, QAbstractItemView, QMessageBox, QFrame
)
from auth import list_users, add_user, delete_user
from db import list_clinics, add_clinic, delete_clinic


class CollapsibleSection(QWidget):
    """
    Einfache einklappbare Sektion mit Header-Button (Pfeil) + Content-Widget.
    - start_collapsed: True => Inhalt versteckt
    - exclusive handling erfolgt außen (AdminTab) via expand_only(this)
    """
    toggled = pyqtSignal(bool)

    def __init__(self, title: str, content: QWidget, start_collapsed: bool = True, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._content = content

        self._btn = QPushButton(title)
        self._btn.setCheckable(True)
        self._btn.setChecked(not start_collapsed)
        self._btn.setStyleSheet("QPushButton { text-align: left; padding: 8px 10px; border-radius: 8px; }")
        self._btn.toggled.connect(self._on_toggled)

        # kleiner Pfeil links
        self._update_arrow(self._btn.isChecked())

        # Inhalt umrahmen (Card-Optik)
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setFrameShadow(QFrame.Shadow.Plain)
        flay = QVBoxLayout(frame); flay.setContentsMargins(10, 8, 10, 10); flay.addWidget(content)

        self._content_frame = frame
        self._content_frame.setVisible(not start_collapsed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._btn)
        lay.addWidget(self._content_frame)

    def _update_arrow(self, expanded: bool):
        # Unicode-Pfeile: ▶ (rechts) / ▼ (unten)
        arrow = "▼ " if expanded else "▶ "
        self._btn.setText(f"{arrow}{self._btn.text()[2:] if self._btn.text().startswith(('▼ ','▶ ')) else self._btn.text()}")

    def _on_toggled(self, checked: bool):
        self._content_frame.setVisible(checked)
        self._update_arrow(checked)
        self.toggled.emit(checked)

    def set_expanded(self, expanded: bool):
        self._btn.blockSignals(True)
        self._btn.setChecked(expanded)
        self._content_frame.setVisible(expanded)
        self._update_arrow(expanded)
        self._btn.blockSignals(False)

    def is_expanded(self) -> bool:
        return self._btn.isChecked()


class AdminTab(QWidget):
    """
    Struktur:
      1) Benutzerübersicht (immer sichtbar, read-only)
      2) Collapsible: „Neuen Benutzer anlegen“ (zu Beginn zu)
      3) Collapsible: „Ausgewählten Benutzer bearbeiten“ (zu Beginn zu)
      4) Collapsible: „Kliniken verwalten“ (zu Beginn zu)
      -> exklusiv: immer nur eine Sektion offen
    """
    def __init__(self, conn: sqlite3.Connection, current_user_id: int, on_clinics_changed: Optional[Callable] = None):
        super().__init__()
        self.conn = conn
        self.current_user_id = current_user_id
        self.on_clinics_changed = on_clinics_changed

        # ----- 1) Benutzerübersicht -----
        self.gb_list = QGroupBox("Benutzerübersicht")
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["ID", "Benutzername", "Rolle", "Kliniken"])
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.sortItems(1)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._load_selected_into_form)
        self.table.verticalHeader().setDefaultSectionSize(28)

        lay_list = QVBoxLayout(self.gb_list); lay_list.addWidget(self.table)

        # ----- 2) Neuen Benutzer anlegen (Content-Widget) -----
        self.name_add = QLineEdit(); self.name_add.setPlaceholderText("z. B. a.mueller")
        self.pwd_add = QLineEdit(); self.pwd_add.setEchoMode(QLineEdit.EchoMode.Password)
        self.role_add = QComboBox(); self.role_add.addItems(["Admin", "Techniker", "Viewer"])

        self.chk_all_add = QCheckBox("Alle Kliniken")
        self.clinic_box_add = QWidget()
        self.clinic_layout_add = QHBoxLayout(self.clinic_box_add); self.clinic_layout_add.setContentsMargins(0, 0, 0, 0)
        self.chk_add: dict[str, QCheckBox] = {}
        self._build_clinic_checkboxes(target="add")
        self.chk_all_add.toggled.connect(lambda checked: self._toggle_all(target="add", checked=checked))

        self.btn_add_user = QPushButton("Benutzer hinzufügen")
        self.btn_add_user.clicked.connect(self.on_add_user)

        w_add = QWidget()
        form_add = QFormLayout(w_add)
        form_add.addRow("Benutzername", self.name_add)
        form_add.addRow("Passwort", self.pwd_add)
        form_add.addRow("Rolle", self.role_add)
        form_add.addRow(self.chk_all_add)
        form_add.addRow("Kliniken", self.clinic_box_add)
        form_add.addRow(self.btn_add_user)

        self.sec_add = CollapsibleSection("Neuen Benutzer anlegen", w_add, start_collapsed=True)

        # ----- 3) Ausgewählten Benutzer bearbeiten (Content-Widget) -----
        self.lbl_sel_user = QLabel("- kein Benutzer ausgewählt -")
        self.role_edit = QComboBox(); self.role_edit.addItems(["Admin", "Techniker", "Viewer"])

        self.chk_all_edit = QCheckBox("Alle Kliniken")
        self.clinic_box_edit = QWidget()
        self.clinic_layout_edit = QHBoxLayout(self.clinic_box_edit); self.clinic_layout_edit.setContentsMargins(0, 0, 0, 0)
        self.chk_edit: dict[str, QCheckBox] = {}
        self._build_clinic_checkboxes(target="edit")
        self.chk_all_edit.toggled.connect(lambda checked: self._toggle_all(target="edit", checked=checked))

        self.btn_save_perm = QPushButton("Änderungen speichern")
        self.btn_delete_user = QPushButton("Benutzer löschen")
        self.btn_save_perm.clicked.connect(self.on_save_selected)
        self.btn_delete_user.clicked.connect(self.on_delete_selected)

        w_edit = QWidget()
        form_edit = QFormLayout(w_edit)
        form_edit.addRow("Auswahl", self.lbl_sel_user)
        form_edit.addRow("Rolle", self.role_edit)
        form_edit.addRow(self.chk_all_edit)
        form_edit.addRow("Kliniken", self.clinic_box_edit)
        row_actions = QHBoxLayout(); row_actions.addWidget(self.btn_save_perm); row_actions.addStretch(1); row_actions.addWidget(self.btn_delete_user)
        form_edit.addRow(row_actions)

        self.sec_edit = CollapsibleSection("Ausgewählten Benutzer bearbeiten", w_edit, start_collapsed=True)

        # ----- 4) Kliniken verwalten (Content-Widget) -----
        self.new_clinic_name = QLineEdit(); self.new_clinic_name.setPlaceholderText("Neue Klinik…")
        self.btn_add_clinic = QPushButton("Klinik hinzufügen"); self.btn_add_clinic.clicked.connect(self.on_add_clinic)
        self.clinic_delete_select = QComboBox(); self._reload_clinic_select()
        self.btn_del_clinic = QPushButton("Klinik löschen"); self.btn_del_clinic.clicked.connect(self.on_delete_clinic)

        w_clin = QWidget()
        lay_clin = QVBoxLayout(w_clin)
        row_add = QHBoxLayout(); row_add.addWidget(self.new_clinic_name); row_add.addWidget(self.btn_add_clinic)
        row_del = QHBoxLayout(); row_del.addWidget(self.clinic_delete_select); row_del.addWidget(self.btn_del_clinic)
        lay_clin.addLayout(row_add); lay_clin.addLayout(row_del)

        self.sec_clin = CollapsibleSection("Kliniken verwalten", w_clin, start_collapsed=True)

        # ----- Exklusives Öffnen (nur eine Sektion offen) -----
        for sec in (self.sec_add, self.sec_edit, self.sec_clin):
            sec.toggled.connect(lambda checked, s=sec: self._on_section_toggled(s, checked))

        # ----- Gesamtlayout -----
        main = QVBoxLayout(self)
        main.addWidget(self.gb_list)
        main.addWidget(self.sec_add)
        main.addWidget(self.sec_edit)
        main.addWidget(self.sec_clin)
        main.addStretch(1)

        self.refresh()

    # --- Exklusive Steuerung ---
    def _on_section_toggled(self, sender: CollapsibleSection, checked: bool):
        if not checked:
            return
        # alle anderen schließen
        for sec in (self.sec_add, self.sec_edit, self.sec_clin):
            if sec is not sender:
                sec.set_expanded(False)

    # --- UI Helpers ---
    def _build_clinic_checkboxes(self, target: str):
        names = list_clinics()
        if target == "add":
            while self.clinic_layout_add.count():
                item = self.clinic_layout_add.takeAt(0)
                if item and item.widget(): item.widget().setParent(None)
            self.chk_add = {}
            for n in names:
                cb = QCheckBox(n); self.clinic_layout_add.addWidget(cb); self.chk_add[n] = cb
            self.clinic_layout_add.addStretch(1)
        else:
            while self.clinic_layout_edit.count():
                item = self.clinic_layout_edit.takeAt(0)
                if item and item.widget(): item.widget().setParent(None)
            self.chk_edit = {}
            for n in names:
                cb = QCheckBox(n); self.clinic_layout_edit.addWidget(cb); self.chk_edit[n] = cb
            self.clinic_layout_edit.addStretch(1)

    def _reload_clinic_select(self):
        self.clinic_delete_select.clear()
        for n in list_clinics(): self.clinic_delete_select.addItem(n)

    def _toggle_all(self, target: str, checked: bool):
        d = self.chk_add if target == "add" else self.chk_edit
        for cb in d.values():
            cb.setChecked(False if checked else cb.isChecked())
            cb.setEnabled(not checked)

    def _selected_user_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0: return None
        return int(self.table.item(row, 0).text())

    def _load_selected_into_form(self):
        uid = self._selected_user_id()
        if uid is None:
            self.lbl_sel_user.setText("- kein Benutzer ausgewählt -")
            self.role_edit.setCurrentIndex(0)
            self.role_edit.setEnabled(True)  # sicherheitshalber zurücksetzen
            self.chk_all_edit.setChecked(False)
            for cb in self.chk_edit.values(): cb.setChecked(False)
            return

        uname = self.table.item(self.table.currentRow(), 1).text()
        role = self.table.item(self.table.currentRow(), 2).text()
        clinics = self.table.item(self.table.currentRow(), 3).text() if self.table.item(self.table.currentRow(), 3) else ""
        self.lbl_sel_user.setText(f"{uname} (ID {uid})")

        # Rolle setzen
        idx = self.role_edit.findText(role)
        if idx >= 0:
            self.role_edit.setCurrentIndex(idx)

        # Eigener Benutzer -> Rolle nicht änderbar
        if uid == self.current_user_id:
            self.role_edit.setEnabled(False)
        else:
            self.role_edit.setEnabled(True)

        # Kliniken setzen
        if clinics == "ALL":
            self.chk_all_edit.setChecked(True)
        else:
            self.chk_all_edit.setChecked(False)
            chosen = {c.strip() for c in clinics.split(",") if c.strip()}
            for name, cb in self.chk_edit.items():
                cb.setChecked(name in chosen)

    # --- DB / Aktionen ---
    def refresh(self):
        rows = list_users()
        self.table.setRowCount(len(rows))
        for r, (id_, uname, role, clinics) in enumerate(rows):
            for c, val in enumerate([id_, uname, role, clinics]):
                self.table.setItem(r, c, QTableWidgetItem("" if val is None else str(val)))
        self.table.resizeColumnsToContents()

    def on_add_user(self):
        uname = self.name_add.text().strip()
        pwd = self.pwd_add.text()
        role = self.role_add.currentText()
        if not uname or not pwd:
            QMessageBox.warning(self, "Validierung", "Benutzername und Passwort erforderlich."); return
        clinics = "ALL" if self.chk_all_add.isChecked() else ",".join([n for n, cb in self.chk_add.items() if cb.isChecked()])
        if clinics == "":
            QMessageBox.warning(self, "Validierung", "Mindestens eine Klinik wählen – oder 'Alle Kliniken'."); return
        try:
            add_user(uname, pwd, role, clinics)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", "Benutzer konnte nicht angelegt werden:\n" + str(e)); return
        self.name_add.clear(); self.pwd_add.clear(); self.chk_all_add.setChecked(False)
        for cb in self.chk_add.values(): cb.setChecked(False)
        self.refresh(); QMessageBox.information(self, "Erstellt", f"Benutzer '{uname}' wurde angelegt.")

    def on_save_selected(self):
        uid = self._selected_user_id()
        if uid is None:
            QMessageBox.information(self, "Auswahl", "Bitte zuerst einen Benutzer auswählen."); return

        new_role = self.role_edit.currentText()
        new_clinics = "ALL" if self.chk_all_edit.isChecked() else ",".join([n for n, cb in self.chk_edit.items() if cb.isChecked()])
        if new_clinics == "":
            QMessageBox.warning(self, "Validierung", "Mindestens eine Klinik wählen – oder 'Alle Kliniken'."); return

        # Sicherheitsregel: Ein Admin darf sich selbst NICHT die Admin-Rechte entziehen
        if uid == self.current_user_id:
            current_role = self.table.item(self.table.currentRow(), 2).text()
            if current_role == "Admin" and new_role != "Admin":
                QMessageBox.warning(
                    self, "Nicht erlaubt",
                    "Du kannst dir selbst nicht die Admin-Rechte entziehen.\nBitte wähle zuerst einen anderen Admin, der dich herabstuft."
                )
                return

        try:
            with self.conn:
                self.conn.execute("UPDATE users SET role=?, clinics=? WHERE id=?", (new_role, new_clinics, uid))
                self.conn.execute("INSERT INTO audit_log(action, entity, entity_id, details) VALUES(?,?,?,?)",
                                  ("user_update", "user", uid, json.dumps({"role": new_role, "clinics": new_clinics}, ensure_ascii=False)))
        except Exception as e:
            QMessageBox.warning(self, "Fehler", "Speichern fehlgeschlagen:\n" + str(e)); return

        self.refresh(); QMessageBox.information(self, "Gespeichert", "Rolle & Kliniken aktualisiert.")

    def on_delete_selected(self):
        uid = self._selected_user_id()
        if uid is None:
            QMessageBox.information(self, "Auswahl", "Bitte zuerst einen Benutzer auswählen."); return
        if uid == self.current_user_id:
            QMessageBox.warning(self, "Nicht erlaubt", "Du kannst dein eigenes Konto nicht löschen."); return
        row = self.table.currentRow()
        uname = self.table.item(row, 1).text() if row >= 0 else str(uid)
        if QMessageBox.question(self, "Benutzer löschen",
                                f"Benutzer '{uname}' (ID {uid}) wirklich löschen?") != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_user(uid)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", "Löschen fehlgeschlagen:\n" + str(e)); return
        self.refresh(); QMessageBox.information(self, "Gelöscht", f"Benutzer '{uname}' wurde gelöscht.")

    def _after_clinic_change(self):
        self._build_clinic_checkboxes(target="add")
        self._build_clinic_checkboxes(target="edit")
        self._reload_clinic_select()
        if self.on_clinics_changed:
            self.on_clinics_changed()

    def on_add_clinic(self):
        name = self.new_clinic_name.text().strip()
        if not name:
            QMessageBox.information(self, "Eingabe", "Bitte Klinikname eingeben."); return
        try:
            add_clinic(name)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", "Klinik konnte nicht angelegt werden:\n" + str(e)); return
        self.new_clinic_name.clear(); self._after_clinic_change()
        QMessageBox.information(self, "Klinik", f"Klinik '{name}' hinzugefügt.")

    def on_delete_clinic(self):
        name = self.clinic_delete_select.currentText().strip()
        if not name:
            QMessageBox.information(self, "Auswahl", "Bitte Klinik auswählen."); return
        if QMessageBox.question(self, "Klinik löschen", f"Klinik '{name}' wirklich löschen?") != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_clinic(name)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", "Klinik konnte nicht gelöscht werden:\n" + str(e)); return
        self._after_clinic_change(); QMessageBox.information(self, "Klinik", f"Klinik '{name}' gelöscht.")
