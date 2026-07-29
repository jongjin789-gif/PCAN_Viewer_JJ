import json
import time
import uuid
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QMessageBox,
    QFileDialog,
    QDialog,
    QFormLayout,
    QComboBox,
    QLineEdit,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QGridLayout,
    QFrame,
    QSlider,
    QProgressBar,
    QStackedLayout,
)


class WidgetConfigDialog(QDialog):
    def __init__(self, db_messages, parent=None, preset=None):
        super().__init__(parent)
        self.setWindowTitle("User Widget Config")
        self.resize(520, 520)
        self.db_messages = db_messages

        self._build_ui()
        self._load_db_messages()
        if preset:
            self.set_config(preset)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.combo_widget_type = QComboBox()
        self.combo_widget_type.addItems([
            "button",
            "toggle",
            "slider",
            "spinbox",
            "progress",
            "label",
            "status_lamp",
        ])
        form.addRow("Widget Type", self.combo_widget_type)

        self.edit_title = QLineEdit("Widget")
        form.addRow("Title", self.edit_title)

        self.spin_row = QSpinBox()
        self.spin_row.setRange(0, 11)
        self.spin_col = QSpinBox()
        self.spin_col.setRange(0, 11)
        self.spin_row_span = QSpinBox()
        self.spin_row_span.setRange(1, 6)
        self.spin_col_span = QSpinBox()
        self.spin_col_span.setRange(1, 6)
        self.spin_row_span.setValue(1)
        self.spin_col_span.setValue(1)

        form.addRow("Row", self.spin_row)
        form.addRow("Column", self.spin_col)
        form.addRow("Row Span", self.spin_row_span)
        form.addRow("Col Span", self.spin_col_span)

        self.combo_behavior = QComboBox()
        self.combo_behavior.addItems(["none", "tx", "rx"])
        form.addRow("Behavior", self.combo_behavior)

        self.combo_bus = QComboBox()
        self.combo_bus.addItems(["1", "2", "3"])
        self.combo_bus.currentIndexChanged.connect(self._on_bus_changed)
        form.addRow("CAN Bus", self.combo_bus)

        self.combo_message = QComboBox()
        self.combo_message.currentIndexChanged.connect(self._on_message_changed)
        form.addRow("DBC Message", self.combo_message)

        self.combo_signal = QComboBox()
        self.combo_signal.currentIndexChanged.connect(self._on_signal_changed)
        form.addRow("DBC Signal", self.combo_signal)

        self.edit_can_id = QLineEdit("0x000")
        form.addRow("CAN ID (HEX)", self.edit_can_id)

        self.spin_dlc = QSpinBox()
        self.spin_dlc.setRange(1, 64)
        self.spin_dlc.setValue(8)
        form.addRow("DLC", self.spin_dlc)

        self.spin_start_bit = QSpinBox()
        self.spin_start_bit.setRange(0, 511)
        self.spin_bit_length = QSpinBox()
        self.spin_bit_length.setRange(1, 64)
        self.spin_bit_length.setValue(8)
        form.addRow("Start Bit", self.spin_start_bit)
        form.addRow("Bit Length", self.spin_bit_length)

        self.spin_scale = QDoubleSpinBox()
        self.spin_scale.setDecimals(6)
        self.spin_scale.setRange(-1000000.0, 1000000.0)
        self.spin_scale.setValue(1.0)
        self.spin_offset = QDoubleSpinBox()
        self.spin_offset.setDecimals(6)
        self.spin_offset.setRange(-1000000.0, 1000000.0)
        form.addRow("Scale", self.spin_scale)
        form.addRow("Offset", self.spin_offset)

        self.chk_signed = QCheckBox("Signed")
        self.chk_big_endian = QCheckBox("Big Endian")
        form.addRow("Sign", self.chk_signed)
        form.addRow("Byte Order", self.chk_big_endian)

        self.spin_min = QDoubleSpinBox()
        self.spin_min.setDecimals(3)
        self.spin_min.setRange(-1000000.0, 1000000.0)
        self.spin_min.setValue(0.0)
        self.spin_max = QDoubleSpinBox()
        self.spin_max.setDecimals(3)
        self.spin_max.setRange(-1000000.0, 1000000.0)
        self.spin_max.setValue(100.0)
        form.addRow("Min", self.spin_min)
        form.addRow("Max", self.spin_max)

        self.edit_unit = QLineEdit("")
        form.addRow("Unit", self.edit_unit)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_ok = QPushButton("OK")
        btn_cancel = QPushButton("Cancel")
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

    def _load_db_messages(self):
        self.combo_message.blockSignals(True)
        self.combo_message.clear()

        bus = int(self.combo_bus.currentText())
        self.combo_message.addItem("Manual Input", None)
        for can_id, msg in sorted(self.db_messages.get(bus, {}).items()):
            self.combo_message.addItem(f"{msg.name} (0x{can_id:X})", can_id)

        self.combo_message.blockSignals(False)
        self._on_message_changed()

    def _on_bus_changed(self):
        self._load_db_messages()

    def _on_message_changed(self):
        self.combo_signal.blockSignals(True)
        self.combo_signal.clear()
        self.combo_signal.addItem("Manual", None)

        bus = int(self.combo_bus.currentText())
        can_id = self.combo_message.currentData()
        if can_id is not None and can_id in self.db_messages.get(bus, {}):
            msg = self.db_messages[bus][can_id]
            self.edit_can_id.setText(f"0x{can_id:X}")
            self.spin_dlc.setValue(int(getattr(msg, "length", 8) or 8))
            for sig in msg.signals:
                self.combo_signal.addItem(sig.name, sig.name)

        self.combo_signal.blockSignals(False)
        self._on_signal_changed()

    def _on_signal_changed(self):
        bus = int(self.combo_bus.currentText())
        can_id = self.combo_message.currentData()
        sig_name = self.combo_signal.currentData()
        if can_id is None or sig_name is None:
            return

        msg = self.db_messages.get(bus, {}).get(can_id)
        if not msg:
            return

        try:
            sig = msg.get_signal_by_name(sig_name)
            self.spin_start_bit.setValue(int(getattr(sig, "start", getattr(sig, "start_bit", 0))))
            self.spin_bit_length.setValue(int(getattr(sig, "length", 8)))
            self.spin_scale.setValue(float(getattr(sig, "scale", 1.0) or 1.0))
            self.spin_offset.setValue(float(getattr(sig, "offset", 0.0) or 0.0))
            self.chk_signed.setChecked(bool(getattr(sig, "is_signed", False)))
            byte_order = str(getattr(sig, "byte_order", "little_endian"))
            self.chk_big_endian.setChecked(byte_order == "big_endian")
            if getattr(sig, "unit", None):
                self.edit_unit.setText(sig.unit)

            min_v = getattr(sig, "minimum", None)
            max_v = getattr(sig, "maximum", None)
            if isinstance(min_v, (int, float)):
                self.spin_min.setValue(float(min_v))
            if isinstance(max_v, (int, float)):
                self.spin_max.setValue(float(max_v))
        except Exception:
            pass

    def get_config(self):
        can_id_text = (self.edit_can_id.text() or "0").strip().lower().replace("h", "")
        if can_id_text.startswith("0x"):
            can_id = int(can_id_text, 16)
        else:
            can_id = int(can_id_text, 16)

        min_v = float(self.spin_min.value())
        max_v = float(self.spin_max.value())
        if max_v < min_v:
            min_v, max_v = max_v, min_v

        return {
            "id": str(uuid.uuid4()),
            "widget_type": self.combo_widget_type.currentText(),
            "title": self.edit_title.text().strip() or "Widget",
            "row": int(self.spin_row.value()),
            "col": int(self.spin_col.value()),
            "row_span": int(self.spin_row_span.value()),
            "col_span": int(self.spin_col_span.value()),
            "behavior": self.combo_behavior.currentText(),
            "binding": {
                "bus": int(self.combo_bus.currentText()),
                "can_id": int(can_id),
                "signal_name": self.combo_signal.currentData(),
                "dlc": int(self.spin_dlc.value()),
                "start_bit": int(self.spin_start_bit.value()),
                "bit_length": int(self.spin_bit_length.value()),
                "scale": float(self.spin_scale.value()),
                "offset": float(self.spin_offset.value()),
                "signed": bool(self.chk_signed.isChecked()),
                "byte_order": "big_endian" if self.chk_big_endian.isChecked() else "little_endian",
                "min": min_v,
                "max": max_v,
                "unit": self.edit_unit.text().strip(),
            },
        }

    def set_config(self, config):
        self.combo_widget_type.setCurrentText(config.get("widget_type", "label"))
        self.edit_title.setText(config.get("title", "Widget"))
        self.spin_row.setValue(int(config.get("row", 0)))
        self.spin_col.setValue(int(config.get("col", 0)))
        self.spin_row_span.setValue(max(1, int(config.get("row_span", 1))))
        self.spin_col_span.setValue(max(1, int(config.get("col_span", 1))))
        self.combo_behavior.setCurrentText(config.get("behavior", "none"))

        binding = config.get("binding", {})
        self.combo_bus.setCurrentText(str(binding.get("bus", 1)))
        self._load_db_messages()

        can_id = int(binding.get("can_id", 0))
        idx = self.combo_message.findData(can_id)
        if idx >= 0:
            self.combo_message.setCurrentIndex(idx)
        self.edit_can_id.setText(f"0x{can_id:X}")

        self.spin_dlc.setValue(int(binding.get("dlc", 8)))
        self.spin_start_bit.setValue(int(binding.get("start_bit", 0)))
        self.spin_bit_length.setValue(int(binding.get("bit_length", 8)))
        self.spin_scale.setValue(float(binding.get("scale", 1.0)))
        self.spin_offset.setValue(float(binding.get("offset", 0.0)))
        self.chk_signed.setChecked(bool(binding.get("signed", False)))
        self.chk_big_endian.setChecked(binding.get("byte_order", "little_endian") == "big_endian")
        self.spin_min.setValue(float(binding.get("min", 0.0)))
        self.spin_max.setValue(float(binding.get("max", 100.0)))
        self.edit_unit.setText(binding.get("unit", ""))

        sig_name = binding.get("signal_name")
        idx_sig = self.combo_signal.findData(sig_name)
        if idx_sig >= 0:
            self.combo_signal.setCurrentIndex(idx_sig)


class UserPanelWindow(QWidget):
    request_tx_value = pyqtSignal(dict, float)

    def __init__(self, main_window, db_messages, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.db_messages = db_messages
        self.setWindowTitle("User Panel")
        self.resize(980, 640)

        self.grid_rows = 8
        self.grid_cols = 8
        self.mode = "edit"
        self.widgets_config = []
        self.widget_frames = {}
        self.widget_controls = {}
        self.selected_widget_id = None
        self.latest_raw_by_msg = {}
        self.latest_value_by_signal = {}

        self.request_tx_value.connect(self._tx_value_throttled)
        self._last_tx_sent = {}

        self._build_ui()
        self.refresh_mode_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self.btn_mode = QPushButton("Mode: EDIT")
        self.btn_mode.clicked.connect(self.toggle_mode)
        self.btn_add = QPushButton("Add Widget")
        self.btn_edit = QPushButton("Edit")
        self.btn_delete = QPushButton("Delete")
        self.btn_save = QPushButton("Save Panel")
        self.btn_load = QPushButton("Load Panel")

        self.btn_add.clicked.connect(self.add_widget)
        self.btn_edit.clicked.connect(self.edit_selected_widget)
        self.btn_delete.clicked.connect(self.delete_selected_widget)
        self.btn_save.clicked.connect(self.save_panel_to_file)
        self.btn_load.clicked.connect(self.load_panel_from_file)

        top.addWidget(self.btn_mode)
        top.addWidget(self.btn_add)
        top.addWidget(self.btn_edit)
        top.addWidget(self.btn_delete)
        top.addStretch()
        top.addWidget(self.btn_save)
        top.addWidget(self.btn_load)
        root.addLayout(top)

        self.label_mode = QLabel()
        root.addWidget(self.label_mode)

        self.canvas = QWidget()
        self.canvas_layout = QGridLayout(self.canvas)
        self.canvas_layout.setContentsMargins(6, 6, 6, 6)
        self.canvas_layout.setHorizontalSpacing(6)
        self.canvas_layout.setVerticalSpacing(6)
        for r in range(self.grid_rows):
            self.canvas_layout.setRowStretch(r, 1)
        for c in range(self.grid_cols):
            self.canvas_layout.setColumnStretch(c, 1)

        root.addWidget(self.canvas, 1)

    def toggle_mode(self):
        self.mode = "run" if self.mode == "edit" else "edit"
        self.refresh_mode_ui()

    def refresh_mode_ui(self):
        is_edit = self.mode == "edit"
        self.btn_mode.setText(f"Mode: {self.mode.upper()}")
        self.label_mode.setText(
            "Edit mode: layout/property editing only, CAN TX blocked"
            if is_edit else
            "Run mode: bound widgets can TX/RX"
        )
        self.btn_add.setEnabled(is_edit)
        self.btn_edit.setEnabled(is_edit)
        self.btn_delete.setEnabled(is_edit)

    def add_widget(self):
        dlg = WidgetConfigDialog(self.db_messages, self)
        if dlg.exec_() != QDialog.Accepted:
            return

        config = dlg.get_config()
        self.widgets_config.append(config)
        self.rebuild_grid()

    def edit_selected_widget(self):
        cfg = self._get_selected_config()
        if not cfg:
            QMessageBox.information(self, "Info", "Select a widget first.")
            return

        dlg = WidgetConfigDialog(self.db_messages, self, preset=cfg)
        if dlg.exec_() != QDialog.Accepted:
            return

        new_cfg = dlg.get_config()
        new_cfg["id"] = cfg["id"]
        for i, old in enumerate(self.widgets_config):
            if old.get("id") == cfg.get("id"):
                self.widgets_config[i] = new_cfg
                break

        self.rebuild_grid()

    def delete_selected_widget(self):
        cfg = self._get_selected_config()
        if not cfg:
            QMessageBox.information(self, "Info", "Select a widget first.")
            return

        self.widgets_config = [x for x in self.widgets_config if x.get("id") != cfg.get("id")]
        self.selected_widget_id = None
        self.rebuild_grid()

    def _get_selected_config(self):
        if not self.selected_widget_id:
            return None
        for cfg in self.widgets_config:
            if cfg.get("id") == self.selected_widget_id:
                return cfg
        return None

    def rebuild_grid(self):
        while self.canvas_layout.count():
            item = self.canvas_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

        self.widget_frames.clear()
        self.widget_controls.clear()

        for cfg in self.widgets_config:
            frame = QFrame()
            frame.setFrameShape(QFrame.StyledPanel)
            frame.setObjectName(cfg.get("id"))

            frame_layout = QVBoxLayout(frame)
            frame_layout.setContentsMargins(6, 6, 6, 6)
            frame_layout.setSpacing(4)
            title = QLabel(cfg.get("title", "Widget"))
            title.setAlignment(Qt.AlignCenter)
            frame_layout.addWidget(title)

            ctrl = self._create_runtime_widget(cfg)
            frame_layout.addWidget(ctrl, 1)

            widget_id = cfg.get("id")
            self.widget_frames[widget_id] = frame
            self.widget_controls[widget_id] = ctrl

            self._bind_select(frame, widget_id)
            self._bind_select(title, widget_id)

            row = int(cfg.get("row", 0))
            col = int(cfg.get("col", 0))
            row_span = max(1, int(cfg.get("row_span", 1)))
            col_span = max(1, int(cfg.get("col_span", 1)))
            self.canvas_layout.addWidget(frame, row, col, row_span, col_span)

        self._refresh_selection_ui()

    def _bind_select(self, widget, widget_id):
        def _on_press(_event):
            self.selected_widget_id = widget_id
            self._refresh_selection_ui()
        widget.mousePressEvent = _on_press

    def _refresh_selection_ui(self):
        for widget_id, frame in self.widget_frames.items():
            selected = widget_id == self.selected_widget_id
            if selected:
                frame.setStyleSheet("QFrame { border: 2px solid #0078D7; background: #F4F9FF; }")
            else:
                frame.setStyleSheet("QFrame { border: 1px solid #C8C8C8; background: #FFFFFF; }")

    def _create_runtime_widget(self, cfg):
        wtype = cfg.get("widget_type", "label")
        behavior = cfg.get("behavior", "none")
        binding = cfg.get("binding", {})

        min_v = float(binding.get("min", 0.0))
        max_v = float(binding.get("max", 100.0))
        if max_v <= min_v:
            max_v = min_v + 1.0

        if wtype == "button":
            btn = QPushButton("Send")
            btn.clicked.connect(lambda: self._emit_tx(cfg, max_v))
            return btn

        if wtype == "toggle":
            btn = QPushButton("OFF")
            btn.setCheckable(True)
            def _toggle(checked):
                btn.setText("ON" if checked else "OFF")
                self._emit_tx(cfg, max_v if checked else min_v)
            btn.toggled.connect(_toggle)
            return btn

        if wtype == "slider":
            container = QWidget()
            lay = QVBoxLayout(container)
            lay.setContentsMargins(0, 0, 0, 0)
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 1000)
            value_label = QLabel(f"{min_v:.3f}")
            value_label.setAlignment(Qt.AlignCenter)
            lay.addWidget(slider)
            lay.addWidget(value_label)

            def _on_changed(v):
                phys = min_v + ((max_v - min_v) * (v / 1000.0))
                value_label.setText(f"{phys:.3f}")
                if behavior == "tx":
                    self._emit_tx(cfg, phys)

            slider.valueChanged.connect(_on_changed)
            return container

        if wtype == "spinbox":
            spin = QDoubleSpinBox()
            spin.setRange(min_v, max_v)
            spin.setDecimals(3)
            spin.setSingleStep(max((max_v - min_v) / 100.0, 0.001))
            if behavior == "tx":
                spin.valueChanged.connect(lambda v: self._emit_tx(cfg, float(v)))
            return spin

        if wtype == "progress":
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(0)
            return bar

        if wtype == "status_lamp":
            lamp = QLabel("OFF")
            lamp.setAlignment(Qt.AlignCenter)
            lamp.setStyleSheet("background:#9E9E9E; color:white; border-radius:4px; padding:4px;")
            return lamp

        return QLabel("-")

    def _tx_value_throttled(self, binding, value):
        key = (
            int(binding.get("bus", 1)),
            int(binding.get("can_id", 0)),
            str(binding.get("signal_name")),
            int(binding.get("start_bit", 0)),
            int(binding.get("bit_length", 1)),
        )
        now = time.time()
        last = self._last_tx_sent.get(key, 0.0)
        if now - last < 0.02:
            return
        self._last_tx_sent[key] = now
        try:
            self.main_window.send_user_panel_value(binding, float(value))
        except Exception as e:
            if hasattr(self.main_window, "statusBar"):
                self.main_window.statusBar().showMessage(f"User panel TX failed: {e}", 4000)

    def _emit_tx(self, cfg, value):
        if self.mode != "run":
            return
        binding = cfg.get("binding", {})
        self.request_tx_value.emit(binding, float(value))

    def on_message_update(self, bus, can_id, data_bytes, ts):
        self.latest_raw_by_msg[(bus, can_id)] = bytes(data_bytes)

        for cfg in self.widgets_config:
            if cfg.get("behavior") != "rx":
                continue
            binding = cfg.get("binding", {})
            if int(binding.get("bus", -1)) != int(bus):
                continue
            if int(binding.get("can_id", -1)) != int(can_id):
                continue

            raw = self._extract_raw_value(bytes(data_bytes), binding)
            if raw is None:
                continue
            phys = raw * float(binding.get("scale", 1.0)) + float(binding.get("offset", 0.0))
            self._update_widget_value(cfg, phys)

    def on_signal_update(self, bus, sig_name, value, unit, ts):
        self.latest_value_by_signal[(bus, sig_name)] = value

        for cfg in self.widgets_config:
            if cfg.get("behavior") != "rx":
                continue
            binding = cfg.get("binding", {})
            if int(binding.get("bus", -1)) != int(bus):
                continue
            if binding.get("signal_name") != sig_name:
                continue
            self._update_widget_value(cfg, value)

    def _update_widget_value(self, cfg, value):
        wid = cfg.get("id")
        ctrl = self.widget_controls.get(wid)
        if not ctrl:
            return

        wtype = cfg.get("widget_type")
        binding = cfg.get("binding", {})
        min_v = float(binding.get("min", 0.0))
        max_v = float(binding.get("max", 100.0))
        if max_v <= min_v:
            max_v = min_v + 1.0

        try:
            v = float(value)
        except Exception:
            return

        if wtype == "progress":
            ratio = 0.0 if max_v == min_v else (v - min_v) / (max_v - min_v)
            ratio = min(1.0, max(0.0, ratio))
            ctrl.setValue(int(ratio * 1000.0))
            return

        if wtype == "slider":
            if isinstance(ctrl, QWidget):
                slider = ctrl.findChild(QSlider)
                if slider is not None:
                    ratio = 0.0 if max_v == min_v else (v - min_v) / (max_v - min_v)
                    ratio = min(1.0, max(0.0, ratio))
                    slider.blockSignals(True)
                    slider.setValue(int(ratio * 1000.0))
                    slider.blockSignals(False)
            return

        if wtype == "spinbox":
            if isinstance(ctrl, QDoubleSpinBox):
                ctrl.blockSignals(True)
                ctrl.setValue(v)
                ctrl.blockSignals(False)
            return

        if wtype == "toggle":
            if isinstance(ctrl, QPushButton) and ctrl.isCheckable():
                is_on = v > ((min_v + max_v) / 2.0)
                ctrl.blockSignals(True)
                ctrl.setChecked(is_on)
                ctrl.setText("ON" if is_on else "OFF")
                ctrl.blockSignals(False)
            return

        if wtype == "status_lamp":
            is_on = v > ((min_v + max_v) / 2.0)
            ctrl.setText("ON" if is_on else "OFF")
            if is_on:
                ctrl.setStyleSheet("background:#2E7D32; color:white; border-radius:4px; padding:4px;")
            else:
                ctrl.setStyleSheet("background:#9E9E9E; color:white; border-radius:4px; padding:4px;")
            return

        if wtype == "label":
            ctrl.setText(f"{v:.3f}")
            return

    def _extract_raw_value(self, payload, binding):
        try:
            bit_length = int(binding.get("bit_length", 1))
            start_bit = int(binding.get("start_bit", 0))
            signed = bool(binding.get("signed", False))
            byte_order = binding.get("byte_order", "little_endian")
            if byte_order == "big_endian":
                return None

            total_bits = len(payload) * 8
            if start_bit + bit_length > total_bits:
                return None

            raw_u64 = int.from_bytes(payload, byteorder="little", signed=False)
            mask = (1 << bit_length) - 1
            raw = (raw_u64 >> start_bit) & mask

            if signed and bit_length > 0:
                sign_bit = 1 << (bit_length - 1)
                if raw & sign_bit:
                    raw -= (1 << bit_length)
            return raw
        except Exception:
            return None

    def save_panel_to_file(self):
        data = {
            "version": 1,
            "grid": {"rows": self.grid_rows, "cols": self.grid_cols},
            "widgets": self.widgets_config,
        }
        path, _ = QFileDialog.getSaveFileName(self, "Save User Panel", "", "User Panel (*.upp.json)")
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            QMessageBox.information(self, "Saved", "User panel saved successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Save failed:\n{e}")

    def load_panel_from_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load User Panel", "", "User Panel (*.upp.json)")
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                raise ValueError("Invalid panel file.")

            self.grid_rows = int(data.get("grid", {}).get("rows", 8))
            self.grid_cols = int(data.get("grid", {}).get("cols", 8))
            self.widgets_config = list(data.get("widgets", []))

            for cfg in self.widgets_config:
                if "id" not in cfg:
                    cfg["id"] = str(uuid.uuid4())
                binding = cfg.setdefault("binding", {})
                binding.setdefault("byte_order", "little_endian")
                binding.setdefault("dlc", 8)
                binding.setdefault("scale", 1.0)
                binding.setdefault("offset", 0.0)
                binding.setdefault("min", 0.0)
                binding.setdefault("max", 100.0)

            self.rebuild_grid()

            missing_signal = [
                c for c in self.widgets_config
                if c.get("binding", {}).get("signal_name")
                and c.get("binding", {}).get("signal_name") not in {
                    s.name
                    for bus in self.db_messages.values()
                    for m in bus.values()
                    for s in m.signals
                }
            ]
            if missing_signal:
                QMessageBox.warning(
                    self,
                    "Loaded with Warning",
                    "Panel loaded. Some DBC signals are not currently available. "
                    "RX/TX falls back to saved bit-field mapping where possible."
                )
            else:
                QMessageBox.information(self, "Loaded", "User panel loaded successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Load failed:\n{e}")
