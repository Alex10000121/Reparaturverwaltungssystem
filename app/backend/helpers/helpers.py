from typing import Optional, List
from app.backend.db.db import list_clinics


def clinics_of_user(role: str, clinics_csv: str) -> Optional[List[str]]:
    """
    Gibt die Liste der Kliniken zurück, auf die ein Benutzer Zugriff hat.
    - Admins oder Benutzer mit 'ALL' haben Zugriff auf alle Kliniken (Rückgabe: None).
    - Für alle anderen wird die kommagetrennte Liste aus clinics_csv verarbeitet.
    """
    if role == "Admin" or clinics_csv == "ALL":
        return None

    # CSV-Zeichenkette in saubere Liste umwandeln
    clinics = [c.strip() for c in clinics_csv.split(",") if c.strip()]
    return clinics or None


def clinic_choices_for(role: str, clinics_csv: str) -> List[str]:
    """
    Gibt die tatsächlich verfügbaren Kliniken für einen Benutzer zurück.
    Admins sehen alle Kliniken, andere nur die, die ihnen zugewiesen sind.
    """
    all_clinics = list_clinics()
    allowed = clinics_of_user(role, clinics_csv)

    # Wenn allowed None ist, darf der Benutzer alle sehen
    if allowed is None:
        return all_clinics

    # Andernfalls nur die Schnittmenge
    return [c for c in all_clinics if c in allowed]
