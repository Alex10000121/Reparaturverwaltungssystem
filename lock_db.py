import sqlite3, time, os
DB = os.path.join(os.path.dirname(__file__), "resources", "app.db")
con = sqlite3.connect(DB, timeout=0.5)  # kurze Wartezeit -> schnell "locked"
cur = con.cursor()
cur.execute("BEGIN EXCLUSIVE")          # hält exklusiven Schreib-Lock
print("DB exklusiv gesperrt. Drücke STRG+C zum Freigeben.")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    con.rollback()
    con.close()
    print("DB wieder freigegeben.")
