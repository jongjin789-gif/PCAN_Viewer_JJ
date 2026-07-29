import uuid
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class WidgetConfigDialog(QDialog):
    config_changed = pyqtSignal(dict)

    def __init__(
        self,
        db_messages,
        parent=None,
        preset=None,
        fixed_behavior=None,
        parent_candidates=None,
        live_preview_default=True,
    ):
        super().__init__(parent)
        self.setWindowTitle("User Widget Config")
        self.resize(500, 620)
        self.db_messages = db_messages
        self.fixed_behavior = fixed_behavior
        self.parent_candidates = parent_candidates or []
        self.live_preview_default = bool(live_preview_default)
        self._config_id = str(uuid.uuid4())
        self._enum_entries = []

        self._build_ui()
        self._load_db_messages()
        if preset:
            self.set_config(preset)
        self._update_help_text()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        self._row_handles = {}

        def _make_group(title):
            group = QGroupBox(title)
            form = QFormLayout(group)
            form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
            form.setContentsMargins(8, 8, 8, 8)
            return group, form

        grp_tool, form_tool = _make_group("도구 설정 (Tool)")
        grp_comm, form_comm = _make_group("통신 설정 (CAN/DBC)")
        grp_value, form_value = _make_group("값/동작 설정 (Value/Behavior)")
        grp_rx, form_rx = _make_group("RX 조건 설정 (RX Conditions)")
        grp_shape, form_shape = _make_group("도형 스타일 설정 (Shape Style)")

        self.grp_tool = grp_tool
        self.grp_comm = grp_comm
        self.grp_value = grp_value
        self.grp_rx = grp_rx
        self.grp_shape = grp_shape

        self.combo_widget_type = QComboBox()
        self.combo_widget_type.addItems(
            [
                "button",
                "toggle",
                "slider",
                "spinbox",
                "progress",
                "label",
                "status_lamp",
                "group_box",
                "tab_container",
                "shape_line",
                "shape_rect",
            ]
        )
        form_tool.addRow("Widget Type", self.combo_widget_type)

        self.edit_title = QLineEdit("Widget")
        form_tool.addRow("Title", self.edit_title)

        self.spin_row = QSpinBox()
        self.spin_row.setRange(0, 23)
        self.spin_col = QSpinBox()
        self.spin_col.setRange(0, 23)
        self.spin_row_span = QSpinBox()
        self.spin_row_span.setRange(1, 12)
        self.spin_col_span = QSpinBox()
        self.spin_col_span.setRange(1, 12)
        form_tool.addRow("Row", self.spin_row)
        form_tool.addRow("Col", self.spin_col)
        form_tool.addRow("Row Span", self.spin_row_span)
        form_tool.addRow("Col Span", self.spin_col_span)

        self.combo_parent_tool = QComboBox()
        self.combo_parent_tool.addItem("None", None)
        for candidate in self.parent_candidates:
            pid = candidate.get("id")
            ptitle = candidate.get("title", "Group")
            ptype = candidate.get("widget_type", "group_box")
            self.combo_parent_tool.addItem(f"{ptitle} [{ptype}]", pid)
        form_tool.addRow("Parent Group/Tab", self.combo_parent_tool)

        self.combo_behavior = QComboBox()
        self.combo_behavior.addItems(["none", "tx", "rx"])
        if self.fixed_behavior in ("tx", "rx"):
            self.combo_behavior.setCurrentText(self.fixed_behavior)
            self.combo_behavior.setEnabled(False)
        form_tool.addRow("Behavior", self.combo_behavior)

        self.combo_bus = QComboBox()
        self.combo_bus.addItems(["1", "2", "3"])
        self.combo_bus.currentIndexChanged.connect(self._on_bus_changed)
        form_comm.addRow("CAN Bus", self.combo_bus)

        self.combo_message = QComboBox()
        self.combo_message.setMaxVisibleItems(14)
        self.combo_message.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo_message.setMinimumContentsLength(24)
        self.combo_message.view().setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.combo_message.view().setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.combo_message.setToolTip("Use mouse wheel or Up/Down keys to scroll long message lists.")
        self.combo_message.currentIndexChanged.connect(self._on_message_changed)
        form_comm.addRow("DBC Message", self.combo_message)

        self.combo_signal = QComboBox()
        self.combo_signal.setMaxVisibleItems(14)
        self.combo_signal.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo_signal.setMinimumContentsLength(24)
        self.combo_signal.view().setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.combo_signal.view().setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.combo_signal.currentIndexChanged.connect(self._on_signal_changed)
        form_comm.addRow("DBC Signal", self.combo_signal)

        self.edit_can_id = QLineEdit("0x000")
        form_comm.addRow("CAN ID (HEX)", self.edit_can_id)

        self.spin_dlc = QSpinBox()
        self.spin_dlc.setRange(1, 64)
        self.spin_dlc.setValue(8)
        form_comm.addRow("DLC", self.spin_dlc)

        self.spin_start_bit = QSpinBox()
        self.spin_start_bit.setRange(0, 511)
        self.spin_bit_length = QSpinBox()
        self.spin_bit_length.setRange(1, 64)
        self.spin_bit_length.setValue(8)
        form_comm.addRow("Start Bit", self.spin_start_bit)
        form_comm.addRow("Bit Length", self.spin_bit_length)

        self.spin_scale = QDoubleSpinBox()
        self.spin_scale.setDecimals(6)
        self.spin_scale.setRange(-1000000.0, 1000000.0)
        self.spin_scale.setValue(1.0)
        self.spin_offset = QDoubleSpinBox()
        self.spin_offset.setDecimals(6)
        self.spin_offset.setRange(-1000000.0, 1000000.0)
        form_comm.addRow("Scale", self.spin_scale)
        form_comm.addRow("Offset", self.spin_offset)

        self.chk_signed = QCheckBox("Signed")
        self.chk_big_endian = QCheckBox("Big Endian")
        form_comm.addRow("Sign", self.chk_signed)
        form_comm.addRow("Byte Order", self.chk_big_endian)

        self.spin_min = QDoubleSpinBox()
        self.spin_min.setDecimals(6)
        self.spin_min.setRange(-1000000.0, 1000000.0)
        self.spin_max = QDoubleSpinBox()
        self.spin_max.setDecimals(6)
        self.spin_max.setRange(-1000000.0, 1000000.0)
        self.spin_max.setValue(100.0)
        form_value.addRow("Min", self.spin_min)
        form_value.addRow("Max", self.spin_max)

        self.spin_resolution = QDoubleSpinBox()
        self.spin_resolution.setDecimals(6)
        self.spin_resolution.setRange(0.000001, 1000000.0)
        self.spin_resolution.setValue(1.0)
        form_value.addRow("Resolution", self.spin_resolution)

        self.combo_tx_cycle_mode = QComboBox()
        self.combo_tx_cycle_mode.addItems(["immediate", "fixed", "dbc", "fastest"])
        self.combo_tx_cycle_mode.setCurrentText("immediate")
        form_value.addRow("TX Cycle Mode", self.combo_tx_cycle_mode)

        self.spin_tx_cycle_ms = QSpinBox()
        self.spin_tx_cycle_ms.setRange(1, 600000)
        self.spin_tx_cycle_ms.setValue(100)
        form_value.addRow("TX Cycle (ms)", self.spin_tx_cycle_ms)

        self.spin_press_value = QDoubleSpinBox()
        self.spin_press_value.setDecimals(6)
        self.spin_press_value.setRange(-1000000.0, 1000000.0)
        self.spin_press_value.setValue(100.0)
        self.combo_press_enum = QComboBox()
        self.stack_press_value = QStackedWidget()
        self.stack_press_value.addWidget(self.spin_press_value)
        self.stack_press_value.addWidget(self.combo_press_enum)
        form_value.addRow("Button Push Value", self.stack_press_value)

        self.spin_release_value = QDoubleSpinBox()
        self.spin_release_value.setDecimals(6)
        self.spin_release_value.setRange(-1000000.0, 1000000.0)
        self.spin_release_value.setValue(0.0)
        self.combo_release_enum = QComboBox()
        self.stack_release_value = QStackedWidget()
        self.stack_release_value.addWidget(self.spin_release_value)
        self.stack_release_value.addWidget(self.combo_release_enum)
        form_value.addRow("Button Pull Value", self.stack_release_value)

        self.spin_toggle_on_value = QDoubleSpinBox()
        self.spin_toggle_on_value.setDecimals(6)
        self.spin_toggle_on_value.setRange(-1000000.0, 1000000.0)
        self.spin_toggle_on_value.setValue(1.0)
        self.combo_toggle_on_enum = QComboBox()
        self.stack_toggle_on_value = QStackedWidget()
        self.stack_toggle_on_value.addWidget(self.spin_toggle_on_value)
        self.stack_toggle_on_value.addWidget(self.combo_toggle_on_enum)
        form_value.addRow("Toggle ON Value", self.stack_toggle_on_value)

        self.spin_toggle_off_value = QDoubleSpinBox()
        self.spin_toggle_off_value.setDecimals(6)
        self.spin_toggle_off_value.setRange(-1000000.0, 1000000.0)
        self.spin_toggle_off_value.setValue(0.0)
        self.combo_toggle_off_enum = QComboBox()
        self.stack_toggle_off_value = QStackedWidget()
        self.stack_toggle_off_value.addWidget(self.spin_toggle_off_value)
        self.stack_toggle_off_value.addWidget(self.combo_toggle_off_enum)
        form_value.addRow("Toggle OFF Value", self.stack_toggle_off_value)

        self.label_value_hint = QLabel()
        self.label_value_hint.setWordWrap(True)
        self.label_value_hint.setStyleSheet("color:#555;")
        form_value.addRow("Input Rule", self.label_value_hint)

        self.combo_rx_on_op = QComboBox()
        self.combo_rx_on_op.addItems(["gt", "ge", "lt", "le", "eq", "ne", "between", "outside"])
        self.combo_rx_on_op.setCurrentText("ge")
        form_rx.addRow("Lamp ON Condition", self.combo_rx_on_op)

        self.spin_rx_on_a = QDoubleSpinBox()
        self.spin_rx_on_a.setDecimals(6)
        self.spin_rx_on_a.setRange(-1000000.0, 1000000.0)
        self.spin_rx_on_a.setValue(1.0)
        self.spin_rx_on_b = QDoubleSpinBox()
        self.spin_rx_on_b.setDecimals(6)
        self.spin_rx_on_b.setRange(-1000000.0, 1000000.0)
        self.spin_rx_on_b.setValue(1.0)
        form_rx.addRow("Lamp ON A", self.spin_rx_on_a)
        form_rx.addRow("Lamp ON B", self.spin_rx_on_b)

        self.combo_rx_off_op = QComboBox()
        self.combo_rx_off_op.addItems(["gt", "ge", "lt", "le", "eq", "ne", "between", "outside"])
        self.combo_rx_off_op.setCurrentText("lt")
        form_rx.addRow("Lamp OFF Condition", self.combo_rx_off_op)

        self.spin_rx_off_a = QDoubleSpinBox()
        self.spin_rx_off_a.setDecimals(6)
        self.spin_rx_off_a.setRange(-1000000.0, 1000000.0)
        self.spin_rx_off_a.setValue(1.0)
        self.spin_rx_off_b = QDoubleSpinBox()
        self.spin_rx_off_b.setDecimals(6)
        self.spin_rx_off_b.setRange(-1000000.0, 1000000.0)
        self.spin_rx_off_b.setValue(1.0)
        form_rx.addRow("Lamp OFF A", self.spin_rx_off_a)
        form_rx.addRow("Lamp OFF B", self.spin_rx_off_b)

        self.combo_shape_kind = QComboBox()
        self.combo_shape_kind.addItems(["line", "rect"])
        form_shape.addRow("Shape Kind", self.combo_shape_kind)

        self.combo_shape_line_dir = QComboBox()
        self.combo_shape_line_dir.addItems(["horizontal", "vertical"])
        form_shape.addRow("Line Direction", self.combo_shape_line_dir)

        self.edit_stroke_color = QLineEdit("#333333")
        self.spin_stroke_width = QSpinBox()
        self.spin_stroke_width.setRange(1, 20)
        self.spin_stroke_width.setValue(2)
        self.combo_stroke_style = QComboBox()
        self.combo_stroke_style.addItems(["solid", "dash", "dot"])
        form_shape.addRow("Stroke Color", self.edit_stroke_color)
        form_shape.addRow("Stroke Width", self.spin_stroke_width)
        form_shape.addRow("Stroke Style", self.combo_stroke_style)

        self.chk_fill = QCheckBox("Fill")
        self.edit_fill_color = QLineEdit("#E8F1FF")
        self.spin_corner_radius = QSpinBox()
        self.spin_corner_radius.setRange(0, 100)
        self.spin_corner_radius.setValue(0)
        form_shape.addRow("Fill", self.chk_fill)
        form_shape.addRow("Fill Color", self.edit_fill_color)
        form_shape.addRow("Corner Radius", self.spin_corner_radius)

        self.edit_unit = QLineEdit("")
        form_comm.addRow("Unit", self.edit_unit)

        self._register_row(form_comm, self.combo_message)
        self._register_row(form_comm, self.combo_signal)
        self._register_row(form_comm, self.edit_can_id)
        self._register_row(form_comm, self.spin_dlc)
        self._register_row(form_comm, self.spin_start_bit)
        self._register_row(form_comm, self.spin_bit_length)
        self._register_row(form_comm, self.spin_scale)
        self._register_row(form_comm, self.spin_offset)
        self._register_row(form_comm, self.chk_signed)
        self._register_row(form_comm, self.chk_big_endian)
        self._register_row(form_comm, self.edit_unit)

        self._register_row(form_value, self.spin_min)
        self._register_row(form_value, self.spin_max)
        self._register_row(form_value, self.spin_resolution)
        self._register_row(form_value, self.combo_tx_cycle_mode)
        self._register_row(form_value, self.spin_tx_cycle_ms)
        self._register_row(form_value, self.stack_press_value)
        self._register_row(form_value, self.stack_release_value)
        self._register_row(form_value, self.stack_toggle_on_value)
        self._register_row(form_value, self.stack_toggle_off_value)
        self._register_row(form_value, self.label_value_hint)

        self._register_row(form_rx, self.combo_rx_on_op)
        self._register_row(form_rx, self.spin_rx_on_a)
        self._register_row(form_rx, self.spin_rx_on_b)
        self._register_row(form_rx, self.combo_rx_off_op)
        self._register_row(form_rx, self.spin_rx_off_a)
        self._register_row(form_rx, self.spin_rx_off_b)

        self._register_row(form_shape, self.combo_shape_kind)
        self._register_row(form_shape, self.combo_shape_line_dir)
        self._register_row(form_shape, self.edit_stroke_color)
        self._register_row(form_shape, self.spin_stroke_width)
        self._register_row(form_shape, self.combo_stroke_style)
        self._register_row(form_shape, self.chk_fill)
        self._register_row(form_shape, self.edit_fill_color)
        self._register_row(form_shape, self.spin_corner_radius)

        compact_widgets = [
            self.combo_widget_type,
            self.edit_title,
            self.combo_parent_tool,
            self.combo_behavior,
            self.combo_bus,
            self.combo_message,
            self.combo_signal,
            self.edit_can_id,
            self.combo_tx_cycle_mode,
            self.combo_press_enum,
            self.combo_release_enum,
            self.combo_toggle_on_enum,
            self.combo_toggle_off_enum,
            self.combo_rx_on_op,
            self.combo_rx_off_op,
            self.combo_shape_kind,
            self.combo_shape_line_dir,
            self.combo_stroke_style,
            self.edit_stroke_color,
            self.edit_fill_color,
            self.edit_unit,
        ]
        for w in compact_widgets:
            w.setMaximumWidth(260)

        form_wrap = QWidget()
        form_wrap_lay = QVBoxLayout(form_wrap)
        form_wrap_lay.setContentsMargins(0, 0, 0, 0)
        form_wrap_lay.setSpacing(6)
        form_wrap_lay.addWidget(grp_tool)
        form_wrap_lay.addWidget(grp_comm)
        form_wrap_lay.addWidget(grp_value)
        form_wrap_lay.addWidget(grp_rx)
        form_wrap_lay.addWidget(grp_shape)
        form_wrap_lay.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(form_wrap)

        root.addWidget(scroll, 1)

        self.help_text = QLabel()
        self.help_text.setWordWrap(True)
        self.help_text.setStyleSheet("color:#333; background:#F5F5F5; border:1px solid #DDD; padding:6px;")
        root.addWidget(self.help_text)

        self.chk_live_preview = QCheckBox("Live preview while editing")
        self.chk_live_preview.setChecked(self.live_preview_default)
        root.addWidget(self.chk_live_preview)

        btns = QHBoxLayout()
        btns.addStretch()
        btn_ok = QPushButton("OK")
        btn_cancel = QPushButton("Cancel")
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        root.addLayout(btns)

        watchers = [
            self.combo_widget_type,
            self.combo_behavior,
            self.combo_bus,
            self.combo_message,
            self.combo_signal,
            self.combo_rx_on_op,
            self.combo_rx_off_op,
            self.combo_shape_kind,
            self.combo_shape_line_dir,
            self.combo_stroke_style,
            self.combo_tx_cycle_mode,
            self.combo_parent_tool,
            self.combo_press_enum,
            self.combo_release_enum,
            self.combo_toggle_on_enum,
            self.combo_toggle_off_enum,
        ]
        for w in watchers:
            w.currentIndexChanged.connect(self._on_any_changed)

        value_watchers = [
            self.edit_title,
            self.edit_can_id,
            self.edit_unit,
            self.edit_stroke_color,
            self.edit_fill_color,
        ]
        for w in value_watchers:
            w.textChanged.connect(self._on_any_changed)

        num_watchers = [
            self.spin_row,
            self.spin_col,
            self.spin_row_span,
            self.spin_col_span,
            self.spin_dlc,
            self.spin_start_bit,
            self.spin_bit_length,
            self.spin_scale,
            self.spin_offset,
            self.spin_min,
            self.spin_max,
            self.spin_resolution,
            self.spin_press_value,
            self.spin_release_value,
            self.spin_toggle_on_value,
            self.spin_toggle_off_value,
            self.spin_rx_on_a,
            self.spin_rx_on_b,
            self.spin_rx_off_a,
            self.spin_rx_off_b,
            self.spin_stroke_width,
            self.spin_tx_cycle_ms,
            self.spin_corner_radius,
        ]
        for w in num_watchers:
            w.valueChanged.connect(self._on_any_changed)

        self.chk_signed.toggled.connect(self._on_any_changed)
        self.chk_big_endian.toggled.connect(self._on_any_changed)
        self.chk_fill.toggled.connect(self._on_any_changed)

        self._update_visibility()

    def _register_row(self, form, field_widget):
        self._row_handles[field_widget] = (form, field_widget)

    def _set_row_visible(self, field_widget, visible):
        pair = self._row_handles.get(field_widget)
        if not pair:
            return
        form, field = pair
        try:
            form.setRowVisible(field, bool(visible))
            return
        except Exception:
            pass

        label = form.labelForField(field)
        if label is not None:
            label.setVisible(bool(visible))
        field.setVisible(bool(visible))

    def _update_visibility(self):
        wtype = self.combo_widget_type.currentText()
        behavior = self.combo_behavior.currentText()
        has_enum = self._has_enum_choices()

        is_shape = wtype in ("shape_line", "shape_rect")
        is_group_container = wtype in ("group_box", "tab_container")
        is_tx = behavior == "tx"
        is_rx = behavior == "rx"

        self.grp_comm.setVisible(not is_shape and not is_group_container)
        self.grp_shape.setVisible(is_shape)
        self.grp_value.setVisible(not is_shape and not is_group_container)
        self.grp_rx.setVisible(is_rx and wtype == "status_lamp")

        show_signal_map = (not is_shape and not is_group_container) and (is_tx or is_rx)
        for w in (
            self.combo_message,
            self.combo_signal,
            self.edit_can_id,
            self.spin_dlc,
            self.spin_start_bit,
            self.spin_bit_length,
            self.spin_scale,
            self.spin_offset,
            self.chk_signed,
            self.chk_big_endian,
            self.edit_unit,
        ):
            self._set_row_visible(w, show_signal_map)

        show_minmax = wtype in ("slider", "spinbox", "progress", "status_lamp", "label")
        self._set_row_visible(self.spin_min, show_minmax)
        self._set_row_visible(self.spin_max, show_minmax)

        self._set_row_visible(self.spin_resolution, is_tx and wtype in ("slider", "spinbox"))
        self._set_row_visible(self.combo_tx_cycle_mode, is_tx)
        self._set_row_visible(self.spin_tx_cycle_ms, is_tx)

        self._set_row_visible(self.stack_press_value, is_tx and wtype == "button")
        self._set_row_visible(self.stack_release_value, is_tx and wtype == "button")
        self._set_row_visible(self.stack_toggle_on_value, is_tx and wtype == "toggle")
        self._set_row_visible(self.stack_toggle_off_value, is_tx and wtype == "toggle")
        self._set_row_visible(self.label_value_hint, is_tx and wtype in ("button", "toggle", "slider", "spinbox"))

        enum_index = 1 if has_enum else 0
        self.stack_press_value.setCurrentIndex(enum_index)
        self.stack_release_value.setCurrentIndex(enum_index)
        self.stack_toggle_on_value.setCurrentIndex(enum_index)
        self.stack_toggle_off_value.setCurrentIndex(enum_index)

        self._set_row_visible(self.combo_shape_line_dir, is_shape and wtype == "shape_line")
        self._set_row_visible(self.chk_fill, is_shape and wtype == "shape_rect")
        self._set_row_visible(self.edit_fill_color, is_shape and wtype == "shape_rect")
        self._set_row_visible(self.spin_corner_radius, is_shape and wtype == "shape_rect")

        if has_enum:
            self.label_value_hint.setText("Enum signal detected: choose value from enum list (raw and physical values shown).")
        else:
            scale = float(self.spin_scale.value())
            offset = float(self.spin_offset.value())
            signed = bool(self.chk_signed.isChecked())
            b = int(self.spin_bit_length.value())
            dtype = "signed" if signed else "unsigned"
            self.label_value_hint.setText(
                f"Physical input mode: type={dtype}/{b}bit, formula: physical = raw * {scale:g} + {offset:g}"
            )

    def _has_enum_choices(self):
        return len(self._enum_entries) > 0

    def _value_from_editor(self, spin_box, enum_combo):
        if enum_combo.count() > 0 and enum_combo.isVisible() and enum_combo.currentData() is not None:
            return float(enum_combo.currentData())
        return float(spin_box.value())

    def _set_enum_selection_by_value(self, combo, value):
        if combo.count() <= 0:
            return
        target = float(value)
        best_idx = 0
        best_err = None
        for i in range(combo.count()):
            v = combo.itemData(i)
            if v is None:
                continue
            err = abs(float(v) - target)
            if best_err is None or err < best_err:
                best_err = err
                best_idx = i
        combo.setCurrentIndex(best_idx)

    def _configure_value_spin(self, spin, min_v, max_v, decimals):
        spin.setDecimals(decimals)
        spin.setRange(float(min_v), float(max_v))

    def _load_enum_entries(self, sig):
        self._enum_entries = []
        choices = getattr(sig, "choices", None)
        if not isinstance(choices, dict) or not choices:
            for combo in (
                self.combo_press_enum,
                self.combo_release_enum,
                self.combo_toggle_on_enum,
                self.combo_toggle_off_enum,
            ):
                combo.clear()
            return

        scale = float(getattr(sig, "scale", 1.0) or 1.0)
        offset = float(getattr(sig, "offset", 0.0) or 0.0)

        rows = []
        for raw, enum_val in choices.items():
            try:
                raw_i = int(raw)
            except Exception:
                continue
            label = getattr(enum_val, "name", None) or str(enum_val)
            phys = (raw_i * scale) + offset
            rows.append((raw_i, float(phys), str(label)))

        rows.sort(key=lambda x: x[0])
        self._enum_entries = rows

        for combo in (
            self.combo_press_enum,
            self.combo_release_enum,
            self.combo_toggle_on_enum,
            self.combo_toggle_off_enum,
        ):
            combo.clear()
            for raw_i, phys, label in rows:
                combo.addItem(f"{label} (raw={raw_i}, phys={phys:g})", float(phys))

    def _apply_signal_constraints(self, sig):
        bit_length = int(getattr(sig, "length", 8) or 8)
        signed = bool(getattr(sig, "is_signed", False))
        scale = float(getattr(sig, "scale", 1.0) or 1.0)
        offset = float(getattr(sig, "offset", 0.0) or 0.0)

        min_v = getattr(sig, "minimum", None)
        max_v = getattr(sig, "maximum", None)
        if not isinstance(min_v, (int, float)) or not isinstance(max_v, (int, float)):
            if signed and bit_length > 0:
                raw_min = -(1 << (bit_length - 1))
                raw_max = (1 << (bit_length - 1)) - 1
            else:
                raw_min = 0
                raw_max = (1 << max(1, bit_length)) - 1
            v1 = (raw_min * scale) + offset
            v2 = (raw_max * scale) + offset
            min_v = min(v1, v2)
            max_v = max(v1, v2)

        min_v = float(min_v)
        max_v = float(max_v)
        if max_v <= min_v:
            max_v = min_v + 1.0

        scale_txt = f"{abs(scale):.8f}".rstrip("0")
        decimals = 0
        if "." in scale_txt:
            decimals = min(6, len(scale_txt.split(".", 1)[1]))

        self.spin_min.setValue(min_v)
        self.spin_max.setValue(max_v)

        for spin in (self.spin_press_value, self.spin_release_value, self.spin_toggle_on_value, self.spin_toggle_off_value):
            self._configure_value_spin(spin, min_v, max_v, decimals)

    def _on_any_changed(self, *_args):
        self._update_visibility()
        self._update_help_text()
        if not self.chk_live_preview.isChecked():
            return
        cfg = self.get_config(strict=False)
        if cfg is not None:
            self.config_changed.emit(cfg)

    def _update_help_text(self):
        wtype = self.combo_widget_type.currentText()
        behavior = self.combo_behavior.currentText()
        desc = {
            "button": "Press: push value repeat TX, Release: pull value TX",
            "toggle": "ON/OFF sends configured values",
            "slider": "Min/Max/Resolution based TX",
            "spinbox": "Direct value TX with Resolution step",
            "progress": "RX bar view",
            "label": "RX text value",
            "status_lamp": "RX condition-based ON/OFF",
            "group_box": "Visual grouping container",
            "tab_container": "Visual tab grouping container",
            "shape_line": "Simple line drawing",
            "shape_rect": "Rectangle drawing",
        }.get(wtype, "")
        mode_text = {
            "tx": "TX tool",
            "rx": "RX tool",
            "none": "No CAN binding",
        }.get(behavior, "")
        self.help_text.setText(f"{desc}\n{mode_text}\nSignal mapping: CAN ID + bit field + scale/offset")

    def _parse_can_id(self, strict=True):
        text = (self.edit_can_id.text() or "0").strip().lower().replace("h", "")
        if text.startswith("0x"):
            text = text[2:]
        if not text:
            return 0 if not strict else (_ for _ in ()).throw(ValueError("CAN ID is empty."))
        try:
            return int(text, 16)
        except Exception:
            if strict:
                raise ValueError("CAN ID must be HEX (example: 0x123).")
            return None

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
            self._enum_entries = []
            for combo in (
                self.combo_press_enum,
                self.combo_release_enum,
                self.combo_toggle_on_enum,
                self.combo_toggle_off_enum,
            ):
                combo.clear()
            self._update_visibility()
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

            self._apply_signal_constraints(sig)
            self._load_enum_entries(sig)
            self._set_enum_selection_by_value(self.combo_press_enum, self.spin_press_value.value())
            self._set_enum_selection_by_value(self.combo_release_enum, self.spin_release_value.value())
            self._set_enum_selection_by_value(self.combo_toggle_on_enum, self.spin_toggle_on_value.value())
            self._set_enum_selection_by_value(self.combo_toggle_off_enum, self.spin_toggle_off_value.value())
            self._update_visibility()
        except Exception:
            pass

    def get_config(self, strict=True):
        can_id = self._parse_can_id(strict=strict)
        if can_id is None:
            return None

        min_v = float(self.spin_min.value())
        max_v = float(self.spin_max.value())
        if max_v < min_v:
            min_v, max_v = max_v, min_v

        return {
            "id": self._config_id,
            "widget_type": self.combo_widget_type.currentText(),
            "title": self.edit_title.text().strip() or "Widget",
            "row": int(self.spin_row.value()),
            "col": int(self.spin_col.value()),
            "row_span": int(self.spin_row_span.value()),
            "col_span": int(self.spin_col_span.value()),
            "parent_id": self.combo_parent_tool.currentData(),
            "z_index": 0,
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
                "tx_resolution": float(self.spin_resolution.value()),
                "tx_cycle_mode": self.combo_tx_cycle_mode.currentText(),
                "tx_cycle_ms": int(self.spin_tx_cycle_ms.value()),
                "tx_press_value": self._value_from_editor(self.spin_press_value, self.combo_press_enum),
                "tx_release_value": self._value_from_editor(self.spin_release_value, self.combo_release_enum),
                "tx_on_value": self._value_from_editor(self.spin_toggle_on_value, self.combo_toggle_on_enum),
                "tx_off_value": self._value_from_editor(self.spin_toggle_off_value, self.combo_toggle_off_enum),
                "rx_on_op": self.combo_rx_on_op.currentText(),
                "rx_on_a": float(self.spin_rx_on_a.value()),
                "rx_on_b": float(self.spin_rx_on_b.value()),
                "rx_off_op": self.combo_rx_off_op.currentText(),
                "rx_off_a": float(self.spin_rx_off_a.value()),
                "rx_off_b": float(self.spin_rx_off_b.value()),
                "shape_kind": self.combo_shape_kind.currentText(),
                "shape_line_direction": self.combo_shape_line_dir.currentText(),
                "stroke_color": (self.edit_stroke_color.text() or "#333333").strip(),
                "stroke_width": int(self.spin_stroke_width.value()),
                "stroke_style": self.combo_stroke_style.currentText(),
                "fill": bool(self.chk_fill.isChecked()),
                "fill_color": (self.edit_fill_color.text() or "#E8F1FF").strip(),
                "corner_radius": int(self.spin_corner_radius.value()),
                "unit": self.edit_unit.text().strip(),
            },
        }

    def set_config(self, config):
        self._config_id = str(config.get("id") or self._config_id)
        self.combo_widget_type.setCurrentText(config.get("widget_type", "label"))
        self.edit_title.setText(config.get("title", "Widget"))
        self.spin_row.setValue(int(config.get("row", 0)))
        self.spin_col.setValue(int(config.get("col", 0)))
        self.spin_row_span.setValue(max(1, int(config.get("row_span", 1))))
        self.spin_col_span.setValue(max(1, int(config.get("col_span", 1))))
        idx_parent = self.combo_parent_tool.findData(config.get("parent_id"))
        if idx_parent >= 0:
            self.combo_parent_tool.setCurrentIndex(idx_parent)
        else:
            self.combo_parent_tool.setCurrentIndex(0)
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

        self.spin_resolution.setValue(float(binding.get("tx_resolution", 1.0)))
        self.combo_tx_cycle_mode.setCurrentText(str(binding.get("tx_cycle_mode", "immediate")))
        self.spin_tx_cycle_ms.setValue(int(binding.get("tx_cycle_ms", 100)))
        self.spin_press_value.setValue(float(binding.get("tx_press_value", binding.get("max", 100.0))))
        self.spin_release_value.setValue(float(binding.get("tx_release_value", binding.get("min", 0.0))))
        self.spin_toggle_on_value.setValue(float(binding.get("tx_on_value", 1.0)))
        self.spin_toggle_off_value.setValue(float(binding.get("tx_off_value", 0.0)))

        self.combo_rx_on_op.setCurrentText(str(binding.get("rx_on_op", "ge")))
        self.spin_rx_on_a.setValue(float(binding.get("rx_on_a", 1.0)))
        self.spin_rx_on_b.setValue(float(binding.get("rx_on_b", 1.0)))
        self.combo_rx_off_op.setCurrentText(str(binding.get("rx_off_op", "lt")))
        self.spin_rx_off_a.setValue(float(binding.get("rx_off_a", 1.0)))
        self.spin_rx_off_b.setValue(float(binding.get("rx_off_b", 1.0)))

        self.combo_shape_kind.setCurrentText(str(binding.get("shape_kind", "line")))
        self.combo_shape_line_dir.setCurrentText(str(binding.get("shape_line_direction", "horizontal")))
        self.edit_stroke_color.setText(str(binding.get("stroke_color", "#333333")))
        self.spin_stroke_width.setValue(int(binding.get("stroke_width", 2)))
        self.combo_stroke_style.setCurrentText(str(binding.get("stroke_style", "solid")))
        self.chk_fill.setChecked(bool(binding.get("fill", False)))
        self.edit_fill_color.setText(str(binding.get("fill_color", "#E8F1FF")))
        self.spin_corner_radius.setValue(int(binding.get("corner_radius", 0)))
        self.edit_unit.setText(binding.get("unit", ""))

        sig_name = binding.get("signal_name")
        idx_sig = self.combo_signal.findData(sig_name)
        if idx_sig >= 0:
            self.combo_signal.setCurrentIndex(idx_sig)

        self._set_enum_selection_by_value(self.combo_press_enum, self.spin_press_value.value())
        self._set_enum_selection_by_value(self.combo_release_enum, self.spin_release_value.value())
        self._set_enum_selection_by_value(self.combo_toggle_on_enum, self.spin_toggle_on_value.value())
        self._set_enum_selection_by_value(self.combo_toggle_off_enum, self.spin_toggle_off_value.value())

        self._update_visibility()

    def accept(self):
        try:
            cfg = self.get_config(strict=True)
            self.config_changed.emit(cfg)
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Input", str(e))
            return
        super().accept()
