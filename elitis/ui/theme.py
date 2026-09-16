"""Dark theme QSS for the whole application."""

COLORS = {
    "bg":           "#1e1e2e",
    "surface":      "#2a2a3e",
    "surface2":     "#313147",
    "border":       "#44445a",
    "accent":       "#8b5cf6",
    "accent_hover": "#a78bfa",
    "text":         "#e2e8f0",
    "text_dim":     "#94a3b8",
    "danger":       "#f87171",
    "success":      "#4ade80",
}


def stylesheet() -> str:
    c = COLORS
    return f"""
QWidget {{
    background-color: {c['bg']};
    color: {c['text']};
    font-family: Segoe UI, Arial, sans-serif;
    font-size: 13px;
}}

QMainWindow, QDialog {{
    background-color: {c['bg']};
}}

QTabWidget::pane {{
    border: 1px solid {c['border']};
    background-color: {c['surface']};
}}

QTabBar::tab {{
    background: {c['surface2']};
    color: {c['text_dim']};
    padding: 6px 18px;
    border: 1px solid {c['border']};
    border-bottom: none;
    margin-right: 2px;
}}

QTabBar::tab:selected {{
    background: {c['surface']};
    color: {c['text']};
    border-bottom: 2px solid {c['accent']};
}}

QTabBar::tab:hover {{
    color: {c['text']};
}}

QPushButton {{
    background-color: {c['surface2']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 4px;
    padding: 5px 14px;
    min-height: 26px;
}}

QPushButton:hover {{
    background-color: {c['accent']};
    border-color: {c['accent']};
}}

QPushButton:pressed {{
    background-color: {c['accent_hover']};
}}

QPushButton:disabled {{
    color: {c['text_dim']};
    border-color: {c['border']};
}}

QPushButton#accent {{
    background-color: {c['accent']};
    border-color: {c['accent']};
    font-weight: bold;
}}

QPushButton#accent:hover {{
    background-color: {c['accent_hover']};
}}

QLabel {{
    color: {c['text']};
    background: transparent;
}}

QLabel#dim {{
    color: {c['text_dim']};
    font-size: 11px;
}}

QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {c['surface2']};
    border: 1px solid {c['border']};
    border-radius: 4px;
    padding: 4px 8px;
    color: {c['text']};
    selection-background-color: {c['accent']};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {c['accent']};
}}

QSpinBox, QDoubleSpinBox {{
    background-color: {c['surface2']};
    border: 1px solid {c['border']};
    border-radius: 4px;
    padding: 3px 6px;
    color: {c['text']};
    min-width: 70px;
}}

QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {c['accent']};
}}

QComboBox {{
    background-color: {c['surface2']};
    border: 1px solid {c['border']};
    border-radius: 4px;
    padding: 4px 8px;
    color: {c['text']};
    min-width: 100px;
}}

QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

QComboBox QAbstractItemView {{
    background-color: {c['surface2']};
    border: 1px solid {c['border']};
    selection-background-color: {c['accent']};
}}

QSlider::groove:horizontal {{
    height: 4px;
    background: {c['border']};
    border-radius: 2px;
}}

QSlider::handle:horizontal {{
    width: 14px;
    height: 14px;
    margin: -5px 0;
    background: {c['accent']};
    border-radius: 7px;
}}

QSlider::sub-page:horizontal {{
    background: {c['accent']};
    border-radius: 2px;
}}

QCheckBox {{
    spacing: 6px;
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {c['border']};
    border-radius: 3px;
    background: {c['surface2']};
}}

QCheckBox::indicator:checked {{
    background: {c['accent']};
    border-color: {c['accent']};
}}

QScrollBar:vertical {{
    width: 8px;
    background: {c['surface']};
}}

QScrollBar::handle:vertical {{
    background: {c['border']};
    border-radius: 4px;
    min-height: 20px;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar:horizontal {{
    height: 8px;
    background: {c['surface']};
}}

QScrollBar::handle:horizontal {{
    background: {c['border']};
    border-radius: 4px;
    min-width: 20px;
}}

QGroupBox {{
    border: 1px solid {c['border']};
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 8px;
    font-weight: bold;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {c['accent']};
}}

QStatusBar {{
    background: {c['surface']};
    border-top: 1px solid {c['border']};
}}

QToolTip {{
    background-color: {c['surface2']};
    color: {c['text']};
    border: 1px solid {c['border']};
    padding: 4px;
}}
"""
