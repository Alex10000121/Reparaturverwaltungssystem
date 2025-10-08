from typing import Optional, List
from app.backend.db.db import list_clinics

def clinics_of_user(role: str, clinics_csv: str) -> Optional[List[str]]:
    if role == "Admin" or clinics_csv == "ALL":
        return None
    cl = [c.strip() for c in clinics_csv.split(",") if c.strip()]
    return cl or None

def clinic_choices_for(role: str, clinics_csv: str) -> List[str]:
    all_db = list_clinics()
    allowed = clinics_of_user(role, clinics_csv)
    return all_db if allowed is None else [c for c in all_db if c in allowed]
