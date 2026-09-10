"""Docked tool editor and explicit, field-wise batch updates."""
import copy

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QCheckBox, QComboBox,
    QSpinBox, QFormLayout, QGroupBox, QMessageBox,
)
from .config_dialog import WidgetConfigDialog
from .binding import reconcile_binding, validate_config
from .packets import validate_tool, bind_packet, find_packet


class ToolProperties(QWidget):
    @staticmethod
    def bound_buses(cfg):
        if cfg.get("widget_type") == "sequence":
            return {int(s["packet"]["bus"]) for s in cfg.get("binding", {}).get("sequence_steps", []) if s.get("packet")}
        return {int(cfg.get("binding", {}).get("bus", 1))} if cfg.get("behavior") in ("tx", "rx") else set()

    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.setMinimumWidth(310)
        self.layout_root = QVBoxLayout(self)
        self.layout_root.setContentsMargins(4, 0, 0, 0)
        self.heading = QLabel("Tool Properties")
        self.layout_root.addWidget(self.heading)
        self.hint = QLabel("Select a tool. Ctrl/Shift selects multiple tools.\nEdit values, then apply properties.")
        self.hint.setWordWrap(True)
        self.layout_root.addWidget(self.hint)
        self.body = None
        self.editor = None
        self.signature = None
        self.checks = {}
        self.fields = {}

    def refresh(self, force=False):
        configs = self.panel.selected_configs()
        signature = (self.panel.mode, repr(configs), repr(self.panel.db_messages), repr(self.panel.tx_packets))
        if not force and signature == self.signature:
            return
        self.signature = signature
        if self.body is not None:
            self.layout_root.removeWidget(self.body)
            self.body.hide()
            self.body.deleteLater()
        self.editor = None
        self.checks, self.fields = {}, {}
        self.body = QWidget()
        self.layout_root.addWidget(self.body, 1)
        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(0, 0, 0, 0)
        self.heading.setText(f"Tool Properties · {len(configs)} selected")
        if not configs:
            layout.addStretch()
            return
        self.body.setEnabled(self.panel.mode == "edit")
        has_can = any(self.bound_buses(c) for c in configs)
        if len(configs) == 1:
            cfg = configs[0]
            self.editor = WidgetConfigDialog(
                self.panel.db_messages, self.body, preset=cfg, embedded=True,
                live_preview_default=False, grid_rows=self.panel.grid_rows,
                grid_cols=self.panel.grid_cols,
                parent_candidates=self.panel._group_parent_candidates(exclude_id=cfg["id"]),
                tx_packets=self.panel.tx_packets,
            )
            self.editor.config_changed.connect(self.apply_single)
            layout.addWidget(self.editor, 1)
        else:
            note = QLabel("Only checked fields are applied.\nMixed values are marked (Mixed). Size is in grid cells.")
            note.setWordWrap(True)
            layout.addWidget(note)
            group = QGroupBox("Common Properties")
            form = QFormLayout(group)
            specs = [("row", "Row", 0, self.panel.grid_rows - 1),
                     ("col", "Col", 0, self.panel.grid_cols - 1),
                     ("row_span", "Height (rows)", 1, self.panel.grid_rows),
                     ("col_span", "Width (cols)", 1, self.panel.grid_cols),
                     ("bus", "RX CAN BUS", 1, 3)]
            for key, label, low, high in specs:
                field = QSpinBox()
                field.setRange(low, high)
                values = ([bus for c in configs for bus in sorted(self.bound_buses(c))] if key == "bus" else
                          [c.get(key, 1) if key in ("row", "col", "row_span", "col_span") else c.get("binding", {}).get(key, 1) for c in configs]) or [1]
                field.setValue(values[0])
                self.add_field(form, key, label, field, len(set(values)) > 1)
            if any(c.get('behavior') == 'tx' and c.get('widget_type') != 'sequence' for c in configs):
                field = QComboBox()
                for packet in self.panel.tx_packets:
                    field.addItem(f"BUS {packet['bus']} · 0x{packet['id']:X} · {packet.get('symbol', 'N/A')}", packet['packet_id'])
                values = [c.get('binding', {}).get('packet_id') for c in configs if c.get('behavior') == 'tx']
                field.setCurrentIndex(max(0, field.findData(values[0] if values else None)))
                self.add_field(form, 'packet_id', 'TX 등록 패킷', field, len(set(values)) > 1)
            self.checks['bus'].setVisible(any(c.get('behavior') == 'rx' for c in configs))
            self.fields['bus'].setVisible(any(c.get('behavior') == 'rx' for c in configs))
            layout.addWidget(group)
        channel = QGroupBox("CAN BUS Speed")
        form = QFormLayout(channel)
        hint = QLabel("Shared by all tools on the affected BUS.\nDisconnect that BUS before changing speed.\nSaved speeds are applied only when checked.")
        hint.setWordWrap(True)
        form.addRow(hint)
        for key, label, rates in [
            ("bitrate", "Nominal bitrate", [1000000, 800000, 500000, 250000, 125000, 100000, 50000, 20000, 10000]),
            ("data_bitrate", "FD data bitrate", [0, 1000000, 2000000, 4000000, 8000000]),
        ]:
            field = QComboBox()
            for rate in rates:
                field.addItem(f"{rate // 1000} kbit/s" if rate else "OFF", rate)
            values = [self.channel_rate(bus, key) for c in configs for bus in sorted(self.bound_buses(c))] or [0]
            field.setCurrentIndex(max(0, field.findData(values[0])))
            self.add_field(form, key, label, field, len(set(values)) > 1)
        layout.addWidget(channel)
        channel.setVisible(has_can)
        apply = QPushButton("Apply Checked Properties" if len(configs) > 1 else "Apply Checked BUS Speed")
        apply.clicked.connect(self.apply_checked)
        layout.addWidget(apply)
        if len(configs) == 1:
            apply.setVisible(has_can)

    def add_field(self, form, key, label, field, mixed):
        check = QCheckBox(label + (" (Mixed)" if mixed else ""))
        field.setEnabled(False)
        check.toggled.connect(field.setEnabled)
        form.addRow(check, field)
        self.checks[key], self.fields[key] = check, field

    def channel_rate(self, bus, key):
        saved = self.panel.channel_settings.get(str(bus), {})
        if key in saved:
            return saved[key]
        combos = getattr(self.panel.main_window, "combo_" + key, {})
        combo = combos.get(bus)
        if combo is not None:
            return self.rate_from_combo(combo, combo.currentIndex(), key)
        return self.panel.channel_settings.get(str(bus), {}).get(key, 500000 if key == "bitrate" else 0)

    @staticmethod
    def rate_from_combo(combo, index, key):
        data = combo.itemData(index)
        if isinstance(data, dict) and key in data:
            return int(data[key])
        text = combo.itemText(index).lower().replace(" ", "")
        try:
            return int(float(text.split("mbit")[0]) * 1000000) if "mbit" in text else int(float(text.split("kbit")[0]) * 1000)
        except ValueError:
            return 0

    def apply_single(self, config):
        if self.panel.mode != "edit":
            return
        original = self.panel._cfg_by_id(config["id"])
        if original is None:
            return
        updated = copy.deepcopy(original)
        updated.update({k: v for k, v in config.items() if k not in ("binding", "z_index")})
        updated.setdefault("binding", {}).update(config["binding"])
        self.commit([updated], {})

    def apply_checked(self):
        if self.panel.mode != "edit":
            return
        configs = copy.deepcopy(self.panel.selected_configs())
        speed = {}
        for key, check in self.checks.items():
            if not check.isChecked():
                continue
            field = self.fields[key]
            value = field.value() if isinstance(field, QSpinBox) else field.currentText()
            if key in ("bitrate", "data_bitrate"):
                speed[key] = field.currentData()
                continue
            if key in ("is_fd", "brs"):
                value = bool(field.currentIndex())
            for cfg in configs:
                if key == 'packet_id':
                    if cfg.get('behavior') == 'tx' and cfg.get('widget_type') != 'sequence':
                        packet = find_packet(self.panel.tx_packets, dict(packet_id=field.currentData()))
                        if packet:
                            bind_packet(cfg.setdefault('binding', {}), packet)
                    continue
                if key == 'bus' and cfg.get('behavior') != 'rx':
                    continue
                if key in ("row", "col", "row_span", "col_span"):
                    cfg[key] = value
                elif key == "bus" and cfg.get("widget_type") == "sequence":
                    for step in cfg.get("binding", {}).get("sequence_steps", []):
                        if step.get("packet"):
                            step["packet"]["bus"] = value
                elif cfg.get("behavior") in ("tx", "rx") and cfg.get("widget_type") != "sequence":
                    cfg.setdefault("binding", {})[key] = value
        self.commit(configs, speed)

    def commit(self, configs, speed):
        try:
            plans = []
            buses = {bus for cfg in configs for bus in self.bound_buses(cfg)}
            for cfg in configs:
                validate_tool(self.panel.tx_packets, cfg)
                validate_config(cfg)
                if cfg.get("parent_id") and self.panel._is_descendant(cfg["parent_id"], cfg["id"]):
                    raise ValueError("A group cannot be placed inside its own child.")
                self.panel._normalize_config(cfg)
                reconcile_binding(self.panel.db_messages, cfg["binding"])
            for bus in buses if speed else []:
                if getattr(self.panel.main_window, "buses", {}).get(bus) is not None:
                    raise ValueError(f"Disconnect CAN BUS {bus} before changing its speed.")
                for key, rate in speed.items():
                    combo = getattr(self.panel.main_window, "combo_" + key, {}).get(bus)
                    if combo is None:
                        raise ValueError(f"CAN BUS {bus} speed settings are unavailable.")
                    index = next((i for i in range(combo.count()) if self.rate_from_combo(combo, i, key) == rate), -1)
                    if index < 0 or (key == "data_bitrate" and rate and not combo.isEnabled()):
                        raise ValueError(f"CAN BUS {bus} does not support the selected {key}.")
                    plans.append((combo, index))
            for combo, index in plans:
                combo.setCurrentIndex(index)
            for bus in buses if speed else []:
                self.panel.channel_settings.setdefault(str(bus), {}).update(speed)
            for cfg in configs:
                self.panel._upsert_widget_config(cfg)
            self.panel.rebuild_grid()
            self.refresh(force=True)
        except ValueError as exc:
            QMessageBox.warning(self, "Properties", str(exc))
