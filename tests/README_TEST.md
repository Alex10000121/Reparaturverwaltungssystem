# Testanleitung – Reparaturverwaltungssystem

Dieses Dokument beschreibt, wie die automatisierten Tests des Projekts ausgeführt werden können.  
Alle Testskripte befinden sich im Ordner [`tests/`](./tests).

---

## Voraussetzungen

Bevor Tests ausgeführt werden können, müssen folgende Voraussetzungen erfüllt sein:

### 1. Python-Umgebung
- Python 3.11 oder neuer ist installiert.  
  Überprüfen:
  ```bash
  python --version
  ```
- Virtuelle Umgebung erstellen (empfohlen):
  ```bash
  python -m venv .venv
  .\.venv\Scripts\activate
  ```

### 2. Abhängigkeiten installieren
Installiere alle erforderlichen Pakete über die Datei `requirements.txt`:
```bash
pip install -r requirements-test.txt
```



---

## Tests ausführen

### 1. Alle Tests ausführen
Im Hauptverzeichnis des Projekts (dort, wo der `app`-Ordner liegt):
```bash
pytest
```

Mit detaillierter Ausgabe:
```bash
pytest -v
```

### 2. Einzelne Tests starten
Nur eine bestimmte Datei:
```bash
pytest tests/test_main_tabs.py
```

Nur Tests mit einem bestimmten Namen:
```bash
pytest -k "AdminTab"
```

---

## Teststruktur

| Datei | Zweck |
|-------|-------|
| `test_main_tabs.py` | Testet das Hauptfenster (`Main`) und die korrekte Anzeige der Tabs je nach Benutzerrolle |
| `test_create_open_done_flow.py` | Überprüft das Zusammenspiel zwischen Erfassen, Anzeigen und Abschließen von Fällen |
| `test_admin_rules.py` | Stellt sicher, dass Admin-spezifische Funktionen korrekt funktionieren |
| `test_buffer_sync.py` | Testet die Synchronisierung von lokal gepufferten Datenbankeinträgen |
| `test_clinic_visibility.py` | Überprüft die Sichtbarkeit von Kliniken entsprechend der Benutzerrolle |

---

## Hinweise

- Die Tests basieren auf `pytest` und verwenden teilweise `PyQt6`-Oberflächenkomponenten.
- PyQt6 kann ohne sichtbare GUI ausgeführt werden.  
  Falls Probleme auftreten, kann der Offscreen-Modus aktiviert werden:
  ```bash
  pytest --qt-offscreen
  ```

- Einige Tests erzeugen automatisch temporäre SQLite-Datenbanken.  
  Diese werden nach Testende gelöscht oder im Unterordner `.pytest_cache` abgelegt.

- Bei Fehlern oder zur Debug-Ausgabe:
  ```bash
  pytest -s -v
  ```

---

## Beispiel eines erfolgreichen Testlaufs

```
==================== test session starts ====================
collected 18 items

tests/test_main_tabs.py ........
tests/test_create_open_done_flow.py ....
tests/test_admin_rules.py ..
tests/test_clinic_visibility.py ..

==================== 18 passed in 3.14s =====================
```

---

## Tipp für PyCharm

Die Tests können direkt aus der IDE ausgeführt werden:

1. Rechtsklick auf den Ordner `tests`
2. Auswahl **Run 'pytest in tests'**
3. PyCharm zeigt die Testergebnisse übersichtlich in der Test-Ansicht an.

---

© 2025 – Reparaturverwaltungssystem  
Automatisierte Testausführung und Dokumentation
