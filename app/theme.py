from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

# Einheitliche, moderne Typo + mehr Politur für Inputs/Buttons/Tabellen
LIGHT_QSS = """
* { font-family: "Segoe UI", "Inter", Arial, sans-serif; }

QMainWindow { background: #fafafa; }
QToolBar { background: #ffffff; border-bottom: 1px solid #ddd; }
QTabWidget::pane { border: 1px solid #ddd; }
QGroupBox { background: #fff; border: 1px solid #e5e5e5; border-radius: 12px; padding: 14px; margin-top: 14px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
QLineEdit, QTextEdit, QComboBox, QDateEdit { background: #fff; }

/* Globale Schriftgrößen (einheitlich 16px) */
QLabel { font-size: 16px; }
QLineEdit, QTextEdit, QComboBox, QDateEdit { font-size: 16px; padding: 8px 10px; border: 1px solid #d7d7d7; border-radius: 8px; }
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QDateEdit:focus {
  border: 1px solid #5b9aff;      /* Fokusring */
  box-shadow: 0 0 0 3px rgba(91,154,255,.15);
}
QPushButton { font-size: 16px; padding: 8px 14px; border-radius: 10px; border: 1px solid #dcdcdc; background: #f6f6f6; }
QPushButton:hover { background: #efefef; }
QPushButton:pressed { background: #e8e8e8; }
QToolButton { font-size: 16px; }
QStatusBar { font-size: 16px; }

/* Tabs (Titel) */
QTabBar::tab { font-size: 16px; padding: 8px 12px; }

/* Tabellen */
QTableWidget, QTableView { font-size: 16px; }
QHeaderView::section {
  background: #f5f5f7;
  border: none;
  border-bottom: 1px solid #ddd;
  padding: 8px 10px;
  font-weight: 600;
}
QTableWidget { gridline-color: #eee; }
QTableView { alternate-background-color: #fafafa; }
"""

DARK_QSS = """
* { color: #e8e8e8; font-family: "Segoe UI", "Inter", Arial, sans-serif; }
QMainWindow { background: #111; }
QToolBar { background: #1a1a1a; border-bottom: 1px solid #333; }
QTabWidget::pane { border: 1px solid #333; }
QWidget { background-color: #111; }
QGroupBox { background: #171717; border: 1px solid #333; border-radius: 12px; padding: 14px; margin-top: 14px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
QLineEdit, QTextEdit, QComboBox, QDateEdit {
  background: #1d1d1d; border: 1px solid #333; border-radius: 8px; padding: 8px 10px;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QDateEdit:focus {
  border: 1px solid #8ab4ff;
  box-shadow: 0 0 0 3px rgba(138,180,255,.12);
}
QPushButton { background: #2a2a2a; border: 1px solid #444; border-radius: 10px; padding: 8px 14px; font-size: 16px; }
QPushButton:hover { background: #333; }
QHeaderView::section { background: #1a1a1a; border: none; border-bottom: 1px solid #333; padding: 8px 10px; font-weight: 600; }
QTableWidget { gridline-color: #333; }

/* Globale Schriftgrößen (einheitlich 16px) */
QLabel { font-size: 16px; }
QLineEdit, QTextEdit, QComboBox, QDateEdit { font-size: 16px; }
QToolButton { font-size: 16px; }
QStatusBar { font-size: 16px; }

/* Tabs (Titel) */
QTabBar::tab { font-size: 16px; padding: 8px 12px; }

/* Tabellen */
QTableWidget, QTableView { font-size: 16px; }
QHeaderView::section { font-size: 16px; }
QTableView { alternate-background-color: #141414; }
"""

def apply_app_theme(app: QApplication):
    """Setzt das Stylesheet global (auch für den Login)."""
    try:
        scheme = app.styleHints().colorScheme()
    except Exception:
        scheme = Qt.ColorScheme.Light
    app.setStyleSheet(DARK_QSS if scheme == Qt.ColorScheme.Dark else LIGHT_QSS)

def apply_system_theme():
    app = QApplication.instance()
    if not app:
        return
    apply_app_theme(app)
