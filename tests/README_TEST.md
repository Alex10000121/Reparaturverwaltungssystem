# Testanleitung – Reparaturverwaltungssystem

Dieses Dokument beschreibt, wie die automatisierten Tests des Projekts ausgeführt werden können.  
Alle Testskripte befinden sich im Ordner [`tests/`](./tests).

---

## Start

1. Stelle sicher, dass **Python 3.13** installiert ist (virtuelle Umgebung empfohlen).
2. Abhängigkeiten installieren:
   ```bash
   pip install -r requirements-test.txt
   ```

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



## Teststruktur

| Datei                           | Zweck                                                                              |
| ------------------------------- | ---------------------------------------------------------------------------------- |
| `test_main_tabs.py`             | Testet das Hauptfenster (`Main`) und die Tabs je nach Benutzerrolle                |
| `test_create_open_done_flow.py` | Überprüft den kompletten Ablauf von Erfassen → Anzeigen → Abschließen von Fällen   |
| `test_admin_rules.py`           | Prüft Admin-Funktionen wie Benutzerverwaltung, Klinikverwaltung und Berechtigungen |
| `test_buffer_sync.py`           | Testet das Schreiben, Zwischenspeichern und spätere Synchronisieren von Änderungen |
| `test_clinic_visibility.py`     | Überprüft, ob Benutzer nur die erlaubten Kliniken sehen                            |


