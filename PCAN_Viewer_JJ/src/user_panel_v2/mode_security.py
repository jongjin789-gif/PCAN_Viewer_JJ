from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QHBoxLayout, QPushButton


class EditPasswordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Enter Edit Password")
        self.resize(320, 120)

        root = QVBoxLayout(self)
        root.addWidget(QLabel("Password is required to enter EDIT mode."))

        self.edit_password = QLineEdit()
        self.edit_password.setEchoMode(QLineEdit.Password)
        root.addWidget(self.edit_password)

        btns = QHBoxLayout()
        btns.addStretch()
        btn_ok = QPushButton("OK")
        btn_cancel = QPushButton("Cancel")
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        root.addLayout(btns)

    def value(self):
        return (self.edit_password.text() or "").strip()


def verify_edit_password(parent, enabled, expected_password):
    if not enabled:
        return True

    dlg = EditPasswordDialog(parent)
    if dlg.exec_() != QDialog.Accepted:
        return False
    return dlg.value() == (expected_password or "")
