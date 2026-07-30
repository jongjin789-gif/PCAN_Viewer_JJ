import copy
import json
import math
import time
import uuid
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QKeySequence, QPainter, QPen
from PyQt5.QtWidgets import (
    QAction,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QMenuBar,
    QPushButton,
    QDoubleSpinBox,
    QProgressBar,
    QShortcut,
    QSpinBox,
    QSlider,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .config_dialog import WidgetConfigDialog
from .mode_security import verify_edit_password
from .storage import PACKAGE_EXT, load_bundle, load_panel_json, save_bundle, save_panel_json


class GridCanvas(QWidget):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner

    def paintEvent(self, event):
        super().paintEvent(event)
        rows = max(1, int(getattr(self.owner, "grid_rows", 12)))
        cols = max(1, int(getattr(self.owner, "grid_cols", 12)))
        w = max(1, self.width())
        h = max(1, self.height())
        cell_w = w / float(cols)
        cell_h = h / float(rows)

        p = QPainter(self)
        c0 = QColor("#FAFBFC")
        c1 = QColor("#F0F4F8")

        for r in range(rows):
            for c in range(cols):
                x = int(round(c * cell_w))
                y = int(round(r * cell_h))
                x2 = int(round((c + 1) * cell_w))
                y2 = int(round((r + 1) * cell_h))
                p.fillRect(x, y, max(1, x2 - x), max(1, y2 - y), c0 if ((r + c) % 2 == 0) else c1)

        p.setPen(QPen(QColor("#D6DCE3"), 1))
        for r in range(rows + 1):
            y = int(round(r * cell_h))
            p.drawLine(0, y, w, y)
        for c in range(cols + 1):
            x = int(round(c * cell_w))
            p.drawLine(x, 0, x, h)

        p.end()


class UserPanelWindow(QWidget):
    request_tx_value = pyqtSignal(dict, float)

    def __init__(self, main_window, db_messages, parent=None, security_config=None):
        super().__init__(parent)
        self.main_window = main_window
        self.db_messages = db_messages
        self.security_config = security_config or {}

        self.setWindowTitle("User Panel")
        self.resize(1180, 760)

        self.grid_rows = 12
        self.grid_cols = 12
        self.mode = "edit"

        self.widgets_config = []
        self.widget_frames = {}
        self.widget_controls = {}
        self.widget_child_hosts = {}
        self.selected_widget_id = None
        self.latest_raw_by_msg = {}
        self.latest_value_by_signal = {}
        self._tool_list_syncing = False
        self._frame_timers = {}
        self.draw_mode = None
        self.draw_start_cell = None
        self._shape_counter = 1
        self._drag_target_id = None
        self._drag_start_global = None
        self._drag_origin_cell = None
        self._drag_origin_span = None
        self._drag_resize_mode = False
        self._prop_syncing = False
        self._overlap_map = {}
        self._conflict_cursor = {}
        self._sim_phase = 0.0
        self._sim_timer = QTimer(self)
        self._sim_timer.setInterval(200)
        self._sim_timer.timeout.connect(self._on_sim_timer)

        self.request_tx_value.connect(self._tx_value_throttled)
        self._last_tx_sent = {}

        self._build_ui()
        self.refresh_mode_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        self.setFocusPolicy(Qt.StrongFocus)

        self.menu_bar = QMenuBar(self)
        root.addWidget(self.menu_bar)

        self.btn_mode_edit = QPushButton("Mode: EDIT")
        self.btn_mode_standby = QPushButton("Mode: STANDBY")
        self.btn_mode_run = QPushButton("Mode: RUN")
        self.btn_mode_edit.clicked.connect(lambda: self.set_mode("edit"))
        self.btn_mode_standby.clicked.connect(lambda: self.set_mode("standby"))
        self.btn_mode_run.clicked.connect(lambda: self.set_mode("run"))

        self.btn_add_tx = QPushButton("Add TX Tool")
        self.btn_add_rx = QPushButton("Add RX Tool")
        self.btn_add_misc = QPushButton("Add Group/Shape")
        self.btn_edit = QPushButton("Edit")
        self.btn_delete = QPushButton("Delete")

        self.btn_add_tx.clicked.connect(lambda: self.add_widget("tx"))
        self.btn_add_rx.clicked.connect(lambda: self.add_widget("rx"))
        self.btn_add_misc.clicked.connect(lambda: self.add_widget("none"))
        self.btn_edit.clicked.connect(self.edit_selected_widget)
        self.btn_delete.clicked.connect(self.delete_selected_widget)

        controls = QHBoxLayout()
        controls.addWidget(self.btn_mode_edit)
        controls.addWidget(self.btn_mode_standby)
        controls.addWidget(self.btn_mode_run)
        controls.addSpacing(12)
        controls.addWidget(self.btn_add_tx)
        controls.addWidget(self.btn_add_rx)
        controls.addWidget(self.btn_add_misc)
        controls.addWidget(self.btn_edit)
        controls.addWidget(self.btn_delete)
        controls.addStretch()
        root.addLayout(controls)

        self._setup_menu_actions()
        self._setup_shortcuts()

        self.label_mode = QLabel()
        root.addWidget(self.label_mode)

        self.label_key_help = QLabel(
            "Move: Arrow keys | Resize span: Shift+Arrow | Delete: Del | Drag move/resize is supported in EDIT"
        )
        self.label_key_help.setStyleSheet("color:#555;")
        root.addWidget(self.label_key_help)

        split = QSplitter(Qt.Horizontal)

        left = QWidget()
        left.setMinimumWidth(180)
        left.setMaximumWidth(340)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.addWidget(QLabel("Tool List"))
        self.list_tools = QListWidget()
        self.list_tools.setMinimumWidth(170)
        self.list_tools.currentItemChanged.connect(self._on_tool_list_selection_changed)
        self.list_tools.itemDoubleClicked.connect(self._on_tool_list_double_clicked)
        self.list_tools.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_tools.customContextMenuRequested.connect(self._show_tool_context_menu)
        left_lay.addWidget(self.list_tools)

        geom_box = QGroupBox("Selected Tool Geometry")
        geom_form = QFormLayout(geom_box)

        self.spin_sel_row = QSpinBox()
        self.spin_sel_row.setRange(0, self.grid_rows - 1)
        self.spin_sel_col = QSpinBox()
        self.spin_sel_col.setRange(0, self.grid_cols - 1)
        self.spin_sel_row_span = QSpinBox()
        self.spin_sel_row_span.setRange(1, self.grid_rows)
        self.spin_sel_col_span = QSpinBox()
        self.spin_sel_col_span.setRange(1, self.grid_cols)

        geom_form.addRow("Row", self.spin_sel_row)
        geom_form.addRow("Col", self.spin_sel_col)
        geom_form.addRow("Row Span", self.spin_sel_row_span)
        geom_form.addRow("Col Span", self.spin_sel_col_span)

        self.spin_sel_row.valueChanged.connect(self._on_geom_editor_changed)
        self.spin_sel_col.valueChanged.connect(self._on_geom_editor_changed)
        self.spin_sel_row_span.valueChanged.connect(self._on_geom_editor_changed)
        self.spin_sel_col_span.valueChanged.connect(self._on_geom_editor_changed)

        left_lay.addWidget(geom_box)

        sim_box = QGroupBox("RX Simulator (No CAN)")
        sim_layout = QVBoxLayout(sim_box)
        sim_row = QHBoxLayout()
        self.spin_sim_value = QDoubleSpinBox()
        self.spin_sim_value.setDecimals(6)
        self.spin_sim_value.setRange(-1000000.0, 1000000.0)
        self.spin_sim_value.setValue(1.0)
        self.btn_sim_selected = QPushButton("Apply Selected RX")
        self.btn_sim_all = QPushButton("Apply All RX")
        self.btn_sim_auto = QPushButton("Auto Sim: OFF")
        self.btn_sim_auto.setCheckable(True)

        self.btn_sim_selected.clicked.connect(self.simulate_selected_rx)
        self.btn_sim_all.clicked.connect(self.simulate_all_rx)
        self.btn_sim_auto.toggled.connect(self._toggle_auto_sim)

        sim_row.addWidget(QLabel("Value"))
        sim_row.addWidget(self.spin_sim_value)
        sim_layout.addLayout(sim_row)
        sim_layout.addWidget(self.btn_sim_selected)
        sim_layout.addWidget(self.btn_sim_all)
        sim_layout.addWidget(self.btn_sim_auto)
        left_lay.addWidget(sim_box)

        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)

        self.canvas = GridCanvas(self)
        self.canvas_layout = QGridLayout(self.canvas)
        self.canvas_layout.setContentsMargins(6, 6, 6, 6)
        self.canvas_layout.setHorizontalSpacing(6)
        self.canvas_layout.setVerticalSpacing(6)
        for r in range(self.grid_rows):
            self.canvas_layout.setRowStretch(r, 1)
        for c in range(self.grid_cols):
            self.canvas_layout.setColumnStretch(c, 1)
        self.canvas.mousePressEvent = self._on_canvas_mouse_press
        self.canvas.mouseReleaseEvent = self._on_canvas_mouse_release

        right_lay.addWidget(self.canvas)

        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([210, 970])

        root.addWidget(split, 1)

        self._sync_geom_editor_from_selection()

    def _setup_menu_actions(self):
        menu_file = self.menu_bar.addMenu("File")
        menu_draw = self.menu_bar.addMenu("Draw")
        menu_arrange = self.menu_bar.addMenu("Arrange")
        menu_tools = self.menu_bar.addMenu("Tools")
        menu_diag = self.menu_bar.addMenu("Diagnostics")
        menu_sim = self.menu_bar.addMenu("RX Simulator")

        self.act_save_panel = QAction("Save Panel", self)
        self.act_load_panel = QAction("Load Panel", self)
        self.act_save_pkg = QAction("Save Package", self)
        self.act_load_pkg = QAction("Load Package", self)
        self.act_save_panel.triggered.connect(self.save_panel_to_file)
        self.act_load_panel.triggered.connect(self.load_panel_from_file)
        self.act_save_pkg.triggered.connect(self.save_package)
        self.act_load_pkg.triggered.connect(self.load_package)
        menu_file.addAction(self.act_save_panel)
        menu_file.addAction(self.act_load_panel)
        menu_file.addSeparator()
        menu_file.addAction(self.act_save_pkg)
        menu_file.addAction(self.act_load_pkg)

        self.act_draw_rect = QAction("Draw Rect", self)
        self.act_draw_line = QAction("Draw Line", self)
        self.act_draw_cancel = QAction("Cancel Draw", self)
        self.act_draw_rect.triggered.connect(lambda: self._start_draw_mode("shape_rect"))
        self.act_draw_line.triggered.connect(lambda: self._start_draw_mode("shape_line"))
        self.act_draw_cancel.triggered.connect(self._cancel_draw_mode)
        menu_draw.addAction(self.act_draw_rect)
        menu_draw.addAction(self.act_draw_line)
        menu_draw.addAction(self.act_draw_cancel)

        self.act_front = QAction("Bring Front", self)
        self.act_back = QAction("Send Back", self)
        self.act_forward = QAction("Forward", self)
        self.act_backward = QAction("Backward", self)
        self.act_front.triggered.connect(self.bring_to_front)
        self.act_back.triggered.connect(self.send_to_back)
        self.act_forward.triggered.connect(self.move_forward)
        self.act_backward.triggered.connect(self.move_backward)
        menu_arrange.addAction(self.act_front)
        menu_arrange.addAction(self.act_back)
        menu_arrange.addAction(self.act_forward)
        menu_arrange.addAction(self.act_backward)

        self.act_resize_w_plus = QAction("Width +1", self)
        self.act_resize_w_minus = QAction("Width -1", self)
        self.act_resize_h_plus = QAction("Height +1", self)
        self.act_resize_h_minus = QAction("Height -1", self)
        self.act_resize_w_plus.triggered.connect(lambda: self.resize_selected_span(1, 0))
        self.act_resize_w_minus.triggered.connect(lambda: self.resize_selected_span(-1, 0))
        self.act_resize_h_plus.triggered.connect(lambda: self.resize_selected_span(0, 1))
        self.act_resize_h_minus.triggered.connect(lambda: self.resize_selected_span(0, -1))
        menu_tools.addAction(self.act_resize_w_plus)
        menu_tools.addAction(self.act_resize_w_minus)
        menu_tools.addAction(self.act_resize_h_plus)
        menu_tools.addAction(self.act_resize_h_minus)

        self.act_check_overlap = QAction("Check TX Overlap", self)
        self.act_focus_conflict = QAction("Focus Conflict", self)
        self.act_check_overlap.triggered.connect(self.check_tx_overlap)
        self.act_focus_conflict.triggered.connect(self.focus_next_conflict)
        menu_diag.addAction(self.act_check_overlap)
        menu_diag.addAction(self.act_focus_conflict)

        self.act_sim_selected = QAction("Apply Selected RX", self)
        self.act_sim_all = QAction("Apply All RX", self)
        self.act_sim_auto = QAction("Auto Sim", self)
        self.act_sim_auto.setCheckable(True)
        self.act_sim_selected.triggered.connect(self.simulate_selected_rx)
        self.act_sim_all.triggered.connect(self.simulate_all_rx)
        self.act_sim_auto.toggled.connect(self._toggle_auto_sim)
        menu_sim.addAction(self.act_sim_selected)
        menu_sim.addAction(self.act_sim_all)
        menu_sim.addAction(self.act_sim_auto)

        self._edit_mode_actions = [
            self.btn_add_tx,
            self.btn_add_rx,
            self.btn_add_misc,
            self.btn_edit,
            self.btn_delete,
            self.act_draw_rect,
            self.act_draw_line,
            self.act_draw_cancel,
            self.act_front,
            self.act_back,
            self.act_forward,
            self.act_backward,
            self.act_resize_w_plus,
            self.act_resize_w_minus,
            self.act_resize_h_plus,
            self.act_resize_h_minus,
            self.act_check_overlap,
            self.act_focus_conflict,
        ]

    def _setup_shortcuts(self):
        self._shortcuts = []

        def _add_shortcut(keyseq, callback):
            sc = QShortcut(QKeySequence(keyseq), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(callback)
            self._shortcuts.append(sc)

        _add_shortcut(Qt.Key_Up, lambda: self.nudge_selected(0, -1))
        _add_shortcut(Qt.Key_Down, lambda: self.nudge_selected(0, 1))
        _add_shortcut(Qt.Key_Left, lambda: self.nudge_selected(-1, 0))
        _add_shortcut(Qt.Key_Right, lambda: self.nudge_selected(1, 0))
        _add_shortcut("Shift+Up", lambda: self.resize_selected_span(0, -1))
        _add_shortcut("Shift+Down", lambda: self.resize_selected_span(0, 1))
        _add_shortcut("Shift+Left", lambda: self.resize_selected_span(-1, 0))
        _add_shortcut("Shift+Right", lambda: self.resize_selected_span(1, 0))
        _add_shortcut(Qt.Key_Delete, self.delete_selected_widget)

    def set_mode(self, new_mode):
        if new_mode == self.mode:
            return

        if new_mode == "edit" and self.mode != "edit":
            enabled = bool(self.security_config.get("enabled", False))
            password = str(self.security_config.get("password", ""))
            if not verify_edit_password(self, enabled, password):
                QMessageBox.warning(self, "Denied", "Invalid password for EDIT mode.")
                return

        self.mode = new_mode
        self.refresh_mode_ui()

    def refresh_mode_ui(self):
        is_edit = self.mode == "edit"
        self.label_mode.setText(
            "EDIT: create/delete/arrange tools"
            if self.mode == "edit"
            else ("STANDBY: RX update only, TX blocked" if self.mode == "standby" else "RUN: RX update + TX enabled")
        )

        if self.mode != "run":
            self._stop_all_frame_timers()
        if self.mode == "edit" and self._sim_timer.isActive():
            self._sim_timer.stop()
            self.btn_sim_auto.blockSignals(True)
            self.btn_sim_auto.setChecked(False)
            self.btn_sim_auto.setText("Auto Sim: OFF")
            self.btn_sim_auto.blockSignals(False)
            self.act_sim_auto.blockSignals(True)
            self.act_sim_auto.setChecked(False)
            self.act_sim_auto.blockSignals(False)

        for item in getattr(self, "_edit_mode_actions", []):
            item.setEnabled(is_edit)

        self.act_sim_auto.blockSignals(True)
        self.act_sim_auto.setChecked(self.btn_sim_auto.isChecked())
        self.act_sim_auto.blockSignals(False)

        if not is_edit:
            self._cancel_draw_mode(refresh=False)

    def _start_draw_mode(self, shape_type):
        if self.mode != "edit":
            QMessageBox.information(self, "Info", "Shape draw mode is available in EDIT mode only.")
            return
        self.draw_mode = shape_type
        self.draw_start_cell = None
        self.label_mode.setText(
            f"EDIT: draw mode active ({shape_type}). Drag on empty canvas area to create shape."
        )

    def _cancel_draw_mode(self, refresh=True):
        self.draw_mode = None
        self.draw_start_cell = None
        if refresh:
            self.refresh_mode_ui()

    def _canvas_cell_from_pos(self, pos):
        if self.grid_rows <= 0 or self.grid_cols <= 0:
            return None
        if self.canvas.width() <= 0 or self.canvas.height() <= 0:
            return None

        x = max(0, min(self.canvas.width() - 1, int(pos.x())))
        y = max(0, min(self.canvas.height() - 1, int(pos.y())))
        col = int((x / max(1, self.canvas.width())) * self.grid_cols)
        row = int((y / max(1, self.canvas.height())) * self.grid_rows)
        col = max(0, min(self.grid_cols - 1, col))
        row = max(0, min(self.grid_rows - 1, row))
        return row, col

    def _on_canvas_mouse_press(self, event):
        if self.draw_mode is None or self.mode != "edit":
            return
        if event.button() != Qt.LeftButton:
            return
        self.draw_start_cell = self._canvas_cell_from_pos(event.pos())

    def _on_canvas_mouse_release(self, event):
        if self.draw_mode is None or self.mode != "edit":
            return
        if event.button() != Qt.LeftButton:
            return
        if self.draw_start_cell is None:
            return

        end_cell = self._canvas_cell_from_pos(event.pos())
        if end_cell is None:
            self.draw_start_cell = None
            return

        r1, c1 = self.draw_start_cell
        r2, c2 = end_cell
        row = min(r1, r2)
        col = min(c1, c2)
        row_span = max(1, abs(r2 - r1) + 1)
        col_span = max(1, abs(c2 - c1) + 1)

        shape_type = self.draw_mode
        cfg = {
            "id": str(uuid.uuid4()),
            "widget_type": shape_type,
            "title": f"Shape {self._shape_counter}",
            "row": row,
            "col": col,
            "row_span": row_span,
            "col_span": col_span,
            "parent_id": None,
            "z_index": self._next_z(),
            "behavior": "none",
            "binding": {},
        }
        self._shape_counter += 1

        self._normalize_config(cfg)

        if shape_type == "shape_line":
            dr = abs(r2 - r1)
            dc = abs(c2 - c1)
            if dc >= dr:
                cfg["binding"]["shape_line_direction"] = "horizontal"
                cfg["row_span"] = 1
                cfg["col_span"] = max(1, col_span)
            else:
                cfg["binding"]["shape_line_direction"] = "vertical"
                cfg["col_span"] = 1
                cfg["row_span"] = max(1, row_span)

        self._upsert_widget_config(cfg)
        self.selected_widget_id = cfg.get("id")
        self.rebuild_grid()
        self.draw_start_cell = None

    def add_widget(self, behavior=None):
        dlg = WidgetConfigDialog(
            self.db_messages,
            self,
            fixed_behavior=behavior,
            parent_candidates=self._group_parent_candidates(),
            live_preview_default=False,
        )
        if behavior == "tx":
            dlg.combo_widget_type.setCurrentText("button")
        elif behavior == "rx":
            dlg.combo_widget_type.setCurrentText("status_lamp")

        preview_id = dlg._config_id
        preview_applied = False

        def _preview(cfg):
            nonlocal preview_applied
            preview_applied = True
            self._normalize_config(cfg)
            self._upsert_widget_config(cfg)
            self.selected_widget_id = cfg.get("id")
            self.rebuild_grid()

        dlg.config_changed.connect(_preview)
        if dlg.exec_() != dlg.Accepted:
            if preview_applied:
                self.widgets_config = [x for x in self.widgets_config if x.get("id") != preview_id]
                self.selected_widget_id = None
                self.rebuild_grid()
            return

        cfg = dlg.get_config(strict=True)
        self._normalize_config(cfg)
        self._upsert_widget_config(cfg)
        self.selected_widget_id = cfg.get("id")
        self.rebuild_grid()

    def edit_selected_widget(self):
        cfg = self._get_selected_config()
        if not cfg:
            QMessageBox.information(self, "Info", "Select a widget first.")
            return

        original_cfg = copy.deepcopy(cfg)
        dlg = WidgetConfigDialog(
            self.db_messages,
            self,
            preset=cfg,
            parent_candidates=self._group_parent_candidates(exclude_id=cfg.get("id")),
            live_preview_default=True,
        )
        preview_applied = False

        def _preview(new_cfg):
            nonlocal preview_applied
            preview_applied = True
            self._normalize_config(new_cfg)
            self._upsert_widget_config(new_cfg)
            self.selected_widget_id = new_cfg.get("id")
            self.rebuild_grid()

        dlg.config_changed.connect(_preview)
        if dlg.exec_() != dlg.Accepted:
            if preview_applied:
                self._upsert_widget_config(original_cfg)
                self.selected_widget_id = original_cfg.get("id")
                self.rebuild_grid()
            return

        new_cfg = dlg.get_config(strict=True)
        self._normalize_config(new_cfg)
        self._upsert_widget_config(new_cfg)
        self.selected_widget_id = new_cfg.get("id")
        self.rebuild_grid()

    def delete_selected_widget(self):
        if self.mode != "edit":
            return
        cfg = self._get_selected_config()
        if not cfg:
            QMessageBox.information(self, "Info", "Select a widget first.")
            return

        self.widgets_config = [x for x in self.widgets_config if x.get("id") != cfg.get("id")]
        self.selected_widget_id = None
        self.rebuild_grid()

    def _upsert_widget_config(self, cfg):
        target_id = cfg.get("id")
        for i, old in enumerate(self.widgets_config):
            if old.get("id") == target_id:
                cfg["z_index"] = old.get("z_index", cfg.get("z_index", 0))
                self.widgets_config[i] = cfg
                return
        cfg["z_index"] = cfg.get("z_index", self._next_z())
        self.widgets_config.append(cfg)

    def _next_z(self):
        if not self.widgets_config:
            return 0
        return max(int(c.get("z_index", 0)) for c in self.widgets_config) + 1

    def _get_selected_config(self):
        if not self.selected_widget_id:
            return None
        for cfg in self.widgets_config:
            if cfg.get("id") == self.selected_widget_id:
                return cfg
        return None

    def _normalize_config(self, cfg):
        cfg.setdefault("id", str(uuid.uuid4()))
        cfg.setdefault("widget_type", "label")
        cfg.setdefault("title", "Widget")
        cfg.setdefault("row", 0)
        cfg.setdefault("col", 0)
        cfg.setdefault("row_span", 1)
        cfg.setdefault("col_span", 1)
        cfg.setdefault("parent_id", None)
        cfg.setdefault("z_index", 0)
        cfg.setdefault("behavior", "none")

        binding = cfg.setdefault("binding", {})
        binding.setdefault("bus", 1)
        binding.setdefault("can_id", 0)
        binding.setdefault("signal_name", None)
        binding.setdefault("dlc", 8)
        binding.setdefault("start_bit", 0)
        binding.setdefault("bit_length", 8)
        binding.setdefault("scale", 1.0)
        binding.setdefault("offset", 0.0)
        binding.setdefault("signed", False)
        binding.setdefault("byte_order", "little_endian")
        binding.setdefault("min", 0.0)
        binding.setdefault("max", 100.0)
        binding.setdefault("tx_resolution", 1.0)
        binding.setdefault("tx_cycle_mode", "immediate")
        binding.setdefault("tx_cycle_ms", 100)
        binding.setdefault("tx_press_value", binding.get("max", 100.0))
        binding.setdefault("tx_release_value", binding.get("min", 0.0))
        binding.setdefault("tx_on_value", 1.0)
        binding.setdefault("tx_off_value", 0.0)
        binding.setdefault("tx_hold_period_ms", 80)
        binding.setdefault("rx_on_op", "ge")
        binding.setdefault("rx_on_a", binding.get("max", 100.0))
        binding.setdefault("rx_on_b", binding.get("max", 100.0))
        binding.setdefault("rx_off_op", "lt")
        binding.setdefault("rx_off_a", binding.get("max", 100.0))
        binding.setdefault("rx_off_b", binding.get("max", 100.0))
        binding.setdefault("shape_kind", "line")
        binding.setdefault("shape_line_direction", "horizontal")
        binding.setdefault("stroke_color", "#333333")
        binding.setdefault("stroke_width", 2)
        binding.setdefault("stroke_style", "solid")
        binding.setdefault("fill", False)
        binding.setdefault("fill_color", "#E8F1FF")
        binding.setdefault("corner_radius", 0)
        binding.setdefault("unit", "")

        if cfg.get("parent_id") == cfg.get("id"):
            cfg["parent_id"] = None

    def _group_parent_candidates(self, exclude_id=None):
        out = []
        for cfg in self.widgets_config:
            if cfg.get("id") == exclude_id:
                continue
            if cfg.get("widget_type") in ("group_box", "tab_container"):
                out.append(
                    {
                        "id": cfg.get("id"),
                        "title": cfg.get("title", "Group"),
                        "widget_type": cfg.get("widget_type", "group_box"),
                    }
                )
        return out

    def _refresh_tool_list(self):
        overlap_ids, overlap_map = self._collect_overlap_details()
        self._overlap_map = overlap_map

        self._tool_list_syncing = True
        self.list_tools.clear()
        sorted_cfg = sorted(self.widgets_config, key=lambda c: int(c.get("z_index", 0)))
        for cfg in sorted_cfg:
            binding = cfg.get("binding", {})
            parent_id = cfg.get("parent_id")
            parent_text = "ROOT" if not parent_id else f"P:{str(parent_id)[:8]}"
            text = f"{cfg.get('title', 'Widget')} [{cfg.get('widget_type', '-')}] [{cfg.get('behavior', '-').upper()}] B{binding.get('bus', 1)} 0x{int(binding.get('can_id', 0)):X}"
            text = f"{text} [{parent_text}]"
            it = QListWidgetItem(text)
            wid = cfg.get("id")
            it.setData(Qt.UserRole, wid)
            if wid in overlap_ids:
                it.setForeground(QColor("#C62828"))
                targets = sorted(list(overlap_map.get(wid, set())))
                if targets:
                    it.setData(Qt.UserRole + 1, targets[0])
                    it.setToolTip(f"TX overlap with {len(targets)} tool(s). Double-click to focus conflict.")
            self.list_tools.addItem(it)
            if wid == self.selected_widget_id:
                self.list_tools.setCurrentItem(it)
        self._tool_list_syncing = False

    def _cfg_by_id(self, widget_id):
        for cfg in self.widgets_config:
            if cfg.get("id") == widget_id:
                return cfg
        return None

    def _is_descendant(self, maybe_child_id, maybe_parent_id):
        current_id = maybe_child_id
        guard = 0
        while current_id and guard < 200:
            guard += 1
            cfg = self._cfg_by_id(current_id)
            if not cfg:
                return False
            pid = cfg.get("parent_id")
            if not pid:
                return False
            if pid == maybe_parent_id:
                return True
            current_id = pid
        return False

    def _hit_group_parent_from_global(self, global_pos, exclude_id=None):
        selected_id = exclude_id
        for cfg in sorted(self.widgets_config, key=lambda x: int(x.get("z_index", 0)), reverse=True):
            wid = cfg.get("id")
            if wid == selected_id:
                continue
            if cfg.get("widget_type") not in ("group_box", "tab_container"):
                continue
            frame = self.widget_frames.get(wid)
            if frame is None:
                continue
            local = frame.mapFromGlobal(global_pos)
            if frame.rect().contains(local):
                if selected_id and self._is_descendant(wid, selected_id):
                    continue
                return wid
        return None

    def _cell_from_global_in_parent(self, parent_id, global_pos):
        if parent_id and parent_id in self.widget_child_hosts and self.widget_child_hosts[parent_id] is not None:
            host_layout = self.widget_child_hosts[parent_id]
            host_widget = host_layout.parentWidget()
            if host_widget is not None and host_widget.width() > 0 and host_widget.height() > 0:
                local = host_widget.mapFromGlobal(global_pos)
                x = max(0, min(host_widget.width() - 1, int(local.x())))
                y = max(0, min(host_widget.height() - 1, int(local.y())))
                col = int((x / max(1, host_widget.width())) * self.grid_cols)
                row = int((y / max(1, host_widget.height())) * self.grid_rows)
                col = max(0, min(self.grid_cols - 1, col))
                row = max(0, min(self.grid_rows - 1, row))
                return row, col

        local = self.canvas.mapFromGlobal(global_pos)
        x = max(0, min(max(0, self.canvas.width() - 1), int(local.x())))
        y = max(0, min(max(0, self.canvas.height() - 1), int(local.y())))
        col = int((x / max(1, self.canvas.width())) * self.grid_cols)
        row = int((y / max(1, self.canvas.height())) * self.grid_rows)
        col = max(0, min(self.grid_cols - 1, col))
        row = max(0, min(self.grid_rows - 1, row))
        return row, col

    def _on_tool_list_selection_changed(self, current, _previous):
        if self._tool_list_syncing:
            return
        if current is None:
            return
        wid = current.data(Qt.UserRole)
        self.selected_widget_id = wid
        self._refresh_selection_ui()

    def _on_tool_list_double_clicked(self, item):
        if item is None:
            return
        wid = item.data(Qt.UserRole)
        target = item.data(Qt.UserRole + 1)
        if not wid or not target:
            return
        self.selected_widget_id = wid
        self.focus_next_conflict()

    def _on_geom_editor_changed(self, _value):
        if self._prop_syncing:
            return
        if self.mode != "edit":
            return

        cfg = self._get_selected_config()
        if not cfg:
            return

        cfg["row"] = int(self.spin_sel_row.value())
        cfg["col"] = int(self.spin_sel_col.value())
        cfg["row_span"] = int(self.spin_sel_row_span.value())
        cfg["col_span"] = int(self.spin_sel_col_span.value())
        self.rebuild_grid()

    def _sync_geom_editor_from_selection(self):
        self._prop_syncing = True
        try:
            cfg = self._get_selected_config()
            enabled = bool(cfg) and self.mode == "edit"
            self.spin_sel_row.setEnabled(enabled)
            self.spin_sel_col.setEnabled(enabled)
            self.spin_sel_row_span.setEnabled(enabled)
            self.spin_sel_col_span.setEnabled(enabled)

            if not cfg:
                self.spin_sel_row.setValue(0)
                self.spin_sel_col.setValue(0)
                self.spin_sel_row_span.setValue(1)
                self.spin_sel_col_span.setValue(1)
                return

            self.spin_sel_row.setRange(0, self.grid_rows - 1)
            self.spin_sel_col.setRange(0, self.grid_cols - 1)
            self.spin_sel_row_span.setRange(1, self.grid_rows)
            self.spin_sel_col_span.setRange(1, self.grid_cols)

            self.spin_sel_row.setValue(max(0, min(self.grid_rows - 1, int(cfg.get("row", 0)))))
            self.spin_sel_col.setValue(max(0, min(self.grid_cols - 1, int(cfg.get("col", 0)))))
            self.spin_sel_row_span.setValue(max(1, min(self.grid_rows, int(cfg.get("row_span", 1)))))
            self.spin_sel_col_span.setValue(max(1, min(self.grid_cols, int(cfg.get("col_span", 1)))))
        finally:
            self._prop_syncing = False

    def _show_tool_context_menu(self, pos):
        item = self.list_tools.itemAt(pos)
        if item is not None:
            self.selected_widget_id = item.data(Qt.UserRole)
            self._refresh_selection_ui()

        menu = QMenu(self)
        act_edit = menu.addAction("Edit")
        act_delete = menu.addAction("Delete")
        menu.addSeparator()
        act_front = menu.addAction("Bring Front")
        act_back = menu.addAction("Send Back")
        act_forward = menu.addAction("Forward")
        act_backward = menu.addAction("Backward")
        menu.addSeparator()
        act_conflict = menu.addAction("Focus Conflict")

        chosen = menu.exec_(self.list_tools.mapToGlobal(pos))
        if chosen == act_edit:
            self.edit_selected_widget()
        elif chosen == act_delete:
            self.delete_selected_widget()
        elif chosen == act_front:
            self.bring_to_front()
        elif chosen == act_back:
            self.send_to_back()
        elif chosen == act_forward:
            self.move_forward()
        elif chosen == act_backward:
            self.move_backward()
        elif chosen == act_conflict:
            self.focus_next_conflict()

    def rebuild_grid(self):
        while self.canvas_layout.count():
            item = self.canvas_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

        self.widget_frames.clear()
        self.widget_controls.clear()
        self.widget_child_hosts.clear()

        sorted_cfg = sorted(self.widgets_config, key=lambda c: int(c.get("z_index", 0)))

        for cfg in sorted_cfg:
            frame = QFrame()
            frame.setFrameShape(QFrame.StyledPanel)
            frame.setObjectName(cfg.get("id"))

            frame_layout = QVBoxLayout(frame)
            frame_layout.setContentsMargins(6, 6, 6, 6)
            frame_layout.setSpacing(4)

            behavior = str(cfg.get("behavior", "none")).upper()
            title = QLabel(f"[{behavior}] {cfg.get('title', 'Widget')}")
            title.setAlignment(Qt.AlignCenter)
            frame_layout.addWidget(title)

            ctrl, child_host = self._create_runtime_widget(cfg)
            frame_layout.addWidget(ctrl, 1)

            wid = cfg.get("id")
            self.widget_frames[wid] = frame
            self.widget_controls[wid] = ctrl
            self.widget_child_hosts[wid] = child_host

            self._bind_select(frame, wid)
            self._bind_select(title, wid)

        for cfg in sorted_cfg:
            wid = cfg.get("id")
            frame = self.widget_frames.get(wid)
            if frame is None:
                continue

            parent_id = cfg.get("parent_id")
            if parent_id and parent_id == wid:
                parent_id = None

            row = int(cfg.get("row", 0))
            col = int(cfg.get("col", 0))
            row_span = max(1, int(cfg.get("row_span", 1)))
            col_span = max(1, int(cfg.get("col_span", 1)))

            if parent_id and parent_id in self.widget_child_hosts and self.widget_child_hosts[parent_id] is not None:
                host_layout = self.widget_child_hosts[parent_id]
                host_layout.addWidget(frame, row, col, row_span, col_span)
            else:
                self.canvas_layout.addWidget(frame, row, col, row_span, col_span)

            frame.raise_()

        self._refresh_selection_ui()
        self._refresh_tool_list()
        self._sync_frame_timers_from_configs()

    def _bind_select(self, widget, widget_id):
        def _on_press(event):
            self.selected_widget_id = widget_id
            self._refresh_selection_ui()

            if self.mode == "edit" and self.draw_mode is None and event is not None and event.button() == Qt.LeftButton:
                try:
                    self._drag_target_id = widget_id
                    self._drag_start_global = event.globalPos()
                    cfg = self._get_selected_config()
                    if cfg:
                        self._drag_origin_cell = (int(cfg.get("row", 0)), int(cfg.get("col", 0)))
                        self._drag_origin_span = (int(cfg.get("row_span", 1)), int(cfg.get("col_span", 1)))

                    local = event.pos()
                    w = max(1, widget.width())
                    h = max(1, widget.height())
                    self._drag_resize_mode = (local.x() >= (w - 16) and local.y() >= (h - 16))
                except Exception:
                    self._drag_target_id = None
                    self._drag_start_global = None
                    self._drag_origin_cell = None
                    self._drag_origin_span = None
                    self._drag_resize_mode = False

        def _on_release(event):
            if self.mode != "edit" or self.draw_mode is not None:
                return
            if self._drag_target_id != widget_id:
                return
            if self._drag_start_global is None or self._drag_origin_cell is None:
                return
            if event is None:
                return

            try:
                end_pos = event.globalPos()
                delta_x = int(end_pos.x() - self._drag_start_global.x())
                delta_y = int(end_pos.y() - self._drag_start_global.y())
                cell_w = max(1.0, float(self.canvas.width()) / max(1, self.grid_cols))
                cell_h = max(1.0, float(self.canvas.height()) / max(1, self.grid_rows))

                cfg = self._get_selected_config()
                if not cfg:
                    return

                if self._drag_resize_mode:
                    dcol_span = int(round(delta_x / cell_w))
                    drow_span = int(round(delta_y / cell_h))
                    row_span0, col_span0 = self._drag_origin_span or (int(cfg.get("row_span", 1)), int(cfg.get("col_span", 1)))
                    cfg["col_span"] = max(1, min(self.grid_cols, col_span0 + dcol_span))
                    cfg["row_span"] = max(1, min(self.grid_rows, row_span0 + drow_span))
                    self.rebuild_grid()
                else:
                    dcol = int(round(delta_x / cell_w))
                    drow = int(round(delta_y / cell_h))
                    old_parent = cfg.get("parent_id")
                    new_parent = self._hit_group_parent_from_global(end_pos, exclude_id=widget_id)
                    cfg["parent_id"] = new_parent

                    if drow != 0 or dcol != 0 or old_parent != new_parent:
                        row_new, col_new = self._cell_from_global_in_parent(new_parent, end_pos)
                        cfg["row"] = row_new
                        cfg["col"] = col_new

                    self.rebuild_grid()
            finally:
                self._drag_target_id = None
                self._drag_start_global = None
                self._drag_origin_cell = None
                self._drag_origin_span = None
                self._drag_resize_mode = False

        widget.mousePressEvent = _on_press
        widget.mouseReleaseEvent = _on_release

    def _refresh_selection_ui(self):
        for wid, frame in self.widget_frames.items():
            selected = wid == self.selected_widget_id
            if selected:
                frame.setStyleSheet("QFrame { border: 2px solid #0078D7; background: #F4F9FF; }")
            else:
                frame.setStyleSheet("QFrame { border: 1px solid #C8C8C8; background: #FFFFFF; }")

        if self.selected_widget_id:
            self._tool_list_syncing = True
            for i in range(self.list_tools.count()):
                it = self.list_tools.item(i)
                if it.data(Qt.UserRole) == self.selected_widget_id:
                    self.list_tools.setCurrentRow(i)
                    break
            self._tool_list_syncing = False

        self._sync_geom_editor_from_selection()

    def _stroke_qt_style(self, style_name):
        if style_name == "dash":
            return "dashed"
        if style_name == "dot":
            return "dotted"
        return "solid"

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
            push_value = float(binding.get("tx_press_value", max_v))
            pull_value = float(binding.get("tx_release_value", min_v))
            hold_period_ms = int(binding.get("tx_hold_period_ms", 80))
            hold_period_ms = max(20, min(1000, hold_period_ms))

            hold_timer = QTimer(btn)
            hold_timer.setInterval(hold_period_ms)
            hold_timer.timeout.connect(lambda: self._emit_tx(cfg, push_value))

            def _pressed():
                self._emit_tx(cfg, push_value)
                hold_timer.start()

            def _released():
                hold_timer.stop()
                self._emit_tx(cfg, pull_value)

            btn.pressed.connect(_pressed)
            btn.released.connect(_released)
            return btn, None

        if wtype == "toggle":
            btn = QPushButton("OFF")
            btn.setCheckable(True)
            on_value = float(binding.get("tx_on_value", max_v))
            off_value = float(binding.get("tx_off_value", min_v))

            def _toggle(checked):
                btn.setText("ON" if checked else "OFF")
                self._emit_tx(cfg, on_value if checked else off_value)

            btn.toggled.connect(_toggle)
            return btn, None

        if wtype == "slider":
            container = QWidget()
            lay = QVBoxLayout(container)
            lay.setContentsMargins(0, 0, 0, 0)
            slider = QSlider(Qt.Horizontal)
            slider.setObjectName("slider")
            steps = self._slider_steps(binding, min_v, max_v)
            slider.setRange(0, steps)
            value_label = QLabel(f"{min_v:.3f}")
            value_label.setObjectName("value_label")
            value_label.setAlignment(Qt.AlignCenter)
            lay.addWidget(slider)
            lay.addWidget(value_label)

            def _on_changed(v):
                ratio = 0.0 if steps <= 0 else (v / float(steps))
                phys = min_v + ((max_v - min_v) * ratio)
                value_label.setText(f"{phys:.3f}")
                if behavior == "tx":
                    self._emit_tx(cfg, phys)

            slider.valueChanged.connect(_on_changed)
            return container, None

        if wtype == "spinbox":
            spin = QDoubleSpinBox()
            spin.setRange(min_v, max_v)
            step = float(binding.get("tx_resolution", max((max_v - min_v) / 100.0, 0.001)))
            step = max(step, 0.000001)
            spin.setSingleStep(step)
            spin.setDecimals(self._resolution_decimals(step))
            if behavior == "tx":
                spin.valueChanged.connect(lambda v: self._emit_tx(cfg, float(v)))
            return spin, None

        if wtype == "progress":
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(0)
            return bar, None

        if wtype == "status_lamp":
            lamp = QLabel("OFF")
            lamp.setAlignment(Qt.AlignCenter)
            lamp.setStyleSheet("background:#9E9E9E; color:white; border-radius:4px; padding:4px;")
            return lamp, None

        if wtype == "group_box":
            grp = QGroupBox(cfg.get("title", "Group"))
            inner = QWidget()
            inner_layout = QGridLayout(inner)
            inner_layout.setContentsMargins(4, 4, 4, 4)
            inner_layout.setHorizontalSpacing(4)
            inner_layout.setVerticalSpacing(4)
            grp_lay = QVBoxLayout(grp)
            grp_lay.setContentsMargins(6, 6, 6, 6)
            grp_lay.addWidget(inner)
            return grp, inner_layout

        if wtype == "tab_container":
            tabs = QTabWidget()
            tab1 = QWidget()
            tab1_layout = QGridLayout(tab1)
            tab1_layout.setContentsMargins(4, 4, 4, 4)
            tab1_layout.setHorizontalSpacing(4)
            tab1_layout.setVerticalSpacing(4)
            tabs.addTab(tab1, "Tab 1")
            tabs.addTab(QWidget(), "Tab 2")
            return tabs, tab1_layout

        if wtype == "shape_line":
            line = QFrame()
            direction = str(binding.get("shape_line_direction", "horizontal"))
            if direction == "vertical":
                line.setFrameShape(QFrame.VLine)
            else:
                line.setFrameShape(QFrame.HLine)
            line.setFrameShadow(QFrame.Plain)
            stroke = binding.get("stroke_color", "#333333")
            width = int(binding.get("stroke_width", 2))
            qt_style = self._stroke_qt_style(binding.get("stroke_style", "solid"))
            if direction == "vertical":
                line.setStyleSheet(f"border: 0; border-left: {width}px {qt_style} {stroke};")
            else:
                line.setStyleSheet(f"border: 0; border-top: {width}px {qt_style} {stroke};")
            return line, None

        if wtype == "shape_rect":
            rect = QLabel("")
            stroke = binding.get("stroke_color", "#333333")
            width = int(binding.get("stroke_width", 2))
            qt_style = self._stroke_qt_style(binding.get("stroke_style", "solid"))
            corner_radius = int(binding.get("corner_radius", 0))
            if binding.get("fill", False):
                fill = binding.get("fill_color", "#E8F1FF")
            else:
                fill = "transparent"
            rect.setStyleSheet(
                f"border: {width}px {qt_style} {stroke}; background:{fill}; border-radius:{corner_radius}px;"
            )
            return rect, None

        return QLabel("-"), None

    def bring_to_front(self):
        cfg = self._get_selected_config()
        if not cfg:
            return
        cfg["z_index"] = self._next_z()
        self.rebuild_grid()

    def send_to_back(self):
        cfg = self._get_selected_config()
        if not cfg:
            return
        min_z = min((int(c.get("z_index", 0)) for c in self.widgets_config), default=0)
        cfg["z_index"] = min_z - 1
        self.rebuild_grid()

    def move_forward(self):
        cfg = self._get_selected_config()
        if not cfg:
            return
        cfg["z_index"] = int(cfg.get("z_index", 0)) + 1
        self.rebuild_grid()

    def move_backward(self):
        cfg = self._get_selected_config()
        if not cfg:
            return
        cfg["z_index"] = int(cfg.get("z_index", 0)) - 1
        self.rebuild_grid()

    def nudge_selected(self, dx, dy):
        if self.mode != "edit":
            return
        cfg = self._get_selected_config()
        if not cfg:
            return

        col = int(cfg.get("col", 0)) + int(dx)
        row = int(cfg.get("row", 0)) + int(dy)
        col = max(0, min(self.grid_cols - 1, col))
        row = max(0, min(self.grid_rows - 1, row))
        cfg["col"] = col
        cfg["row"] = row
        self.rebuild_grid()

    def resize_selected_span(self, dcol_span, drow_span):
        if self.mode != "edit":
            return
        cfg = self._get_selected_config()
        if not cfg:
            return

        col_span = int(cfg.get("col_span", 1)) + int(dcol_span)
        row_span = int(cfg.get("row_span", 1)) + int(drow_span)
        cfg["col_span"] = max(1, min(self.grid_cols, col_span))
        cfg["row_span"] = max(1, min(self.grid_rows, row_span))
        self.rebuild_grid()

    def check_tx_overlap(self):
        overlap_ids, overlap_map, issues = self._collect_overlap_issue_lines()
        self._overlap_map = overlap_map

        if not issues:
            QMessageBox.information(self, "TX Overlap Check", "No overlapping TX bit ranges found.")
            self._refresh_tool_list()
            return

        self._refresh_tool_list()
        QMessageBox.warning(
            self,
            "TX Overlap Check",
            "Overlapping TX bit ranges found:\n\n" + "\n".join(issues[:30]) +
            ("\n\n..." if len(issues) > 30 else "")
        )

    def _collect_overlap_details(self):
        ranges_by_frame = {}
        overlap_ids = set()
        overlap_map = {}
        for cfg in self.widgets_config:
            if cfg.get("behavior") != "tx":
                continue
            binding = cfg.get("binding", {})
            key = self._frame_key_from_binding(binding)
            start_bit = int(binding.get("start_bit", 0))
            bit_length = int(binding.get("bit_length", 1))
            end_bit = start_bit + max(1, bit_length) - 1
            ranges_by_frame.setdefault(key, []).append(
                {"id": cfg.get("id"), "start": start_bit, "end": end_bit}
            )

        for _, items in ranges_by_frame.items():
            items = sorted(items, key=lambda x: x["start"])
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    a = items[i]
                    b = items[j]
                    if a["end"] < b["start"]:
                        break
                    if b["end"] >= a["start"]:
                        overlap_ids.add(a["id"])
                        overlap_ids.add(b["id"])
                        overlap_map.setdefault(a["id"], set()).add(b["id"])
                        overlap_map.setdefault(b["id"], set()).add(a["id"])
        return overlap_ids, overlap_map

    def _collect_overlap_issue_lines(self):
        ranges_by_frame = {}
        issues = []
        overlap_ids = set()
        overlap_map = {}

        for cfg in self.widgets_config:
            if cfg.get("behavior") != "tx":
                continue
            binding = cfg.get("binding", {})
            key = self._frame_key_from_binding(binding)
            start_bit = int(binding.get("start_bit", 0))
            bit_length = int(binding.get("bit_length", 1))
            end_bit = start_bit + max(1, bit_length) - 1
            ranges_by_frame.setdefault(key, []).append(
                {
                    "id": cfg.get("id"),
                    "title": cfg.get("title", "Widget"),
                    "start": start_bit,
                    "end": end_bit,
                }
            )

        for key, items in ranges_by_frame.items():
            items = sorted(items, key=lambda x: x["start"])
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    a = items[i]
                    b = items[j]
                    if a["end"] < b["start"]:
                        break
                    if b["end"] >= a["start"]:
                        overlap_ids.add(a["id"])
                        overlap_ids.add(b["id"])
                        overlap_map.setdefault(a["id"], set()).add(b["id"])
                        overlap_map.setdefault(b["id"], set()).add(a["id"])
                        issues.append(
                            f"Frame B{key[0]} 0x{key[1]:X} DLC {key[2]}: "
                            f"{a['title']}[{a['start']}..{a['end']}] <-> {b['title']}[{b['start']}..{b['end']}]"
                        )

        return overlap_ids, overlap_map, issues

    def focus_next_conflict(self):
        if not self.selected_widget_id:
            QMessageBox.information(self, "Conflict Focus", "Select a tool first.")
            return

        targets = sorted(list(self._overlap_map.get(self.selected_widget_id, set())))
        if not targets:
            QMessageBox.information(self, "Conflict Focus", "No conflict target for selected tool.")
            return

        idx = int(self._conflict_cursor.get(self.selected_widget_id, 0))
        idx = idx % len(targets)
        target = targets[idx]
        self._conflict_cursor[self.selected_widget_id] = idx + 1

        self.selected_widget_id = target
        self._refresh_selection_ui()

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
        if cfg.get("behavior") != "tx":
            return
        binding = cfg.get("binding", {})
        cycle_mode = str(binding.get("tx_cycle_mode", "immediate"))
        if cycle_mode == "immediate":
            self.request_tx_value.emit(binding, float(value))
            return

        if not hasattr(self.main_window, "stage_user_panel_value"):
            self.request_tx_value.emit(binding, float(value))
            return

        try:
            self.main_window.stage_user_panel_value(binding, float(value))
        except Exception as e:
            if hasattr(self.main_window, "statusBar"):
                self.main_window.statusBar().showMessage(f"User panel TX stage failed: {e}", 4000)
            return

        self._sync_frame_timers_from_configs()

    def _frame_key_from_binding(self, binding):
        return (
            int(binding.get("bus", 1)),
            int(binding.get("can_id", 0)),
            max(1, min(64, int(binding.get("dlc", 8)))),
        )

    def _get_dbc_cycle_ms(self, bus_num, can_id):
        msg = self.db_messages.get(int(bus_num), {}).get(int(can_id))
        if not msg:
            return None

        for attr_name in ("cycle_time", "cycle", "gen_msg_cycle_time"):
            v = getattr(msg, attr_name, None)
            if isinstance(v, (int, float)) and v > 0:
                return int(max(1, min(600000, v)))
        return None

    def _resolve_cycle_ms_for_binding(self, binding):
        mode = str(binding.get("tx_cycle_mode", "immediate"))
        if mode == "immediate":
            return None

        fixed_ms = int(binding.get("tx_cycle_ms", 100))
        fixed_ms = max(1, min(600000, fixed_ms))
        dbc_ms = self._get_dbc_cycle_ms(binding.get("bus", 1), binding.get("can_id", 0))

        if mode == "fixed":
            return fixed_ms
        if mode == "dbc":
            return dbc_ms if dbc_ms is not None else fixed_ms
        if mode == "fastest":
            if dbc_ms is None:
                return fixed_ms
            return min(fixed_ms, dbc_ms)
        return fixed_ms

    def _compute_frame_cycle_ms(self, frame_key):
        candidates = []
        for cfg in self.widgets_config:
            if cfg.get("behavior") != "tx":
                continue
            binding = cfg.get("binding", {})
            if self._frame_key_from_binding(binding) != frame_key:
                continue
            cycle_ms = self._resolve_cycle_ms_for_binding(binding)
            if cycle_ms is not None:
                candidates.append(int(cycle_ms))

        if not candidates:
            return None
        return max(1, min(600000, min(candidates)))

    def _flush_frame(self, frame_key):
        if self.mode != "run":
            return
        if not hasattr(self.main_window, "flush_user_panel_frame"):
            return
        bus_num, can_id, dlc = frame_key
        try:
            self.main_window.flush_user_panel_frame(bus_num, can_id, dlc)
        except Exception as e:
            if hasattr(self.main_window, "statusBar"):
                self.main_window.statusBar().showMessage(f"User panel frame TX failed: {e}", 4000)

    def _stop_all_frame_timers(self):
        for timer in self._frame_timers.values():
            try:
                timer.stop()
            except Exception:
                pass
        self._frame_timers.clear()

    def _sync_frame_timers_from_configs(self):
        if self.mode != "run":
            self._stop_all_frame_timers()
            return

        keys = set()
        for cfg in self.widgets_config:
            if cfg.get("behavior") != "tx":
                continue
            binding = cfg.get("binding", {})
            key = self._frame_key_from_binding(binding)
            cycle = self._compute_frame_cycle_ms(key)
            if cycle is not None:
                keys.add((key, cycle))

        active_key_map = {k: c for k, c in keys}

        for key in list(self._frame_timers.keys()):
            if key not in active_key_map:
                self._frame_timers[key].stop()
                del self._frame_timers[key]

        for key, cycle_ms in active_key_map.items():
            timer = self._frame_timers.get(key)
            if timer is None:
                timer = QTimer(self)
                timer.timeout.connect(lambda _k=key: self._flush_frame(_k))
                self._frame_timers[key] = timer

            if timer.interval() != int(cycle_ms):
                timer.setInterval(int(cycle_ms))
            if not timer.isActive():
                timer.start()

    def _slider_steps(self, binding, min_v, max_v):
        resolution = float(binding.get("tx_resolution", 1.0))
        resolution = max(resolution, 0.000001)
        steps = int(round((max_v - min_v) / resolution))
        return max(1, min(steps, 5000))

    def _resolution_decimals(self, step):
        text = f"{float(step):.10f}".rstrip("0")
        if "." not in text:
            return 0
        return min(6, len(text.split(".", 1)[1]))

    def _eval_condition(self, value, op, a, b):
        if op == "gt":
            return value > a
        if op == "ge":
            return value >= a
        if op == "lt":
            return value < a
        if op == "le":
            return value <= a
        if op == "eq":
            return value == a
        if op == "ne":
            return value != a
        lo = min(a, b)
        hi = max(a, b)
        if op == "between":
            return lo <= value <= hi
        if op == "outside":
            return value < lo or value > hi
        return False

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

    def _update_widget_value(self, cfg, value, force=False):
        if self.mode == "edit" and not force:
            return

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
                slider = ctrl.findChild(QSlider, "slider")
                value_label = ctrl.findChild(QLabel, "value_label")
                if slider is not None:
                    steps = max(1, int(slider.maximum()))
                    ratio = 0.0 if max_v == min_v else (v - min_v) / (max_v - min_v)
                    ratio = min(1.0, max(0.0, ratio))
                    slider.blockSignals(True)
                    slider.setValue(int(ratio * steps))
                    slider.blockSignals(False)
                    if value_label is not None:
                        value_label.setText(f"{v:.3f}")
            return

        if wtype == "spinbox":
            if isinstance(ctrl, QDoubleSpinBox):
                ctrl.blockSignals(True)
                ctrl.setValue(v)
                ctrl.blockSignals(False)
            return

        if wtype == "toggle":
            if isinstance(ctrl, QPushButton) and ctrl.isCheckable():
                on_value = float(binding.get("tx_on_value", max_v))
                off_value = float(binding.get("tx_off_value", min_v))
                pivot = (on_value + off_value) / 2.0
                is_on = v >= pivot
                ctrl.blockSignals(True)
                ctrl.setChecked(is_on)
                ctrl.setText("ON" if is_on else "OFF")
                ctrl.blockSignals(False)
            return

        if wtype == "status_lamp":
            on_op = str(binding.get("rx_on_op", "ge"))
            on_a = float(binding.get("rx_on_a", max_v))
            on_b = float(binding.get("rx_on_b", max_v))
            off_op = str(binding.get("rx_off_op", "lt"))
            off_a = float(binding.get("rx_off_a", max_v))
            off_b = float(binding.get("rx_off_b", max_v))

            on_match = self._eval_condition(v, on_op, on_a, on_b)
            off_match = self._eval_condition(v, off_op, off_a, off_b)

            if on_match and not off_match:
                is_on = True
            elif off_match and not on_match:
                is_on = False
            else:
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

    def _rx_widgets(self):
        return [cfg for cfg in self.widgets_config if cfg.get("behavior") == "rx"]

    def _simulate_apply_to_cfg(self, cfg, value):
        try:
            v = float(value)
        except Exception:
            return
        self._update_widget_value(cfg, v, force=True)

    def simulate_selected_rx(self):
        cfg = self._get_selected_config()
        if not cfg or cfg.get("behavior") != "rx":
            QMessageBox.information(self, "RX Simulator", "Select an RX tool first.")
            return
        self._simulate_apply_to_cfg(cfg, self.spin_sim_value.value())

    def simulate_all_rx(self):
        rx_items = self._rx_widgets()
        if not rx_items:
            QMessageBox.information(self, "RX Simulator", "No RX tools available.")
            return
        value = float(self.spin_sim_value.value())
        for cfg in rx_items:
            self._simulate_apply_to_cfg(cfg, value)

    def _toggle_auto_sim(self, checked):
        self.act_sim_auto.blockSignals(True)
        self.act_sim_auto.setChecked(bool(checked))
        self.act_sim_auto.blockSignals(False)

        if checked:
            if self.mode == "edit":
                QMessageBox.information(self, "RX Simulator", "Switch to STANDBY or RUN mode to start auto simulation.")
                self.btn_sim_auto.blockSignals(True)
                self.btn_sim_auto.setChecked(False)
                self.btn_sim_auto.blockSignals(False)
                self.act_sim_auto.blockSignals(True)
                self.act_sim_auto.setChecked(False)
                self.act_sim_auto.blockSignals(False)
                return
            self._sim_phase = 0.0
            self._sim_timer.start()
            self.btn_sim_auto.setText("Auto Sim: ON")
        else:
            self._sim_timer.stop()
            self.btn_sim_auto.setText("Auto Sim: OFF")

    def _on_sim_timer(self):
        rx_items = self._rx_widgets()
        if not rx_items:
            return

        self._sim_phase += 0.25
        for idx, cfg in enumerate(rx_items):
            binding = cfg.get("binding", {})
            min_v = float(binding.get("min", 0.0))
            max_v = float(binding.get("max", 100.0))
            if max_v <= min_v:
                max_v = min_v + 1.0

            phase = self._sim_phase + (idx * 0.35)
            ratio = (math.sin(phase) + 1.0) * 0.5
            value = min_v + (max_v - min_v) * ratio
            self._simulate_apply_to_cfg(cfg, value)

    def _panel_data(self):
        return {
            "version": 2,
            "grid": {"rows": self.grid_rows, "cols": self.grid_cols},
            "mode": self.mode,
            "widgets": self.widgets_config,
        }

    def save_panel_to_file(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save User Panel", "", "User Panel (*.upp.json)")
        if not path:
            return
        try:
            save_panel_json(path, self._panel_data())
            QMessageBox.information(self, "Saved", "User panel saved successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Save failed:\n{e}")

    def load_panel_from_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load User Panel", "", "User Panel (*.upp.json)")
        if not path:
            return

        try:
            data = load_panel_json(path)
            self._load_panel_data(data)
            QMessageBox.information(self, "Loaded", "User panel loaded successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Load failed:\n{e}")

    def _load_panel_data(self, data):
        if not isinstance(data, dict):
            raise ValueError("Invalid panel file")

        self.grid_rows = int(data.get("grid", {}).get("rows", 12))
        self.grid_cols = int(data.get("grid", {}).get("cols", 12))
        self.widgets_config = list(data.get("widgets", []))
        for cfg in self.widgets_config:
            self._normalize_config(cfg)
        self.selected_widget_id = self.widgets_config[0].get("id") if self.widgets_config else None

        shape_count = sum(1 for c in self.widgets_config if str(c.get("widget_type", "")).startswith("shape_"))
        self._shape_counter = max(1, shape_count + 1)

        mode = data.get("mode", "edit")
        self.mode = mode if mode in ("edit", "standby", "run") else "edit"

        self.rebuild_grid()
        self.refresh_mode_ui()

    def save_package(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save User Panel Package",
            "",
            f"User Panel Package (*{PACKAGE_EXT})",
        )
        if not path:
            return

        if not hasattr(self.main_window, "get_db_file_paths_by_bus"):
            QMessageBox.warning(self, "Not Supported", "Main window does not support DB bundle export.")
            return

        try:
            db_paths = self.main_window.get_db_file_paths_by_bus()
            out_path = save_bundle(path, self._panel_data(), db_paths)
            QMessageBox.information(self, "Saved", f"Package saved:\n{out_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Package save failed:\n{e}")

    def load_package(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load User Panel Package",
            "",
            f"User Panel Package (*{PACKAGE_EXT})",
        )
        if not path:
            return

        if not hasattr(self.main_window, "replace_db_files_by_bus"):
            QMessageBox.warning(self, "Not Supported", "Main window does not support DB bundle import.")
            return

        try:
            panel_data, db_paths_by_bus = load_bundle(path)
            self.main_window.replace_db_files_by_bus(db_paths_by_bus)
            self._load_panel_data(panel_data)
            QMessageBox.information(self, "Loaded", "Package loaded successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Package load failed:\n{e}")
