import sqlite3
import time
import os
import sys

# Pfad zur Datenbank (liegt in ../backend/app.db)
DB = os.path.join(os.path.dirname(__file__), "..","app", "backend", "db", "resources", "app.db")
DB = os.path.abspath(DB)  # für absolute Pfadauflösung

if not os.path.exists(DB):
    print(f"Fehler: Datenbankdatei nicht gefunden unter: {DB}")
    sys.exit(1)

try:
    con = sqlite3.connect(DB, timeout=0.5)
    cur = con.cursor()
    cur.execute("BEGIN EXCLUSIVE")
    print("----------------------------------------------------")
    print(f"Datenbank '{DB}' ist jetzt EXKLUSIV GESPERRT.")
    print("Drücke STRG+C, um die Sperre wieder freizugeben.")
    print("----------------------------------------------------")

    while True:
        time.sleep(1)

except KeyboardInterrupt:
    print("\nAbbruch durch Benutzer erkannt – Sperre wird aufgehoben...")

except sqlite3.OperationalError as e:
    print(f"Fehler beim Sperren der Datenbank: {e}")

finally:
    try:
        con.rollback()
        con.close()
        print("----------------------------------------------------")
        print("Datenbank wurde wieder freigegeben.")
        print("----------------------------------------------------")
    except Exception:
        pass
