"""Presentation for generated panel tools; independent of saved configuration."""

TOOL_STYLE = """
QFrame[panelCard="true"] {
    background: #ffffff; border: 1px solid #dce3ed; border-radius: 8px;
}
QFrame[panelCard="true"][selected="true"] {
    border: 1px solid #2563eb; background: #f5f8ff;
}
QLabel { color: #334155; background: transparent; border: none; }
QLabel[panelTitle="true"] { color: #64748b; font-size: 11px; font-weight: 600; }
QLabel#value_label, QLabel[panelValue="true"] {
    color: #0f172a; font-size: 16px; font-weight: 600;
}
QPushButton {
    color: #334155; background: #f1f5f9; border: 1px solid #cbd5e1;
    border-radius: 6px; padding: 3px 8px; font-weight: 600;
}
QPushButton:hover { background: #e2e8f0; border-color: #94a3b8; }
QPushButton:pressed { background: #cbd5e1; }
QPushButton[panelPrimary="true"], QPushButton:checked {
    color: white; background: #2563eb; border-color: #2563eb;
}
QPushButton[panelPrimary="true"]:hover, QPushButton:checked:hover { background: #1d4ed8; }
QPushButton[panelPrimary="true"]:pressed { background: #1e40af; }
QPushButton:focus, QDoubleSpinBox:focus { border: 1px solid #0ea5e9; }
QPushButton:disabled {
    color: #94a3b8; background: #f1f5f9; border-color: #e2e8f0;
}
QSlider::groove:horizontal { height: 6px; background: #e2e8f0; border-radius: 3px; }
QSlider::sub-page:horizontal { background: #3b82f6; border-radius: 3px; }
QSlider::handle:horizontal {
    background: white; border: 2px solid #2563eb; width: 12px;
    margin: -5px 0; border-radius: 8px;
}
QSlider::handle:horizontal:hover, QSlider::handle:horizontal:focus { background: #dbeafe; }
QSlider::sub-page:horizontal:disabled { background: #cbd5e1; }
QSlider::handle:horizontal:disabled { border-color: #94a3b8; }
QDoubleSpinBox {
    color: #0f172a; background: #f8fafc; border: 1px solid #cbd5e1;
    border-radius: 6px; padding: 2px 4px; font-size: 14px;
}
QDoubleSpinBox:disabled { color: #94a3b8; }
QProgressBar {
    color: #0f172a; background: #e8eef6; border: none;
    border-radius: 6px; text-align: center; font-weight: 600;
}
QProgressBar::chunk { background: #60a5fa; border-radius: 6px; }
QGroupBox {
    color: #475569; border: 1px solid #e2e8f0; border-radius: 6px;
    margin-top: 10px; font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
QTabWidget::pane { border: 1px solid #e2e8f0; background: white; }
QTabBar::tab { background: #f1f5f9; color: #64748b; padding: 4px 10px; }
QTabBar::tab:selected { background: #dbeafe; color: #1d4ed8; }
"""


def lamp_style(is_on):
    background, foreground, border = (
        ("#dcfce7", "#166534", "#86efac") if is_on
        else ("#f1f5f9", "#64748b", "#cbd5e1")
    )
    return (
        f"background:{background}; color:{foreground}; border:1px solid {border};"
        "border-radius:6px; padding:3px; font-weight:600;"
    )
