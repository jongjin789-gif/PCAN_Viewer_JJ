"""Authenticated view of the main window's existing CAN/DBC controls."""
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QComboBox, QPushButton, QLabel, QListWidget


class ConnectionDialog(QDialog):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel, self.main = panel, panel.main_window
        self.setWindowTitle('통신 설정 / DBC')
        self.resize(1000, 470)
        self.fields, self.states, self.databases, self.buttons = {}, {}, {}, {}
        self._syncing = False
        root = QVBoxLayout(self)
        root.addWidget(QLabel('메인창과 연결 상태를 공유합니다. 변경 시 패널은 STANDARD로 전환됩니다.'))
        row = QHBoxLayout()
        root.addLayout(row)
        for bus in (1, 2, 3):
            group = QGroupBox(f'BUS {bus}')
            layout = QVBoxLayout(group)
            self.states[bus] = QLabel()
            layout.addWidget(self.states[bus])
            form = QFormLayout()
            layout.addLayout(form)
            for key, title in [('channels', '장치'), ('bitrate', 'Nominal'), ('fd_iso', 'FD ISO'), ('data_bitrate', 'Data bitrate')]:
                field = QComboBox()
                field.setMinimumContentsLength(12)
                field.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
                self.fields[bus, key] = field
                field.currentIndexChanged.connect(lambda index, b=bus, k=key: self.change(b, k, index))
                form.addRow(title, field)
            for name, title, callback in [
                ('refresh', '장치 검색', lambda b=bus: self.main.search_can_channels(b)),
                ('open', '연결', lambda b=bus: self.main.open_can(b)),
                ('close', '연결 해제', lambda b=bus: self.main.close_can(b)),
                ('db_add', 'DBC/SYM 등록', lambda b=bus: self.main.load_database_file(b)),
                ('db_remove', '선택 DBC/SYM 해제', lambda b=bus: self.remove_database(b)),
            ]:
                button = QPushButton(title)
                button.clicked.connect(lambda checked=False, cb=callback, b=bus, text=title: self.perform(cb, f'BUS {b}: {text}'))
                self.buttons[bus, name] = button
                layout.addWidget(button)
            self.databases[bus] = QListWidget()
            layout.addWidget(self.databases[bus])
            row.addWidget(group)
        close = QPushButton('닫기')
        close.clicked.connect(self.accept)
        root.addWidget(close)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(400)
        self.refresh()

    def perform(self, callback, description):
        self.panel.set_mode('standby')
        self.panel.log_system(description)
        try:
            callback()
            self.main.session.autosave()
        except Exception as exc:
            self.panel.log_system(f'{description} 실패: {exc}', 'ERROR')
        self.refresh()

    def change(self, bus, key, index):
        if self._syncing or index < 0:
            return
        source = getattr(self.main, 'combo_' + key)[bus]
        if source.isEnabled() and self.main.buses[bus] is None:
            value = self.fields[bus, key].itemText(index)
            self.perform(lambda: source.setCurrentIndex(index), f'BUS {bus}: {key} → {value}')

    def remove_database(self, bus):
        index = self.databases[bus].currentRow()
        if index >= 0:
            source = self.main.list_db_files[bus]
            source.setCurrentRow(index)
            self.main.remove_selected_db_file(bus)

    def refresh(self):
        self._syncing = True
        try:
            for bus in (1, 2, 3):
                connected = self.main.buses[bus] is not None
                mode = 'FD' if self.main.bus_capabilities[bus].get('is_fd') else 'Classic'
                self.states[bus].setText(f'연결됨 · {mode}' if connected else '미연결')
                for key in ('channels', 'bitrate', 'fd_iso', 'data_bitrate'):
                    source, field = getattr(self.main, 'combo_' + key)[bus], self.fields[bus, key]
                    items = [source.itemText(i) for i in range(source.count())]
                    if items != [field.itemText(i) for i in range(field.count())]:
                        field.clear()
                        field.addItems(items)
                    field.setCurrentIndex(source.currentIndex())
                    field.setEnabled(not connected and source.isEnabled())
                for key in ('refresh', 'open', 'close'):
                    self.buttons[bus, key].setEnabled(getattr(self.main, 'btn_' + key)[bus].isEnabled())
                source, target = self.main.list_db_files[bus], self.databases[bus]
                names = [source.item(i).text() for i in range(source.count())]
                if names != [target.item(i).text() for i in range(target.count())]:
                    selected = target.currentRow()
                    target.clear()
                    target.addItems(names)
                    target.setCurrentRow(min(selected, target.count() - 1))
        finally:
            self._syncing = False
