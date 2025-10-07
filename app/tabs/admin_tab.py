# app/tabs/admin_tab.py
from typing import Optional, Callable
import sqlite3, json, bcrypt
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit, QComboBox, QCheckBox,
    QPushButton, QTableWidget, QTableWidgetItem, QGroupBox, QAbstractItemView, QMessageBox, QFrame,
    QDialog, QDialogButtonBox
)
from auth import list_users, add_user, delete_user
from db import add_clinic  # Kliniken-Insert über eure DB-Kapselung


# ---------- kompakte UI-/DB-Helfer ----------
def msg_info(parent, title, text): QMessageBox.information(parent, title, text)
def msg_warn(parent, title, text): QMessageBox.warning(parent, title, text)
def msg_err(parent, title, text):  QMessageBox.critical(parent, title, text)
def msg_yes(parent, title, text) -> bool:
    return QMessageBox.question(parent, title, text) == QMessageBox.StandardButton.Yes

def run_sql(conn: sqlite3.Connection, sql: str, params: tuple = (), fetch: bool = False):
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall() if fetch else None
    conn.commit()
    return cur.rowcount, rows


# ---------- einklappbare Sektion ----------
class CollapsibleSection(QWidget):
    toggled = pyqtSignal(bool)
    def __init__(self, title: str, content: QWidget, start_collapsed: bool = True, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._btn = QPushButton(("▶ " if start_collapsed else "▼ ") + title)
        self._btn.setCheckable(True)
        self._btn.setChecked(start_collapsed if False else not start_collapsed)  # defensive: bleibt wie vorher
        self._btn.setStyleSheet("QPushButton { text-align: left; padding: 8px 10px; border-radius: 8px; }")
        self._btn.toggled.connect(self._on_toggled)
        frame = QFrame(); frame.setFrameShape(QFrame.Shape.StyledPanel)
        lay_in = QVBoxLayout(frame); lay_in.setContentsMargins(10,8,10,10); lay_in.addWidget(content)
        self._content = frame; self._content.setVisible(not start_collapsed)
        lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.addWidget(self._btn); lay.addWidget(self._content)

    def _on_toggled(self, checked: bool):
        self._content.setVisible(checked)
        self._btn.setText(("▼ " if checked else "▶ ") + self._btn.text()[2:])
        self.toggled.emit(checked)

    def set_expanded(self, expanded: bool):
        self._btn.blockSignals(True)
        self._btn.setChecked(expanded)
        self._on_toggled(expanded)
        self._btn.blockSignals(False)


# ---------- AdminTab ----------
class AdminTab(QWidget):
    """
    Benutzer- & Klinikverwaltung:
    - Benutzerübersicht (lesen)
    - Benutzer anlegen (Passwort ≥ 8 Zeichen)
    - Benutzer bearbeiten (Rolle/Kliniken ändern, Passwort zurücksetzen, löschen)
    - Kliniken verwalten (hinzufügen/löschen, optionaler Schutz via is_system)
    - Schutz: kein Self-Delete / keine Self-Demotion
    """
    def __init__(self, conn: sqlite3.Connection, current_user_id: int, on_clinics_changed: Optional[Callable] = None):
        super().__init__()
        self.conn = conn
        self.current_user_id = current_user_id
        self.on_clinics_changed = on_clinics_changed
        try:
            self.conn.execute("PRAGMA foreign_keys = ON;")
        except Exception:
            pass

        # 1) Benutzerliste
        self.gb_list = QGroupBox("Benutzerübersicht")
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["ID", "Benutzername", "Rolle", "Kliniken"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSortingEnabled(True); self.table.sortItems(1)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._load_selected_into_form)
        lay_list = QVBoxLayout(self.gb_list); lay_list.addWidget(self.table)

        # 2) Benutzer anlegen
        self.name_add, self.pwd_add = QLineEdit(), QLineEdit()
        self.pwd_add.setEchoMode(QLineEdit.EchoMode.Password)
        self.pwd_add.setPlaceholderText("Passwort (min. 8 Zeichen)")
        self.role_add = QComboBox(); self.role_add.addItems(["Admin", "Techniker", "Viewer"])
        self.chk_all_add = QCheckBox("Alle Kliniken")
        self.clinic_box_add, self.clinic_layout_add = QWidget(), QHBoxLayout()
        self.clinic_box_add.setLayout(self.clinic_layout_add)
        self.chk_add: dict[str, QCheckBox] = {}
        self.chk_all_add.toggled.connect(lambda ch: self._toggle_all(self.chk_add, ch))
        self.btn_add_user = QPushButton("Benutzer hinzufügen"); self.btn_add_user.clicked.connect(self.on_add_user)
        w_add = QWidget(); f_add = QFormLayout(w_add)
        self.name_add.setPlaceholderText("z. B. a.mueller")
        f_add.addRow("Benutzername", self.name_add); f_add.addRow("Passwort", self.pwd_add)
        f_add.addRow("Rolle", self.role_add); f_add.addRow(self.chk_all_add)
        f_add.addRow("Kliniken", self.clinic_box_add); f_add.addRow(self.btn_add_user)
        self.sec_add = CollapsibleSection("Neuen Benutzer anlegen", w_add, True)

        # 3) Benutzer bearbeiten
        self.lbl_sel_user = QLabel("- kein Benutzer ausgewählt -")
        self.role_edit = QComboBox(); self.role_edit.addItems(["Admin", "Techniker", "Viewer"])
        self.chk_all_edit = QCheckBox("Alle Kliniken")
        self.clinic_box_edit, self.clinic_layout_edit = QWidget(), QHBoxLayout()
        self.clinic_box_edit.setLayout(self.clinic_layout_edit)
        self.chk_edit: dict[str, QCheckBox] = {}
        self.chk_all_edit.toggled.connect(lambda ch: self._toggle_all(self.chk_edit, ch))
        self.btn_save_perm = QPushButton("Änderungen speichern")
        self.btn_delete_user = QPushButton("Benutzer löschen")
        self.btn_reset_pw = QPushButton("Passwort zurücksetzen…")
        self.btn_save_perm.clicked.connect(self.on_save_selected)
        self.btn_delete_user.clicked.connect(self.on_delete_selected)
        self.btn_reset_pw.clicked.connect(self.on_reset_password)
        w_edit = QWidget(); f_edit = QFormLayout(w_edit)
        row_actions = QHBoxLayout()
        row_actions.addWidget(self.btn_save_perm); row_actions.addStretch(1)
        row_actions.addWidget(self.btn_reset_pw); row_actions.addWidget(self.btn_delete_user)
        f_edit.addRow("Auswahl", self.lbl_sel_user)
        f_edit.addRow("Rolle", self.role_edit)
        f_edit.addRow(self.chk_all_edit)
        f_edit.addRow("Kliniken", self.clinic_box_edit)
        f_edit.addRow(row_actions)
        self.sec_edit = CollapsibleSection("Ausgewählten Benutzer bearbeiten", w_edit, True)

        # 4) Kliniken verwalten
        self.new_clinic_name = QLineEdit(); self.new_clinic_name.setPlaceholderText("Neue Klinik…")
        self.btn_add_clinic = QPushButton("Klinik hinzufügen"); self.btn_add_clinic.clicked.connect(self.on_add_clinic)
        self.clinic_delete_select = QComboBox()
        self.btn_del_clinic = QPushButton("Klinik löschen"); self.btn_del_clinic.clicked.connect(self.on_delete_clinic)
        w_clin = QWidget(); lay_clin = QVBoxLayout(w_clin)
        row_add = QHBoxLayout(); row_add.addWidget(self.new_clinic_name); row_add.addWidget(self.btn_add_clinic)
        row_del = QHBoxLayout(); row_del.addWidget(self.clinic_delete_select); row_del.addWidget(self.btn_del_clinic)
        lay_clin.addLayout(row_add); lay_clin.addLayout(row_del)
        self.sec_clin = CollapsibleSection("Kliniken verwalten", w_clin, True)

        # exklusives Öffnen
        for sec in (self.sec_add, self.sec_edit, self.sec_clin):
            sec.toggled.connect(lambda ch, s=sec: self._exclusive_open(s, ch))

        # Layout
        main = QVBoxLayout(self)
        main.addWidget(self.gb_list); main.addWidget(self.sec_add)
        main.addWidget(self.sec_edit); main.addWidget(self.sec_clin); main.addStretch(1)

        # initial
        self.refresh_users()
        self._rebuild_clinic_checkboxes()
        self._reload_clinic_select()

    # ---------- interne Helfer ----------
    def _exclusive_open(self, sender: CollapsibleSection, checked: bool):
        if not checked:
            return
        for sec in (self.sec_add, self.sec_edit, self.sec_clin):
            if sec is not sender:
                sec.set_expanded(False)

    def _toggle_all(self, chk_map: dict[str, QCheckBox], checked: bool):
        for cb in chk_map.values():
            cb.setChecked(False if checked else cb.isChecked())
            cb.setEnabled(not checked)

    def _clinics_schema(self) -> tuple[str, bool]:
        cur = self.conn.cursor()
        cur.execute("PRAGMA table_info(clinics);")
        cols = {row[1] for row in cur.fetchall()}
        pk_col = "id" if "id" in cols else "rowid"
        has_is_system = "is_system" in cols
        return pk_col, has_is_system

    def _fetch_clinics(self):
        pk, has_sys = self._clinics_schema()
        if has_sys:
            _, rows = run_sql(self.conn, f"SELECT {pk}, name, is_system FROM clinics ORDER BY name COLLATE NOCASE;", (), True)
        else:
            _, rows = run_sql(self.conn, f"SELECT {pk}, name, 0 FROM clinics ORDER BY name COLLATE NOCASE;", (), True)
        return rows or []

    def _rebuild_checkbox_row(self, layout: QHBoxLayout, chk_map: dict[str, QCheckBox], names: list[str]):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
        chk_map.clear()
        for n in names:
            cb = QCheckBox(n)
            layout.addWidget(cb)
            chk_map[n] = cb
        layout.addStretch(1)

    def _rebuild_clinic_checkboxes(self):
        names = [name for (_cid, name, _sys) in self._fetch_clinics()]
        self._rebuild_checkbox_row(self.clinic_layout_add,  self.chk_add,  names)
        self._rebuild_checkbox_row(self.clinic_layout_edit, self.chk_edit, names)

    def _reload_clinic_select(self):
        self.clinic_delete_select.clear()
        for cid, name, is_system in self._fetch_clinics():
            self.clinic_delete_select.addItem(f"{name} {'(🔒)' if is_system else ''}", cid)

    def refresh_users(self):
        rows = list_users()
        self.table.setRowCount(len(rows))
        for r, (id_, uname, role, clinics) in enumerate(rows):
            for c, val in enumerate((id_, uname, role, clinics)):
                self.table.setItem(r, c, QTableWidgetItem("" if val is None else str(val)))
        self.table.resizeColumnsToContents()

    def _selected_user_id(self) -> Optional[int]:
        row = self.table.currentRow()
        return None if row < 0 else int(self.table.item(row, 0).text())

    # ---------- Events ----------
    def _load_selected_into_form(self):
        """FEHLTE vorher: lädt die aktuell ausgewählte Tabellenzeile in das Bearbeitungsformular."""
        uid = self._selected_user_id()
        if uid is None:
            self.lbl_sel_user.setText("- kein Benutzer ausgewählt -")
            self.role_edit.setEnabled(True); self.role_edit.setCurrentIndex(0)
            self.chk_all_edit.setChecked(False)
            for cb in self.chk_edit.values():
                cb.setChecked(False)
            return

        row = self.table.currentRow()
        uname = self.table.item(row, 1).text()
        role = self.table.item(row, 2).text()
        clinics = (self.table.item(row, 3).text() if self.table.item(row, 3) else "") or ""

        self.lbl_sel_user.setText(f"{uname} (ID {uid})")

        idx = self.role_edit.findText(role)
        if idx >= 0:
            self.role_edit.setCurrentIndex(idx)

        # sich selbst nicht von Admin wegsetzen
        self.role_edit.setEnabled(not (uid == self.current_user_id and role == "Admin"))

        if clinics == "ALL":
            self.chk_all_edit.setChecked(True)
            for cb in self.chk_edit.values():
                cb.setChecked(False)
                cb.setEnabled(False)
        else:
            self.chk_all_edit.setChecked(False)
            for cb in self.chk_edit.values():
                cb.setEnabled(True)
            chosen = {c.strip() for c in clinics.split(",") if c.strip()}
            for name, cb in self.chk_edit.items():
                cb.setChecked(name in chosen)

    # ---------- Benutzeraktionen ----------
    def on_add_user(self):
        uname = self.name_add.text().strip()
        pwd = self.pwd_add.text()
        role = self.role_add.currentText()

        if not uname:
            return msg_warn(self, "Validierung", "Benutzername ist erforderlich.")
        if len(pwd or "") < 8:
            return msg_warn(self, "Validierung", "Das Passwort muss mindestens 8 Zeichen lang sein.")

        clinics = "ALL" if self.chk_all_add.isChecked() else ",".join(
            [n for n, cb in self.chk_add.items() if cb.isChecked()]
        )
        if not clinics:
            return msg_warn(self, "Validierung", "Mindestens eine Klinik wählen – oder 'Alle Kliniken'.")

        try:
            add_user(uname, pwd, role, clinics)
        except Exception as e:
            return msg_warn(self, "Fehler", "Benutzer konnte nicht angelegt werden:\n" + str(e))

        # Formular zurücksetzen
        self.name_add.clear()
        self.pwd_add.clear()
        self.chk_all_add.setChecked(False)
        for cb in self.chk_add.values():
            cb.setChecked(False)

        self.refresh_users()
        msg_info(self, "Erstellt", f"Benutzer '{uname}' wurde angelegt.")

    def on_save_selected(self):
        uid = self._selected_user_id()
        if uid is None:
            return msg_info(self, "Auswahl", "Bitte zuerst einen Benutzer auswählen.")

        row = self.table.currentRow()
        current_role = self.table.item(row, 2).text() if row >= 0 else ""
        new_role = self.role_edit.currentText()
        new_clinics = "ALL" if self.chk_all_edit.isChecked() else ",".join(
            [n for n, cb in self.chk_edit.items() if cb.isChecked()]
        )
        if not new_clinics:
            return msg_warn(self, "Validierung", "Mindestens eine Klinik wählen – oder 'Alle Kliniken'.")

        # Self-Demotion verhindern
        if uid == self.current_user_id and current_role == "Admin" and new_role != "Admin":
            return msg_warn(self, "Nicht erlaubt", "Du kannst dir selbst nicht die Admin-Rechte entziehen.")

        try:
            with self.conn:
                self.conn.execute("UPDATE users SET role=?, clinics=? WHERE id=?", (new_role, new_clinics, uid))
                # optionales Audit:
                self.conn.execute(
                    "INSERT INTO audit_log(action, entity, entity_id, details) VALUES(?,?,?,?)",
                    ("user_update", "user", uid, json.dumps({"role": new_role, "clinics": new_clinics}, ensure_ascii=False))
                )
        except Exception as e:
            return msg_warn(self, "Fehler", "Speichern fehlgeschlagen:\n" + str(e))

        self.refresh_users()
        msg_info(self, "Gespeichert", "Rolle & Kliniken aktualisiert.")

    def on_delete_selected(self):
        uid = self._selected_user_id()
        if uid is None:
            return msg_info(self, "Auswahl", "Bitte zuerst einen Benutzer auswählen.")
        # Self-Delete verhindern
        if uid == self.current_user_id:
            return msg_warn(self, "Nicht erlaubt", "Du kannst dein eigenes Konto nicht löschen.")

        row = self.table.currentRow()
        uname = self.table.item(row, 1).text() if row >= 0 else str(uid)
        if not msg_yes(self, "Benutzer löschen", f"Benutzer '{uname}' (ID {uid}) wirklich löschen?"):
            return

        try:
            delete_user(uid)
        except Exception as e:
            return msg_warn(self, "Fehler", "Löschen fehlgeschlagen:\n" + str(e))

        self.refresh_users()
        msg_info(self, "Gelöscht", f"Benutzer '{uname}' wurde gelöscht.")

    def on_reset_password(self):
        uid = self._selected_user_id()
        if uid is None:
            return msg_info(self, "Auswahl", "Bitte zuerst einen Benutzer auswählen.")
        row = self.table.currentRow()
        uname = self.table.item(row, 1).text() if row >= 0 else f"ID {uid}"

        # Dialog
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Passwort zurücksetzen – {uname}")
        le_pw1, le_pw2 = QLineEdit(), QLineEdit()
        for le in (le_pw1, le_pw2):
            le.setEchoMode(QLineEdit.EchoMode.Password)
        le_pw1.setPlaceholderText("Neues Passwort (min. 8 Zeichen)")
        le_pw2.setPlaceholderText("Wiederholen")
        form = QFormLayout(dlg)
        form.addRow("Neues Passwort:", le_pw1)
        form.addRow("Wiederholen:", le_pw2)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=dlg)
        form.addRow(btns)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        pw1, pw2 = le_pw1.text().strip(), le_pw2.text().strip()
        if len(pw1) < 8:
            return msg_warn(self, "Ungültig", "Das Passwort muss mindestens 8 Zeichen lang sein.")
        if pw1 != pw2:
            return msg_warn(self, "Ungültig", "Die Passwörter stimmen nicht überein.")
        if not msg_yes(self, "Bestätigen", f"Passwort für Benutzer „{uname}“ wirklich zurücksetzen?"):
            return

        hashed = bcrypt.hashpw(pw1.encode("utf-8"), bcrypt.gensalt())
        try:
            with self.conn:
                self.conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hashed, uid))
                # optionales Audit:
                self.conn.execute(
                    "INSERT INTO audit_log(action, entity, entity_id, details) VALUES(?,?,?,?)",
                    ("user_password_reset", "user", uid, json.dumps({"username": uname}, ensure_ascii=False))
                )
        except Exception as e:
            return msg_warn(self, "Fehler", "Passwort konnte nicht gesetzt werden:\n" + str(e))

        msg_info(self, "Erfolg", f"Passwort für „{uname}“ wurde zurückgesetzt.")

    # ---------- Kliniken ----------
    def _after_clinic_change(self):
        self._rebuild_clinic_checkboxes()
        self._reload_clinic_select()
        if self.on_clinics_changed:
            self.on_clinics_changed()

    def on_add_clinic(self):
        name = self.new_clinic_name.text().strip()
        if not name:
            return msg_info(self, "Eingabe", "Bitte Klinikname eingeben.")
        try:
            add_clinic(name)
        except Exception as e:
            return msg_warn(self, "Fehler", "Klinik konnte nicht angelegt werden:\n" + str(e))
        self.new_clinic_name.clear()
        self._after_clinic_change()
        msg_info(self, "Klinik", f"Klinik '{name}' hinzugefügt.")

    def on_delete_clinic(self):
        idx = self.clinic_delete_select.currentIndex()
        if idx < 0:
            return msg_info(self, "Auswahl", "Bitte Klinik auswählen.")
        clinic_pk = self.clinic_delete_select.itemData(idx, Qt.ItemDataRole.UserRole)
        label = self.clinic_delete_select.currentText().strip()
        name = label.replace(" (🔒)", "")
        if clinic_pk is None:
            return msg_err(self, "Fehler", "Für die gewählte Klinik ist keine PK-ID hinterlegt.")

        pk, has_sys = self._clinics_schema()

        # Systemschutz prüfen
        if has_sys:
            _, rows = run_sql(self.conn, f"SELECT is_system FROM clinics WHERE {pk}=?", (clinic_pk,), True)
            if rows and int(rows[0][0]) == 1:
                return msg_info(self, "Geschützt", f"Die Klinik '{name}' ist geschützt und kann nicht gelöscht werden.")

        if not msg_yes(self, "Klinik löschen", f"Klinik '{name}' wirklich löschen?"):
            return

        try:
            affected, _ = run_sql(self.conn, f"DELETE FROM clinics WHERE {pk}=?", (clinic_pk,))
        except sqlite3.IntegrityError as e:
            return msg_err(
                self, "Löschen nicht möglich",
                "Diese Klinik ist noch verknüpft (z. B. Benutzer/Fälle).\n"
                "Bitte Verknüpfungen lösen oder ON DELETE-Regeln anpassen.\n\nDetails:\n" + str(e)
            )
        except Exception as e:
            return msg_warn(self, "Fehler", "Klinik konnte nicht gelöscht werden:\n" + str(e))

        if affected == 0:
            self._reload_clinic_select()
            return msg_warn(self, "Nicht gelöscht", "Die Klinik wurde nicht gefunden oder bereits entfernt.")

        self._after_clinic_change()
        msg_info(self, "Klinik", f"Klinik '{name}' gelöscht.")
