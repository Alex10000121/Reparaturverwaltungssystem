from typing import Optional, Tuple
from PyQt6.QtWidgets import QWidget, QLineEdit, QPushButton, QFormLayout, QVBoxLayout, QMessageBox
from app.backend.auth import authenticate

class Login(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Reparaturverwaltung — Login")
        self.setMinimumWidth(360)

        self.user = QLineEdit()
        self.pwd = QLineEdit(); self.pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self.btn = QPushButton("Anmelden"); self.btn.clicked.connect(self.on_login)

        form = QFormLayout(); form.addRow("Benutzername", self.user); form.addRow("Passwort", self.pwd)
        lay = QVBoxLayout(self); lay.addLayout(form); lay.addWidget(self.btn)
        self.authed: Optional[Tuple[int, str, str]] = None  # (user_id, role, clinics_csv)

    def on_login(self):
        creds = authenticate(self.user.text().strip(), self.pwd.text())
        if creds:
            self.authed = creds
            self.close()
        else:
            QMessageBox.warning(self, "Fehler", "Benutzer oder Passwort falsch.")
