from typing import Optional, Tuple
from PyQt6.QtWidgets import (
    QWidget, QLineEdit, QPushButton, QFormLayout,
    QVBoxLayout, QMessageBox
)
from PyQt6.QtCore import Qt
from app.backend.auth import authenticate


class Login(QWidget):
    """Einfache Login-Maske für die Reparaturverwaltung."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Reparaturverwaltung – Anmeldung")
        self.setMinimumWidth(380)

        # Eingabefelder
        self.user = QLineEdit()
        self.user.setPlaceholderText("Benutzername eingeben")
        self.user.setClearButtonEnabled(True)

        self.pwd = QLineEdit()
        self.pwd.setPlaceholderText("Passwort eingeben")
        self.pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self.pwd.returnPressed.connect(self._try_login)
        self.user.returnPressed.connect(self._try_login)

        # Anmelde-Button
        self.btn = QPushButton("Anmelden")
        self.btn.setDefault(True)
        self.btn.clicked.connect(self._try_login)

        # Layout
        form = QFormLayout()
        form.addRow("Benutzername", self.user)
        form.addRow("Passwort", self.pwd)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.btn, alignment=Qt.AlignmentFlag.AlignRight)

        # Authentifizierte Benutzerinfos (user_id, role, clinics_csv)
        self.authed: Optional[Tuple[int, str, str]] = None

    # ----------------------------
    # Login-Logik
    # ----------------------------
    def _try_login(self):
        """Prüft die Anmeldedaten und schließt das Fenster bei Erfolg."""
        username = self.user.text().strip()
        password = self.pwd.text()

        if not username or not password:
            QMessageBox.information(
                self,
                "Hinweis",
                "Bitte Benutzername und Passwort eingeben."
            )
            return

        creds = authenticate(username, password)
        if creds:
            self.authed = creds
            self.close()
        else:
            QMessageBox.warning(
                self,
                "Anmeldung fehlgeschlagen",
                "Der eingegebene Benutzername oder das Passwort ist nicht korrekt."
            )
            self.pwd.clear()
            self.pwd.setFocus()
