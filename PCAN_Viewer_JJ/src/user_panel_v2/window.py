import copy
import json
import math
import time
import uuid
from PyQt5.QtCore import Qt, QTimer, QRect, pyqtSignal, QPoint
from PyQt5.QtGui import QColor, QKeySequence, QPainter, QPen
from PyQt5.QtWidgets import (
    QAction,
    QAbstractItemView,
    QApplication,
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
    QSizePolicy,
    QShortcut,
    QSpinBox,
    QSlider,
    QScrollArea,
    QRubberBand,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .config_dialog import WidgetConfigDialog
from .sequence import SequenceControl, validate_steps
from .mode_security import verify_edit_password
from .storage import PACKAGE_EXT, load_bundle, load_panel_json, save_bundle, save_panel_json
from .styles import TOOL_STYLE, lamp_style
from .properties import ToolProperties
from .binding import reconcile_binding, unpack_raw, matching_signal, bit_positions
from .packets import PacketRegistryDialog, PacketRuntime, find_packet, bind_packet, validate_tool, validate_packet


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
        c0 = QColor("#F8FAFC")
        c1 = QColor("#F4F7FB")

        for r in range(rows):
            for c in range(cols):
                x = int(round(c * cell_w))
                y = int(round(r * cell_h))
                x2 = int(round((c + 1) * cell_w))
                y2 = int(round((r + 1) * cell_h))
                p.fillRect(x, y, max(1, x2 - x), max(1, y2 - y), c0 if ((r + c) % 2 == 0) else c1)

        p.setPen(QPen(QColor("#E5EAF1"), 1))
        for r in range(rows + 1):
            y = int(round(r * cell_h))
            p.drawLine(0, y, w, y)
        for c in range(cols + 1):
            x = int(round(c * cell_w))
            p.drawLine(x, 0, x, h)

        p.end()


class UserPanelWindow(QWidget):
    request_tx_value = pyqtSignal(dict, float)
    HISTORY_LIMIT = 50

    def __init__(self, main_window, db_messages, parent=None, security_config=None):
        super().__init__(parent)
        self.main_window = main_window
        self.db_messages = db_messages
        self.security_config = security_config or {}

        self.setWindowTitle("User Panel")
        self.resize(1180, 760)

        self.grid_rows = 36
        self.grid_cols = 36
        self.grid_cell_size = 32
        self.mode = "edit"

        self.widgets_config = []
        self.tx_packets = []
        self.init_steps = []
        self._init_running = False
        self._paused_packets = set()
        self._packet_runtimes = {}
        self.widget_frames = {}
        self.widget_controls = {}
        self.widget_child_hosts = {}
        self.selected_widget_id = None
        self.selected_widget_ids = set()
        self.channel_settings = {}
        self._undo_stack = []
        self._redo_stack = []
        self._history_current = None
        self._history_suspended = False
        self.latest_raw_by_msg = {}
        self.latest_value_by_signal = {}
        self._tool_list_syncing = False
        self._frame_timers = {}
        self.draw_mode = None
        self.draw_start_cell = None
        self._shape_counter = 1
        self._drag_target_id = None
        self._drag_start_global = None
        self._drag_offset_global = None
        self._drag_origin_cell = None
        self._drag_origin_span = None
        self._drag_origin_parent = None
        self._drag_resize_mode = False
        self._drag_preview_band = None
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
        self._reset_history()

    def _build_ui(self):
        root = QVBoxLayout(self)
        self.setFocusPolicy(Qt.StrongFocus)

        self.menu_bar = QMenuBar(self)
        root.addWidget(self.menu_bar)

        self.btn_mode_edit = QPushButton("Mode: EDIT")
        self.btn_mode_standby = QPushButton("Mode: STANDARD")
        self.btn_mode_run = QPushButton("Mode: RUN")
        self.btn_mode_edit.clicked.connect(lambda: self.set_mode("edit"))
        self.btn_mode_standby.clicked.connect(lambda: self.set_mode("standby"))
        self.btn_mode_run.clicked.connect(lambda: self.set_mode("run"))

        self.btn_add_tx = QPushButton("Add TX Tool")
        self.btn_packets = QPushButton("TX 패킷 등록 / 관리")
        self.btn_packets.clicked.connect(self.manage_tx_packets)
        self.btn_init = QPushButton('RUN Init 시퀀스 설정')
        self.btn_init.clicked.connect(self.edit_init_sequence)
        self.btn_add_rx = QPushButton("Add RX Tool")
        self.btn_add_misc = QPushButton("Add Group/Shape")

        self.btn_add_tx.clicked.connect(lambda: self.add_widget("tx"))
        self.btn_add_rx.clicked.connect(lambda: self.add_widget("rx"))
        self.btn_add_misc.clicked.connect(lambda: self.add_widget("none"))

        controls = QHBoxLayout()
        controls.addWidget(self.btn_mode_edit)
        controls.addWidget(self.btn_mode_standby)
        controls.addWidget(self.btn_mode_run)
        controls.addStretch()
        root.addLayout(controls)
        controls = QHBoxLayout()
        controls.addWidget(self.btn_packets)
        controls.addWidget(self.btn_init)
        controls.addWidget(self.btn_add_tx)
        controls.addWidget(self.btn_add_rx)
        controls.addWidget(self.btn_add_misc)
        controls.addStretch()
        root.addLayout(controls)

        self._setup_menu_actions()

        self.label_mode = QLabel()
        self.label_mode.setWordWrap(True)
        root.addWidget(self.label_mode)
        self.init_control = SequenceControl(self, dict(title='RUN Init', is_init=True, binding={}))
        self.init_control.setMaximumHeight(150)
        self.init_control.button.setEnabled(False)
        self.init_control.finished.connect(self._init_finished)
        self.init_control.hide()
        root.addWidget(self.init_control)

        self.label_key_help = QLabel(
            "Move: Arrow keys | Resize: Shift+Arrow | Delete: Del | Undo: Ctrl+Z | Redo: Ctrl+Y (50 steps) | EDIT only"
        )
        self.label_key_help.setStyleSheet("color:#555;")
        self.label_key_help.setWordWrap(True)
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
        self.list_tools.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_tools.itemSelectionChanged.connect(self._on_tool_list_selection_changed)
        self.list_tools.itemDoubleClicked.connect(self._on_tool_list_double_clicked)
        self.list_tools.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_tools.customContextMenuRequested.connect(self._show_tool_context_menu)
        left_lay.addWidget(self.list_tools)

        geom_box = QGroupBox("Selected Tool Geometry", left)
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

        geom_box.hide()  # Geometry is edited in the right-hand property inspector.

        sim_box = QGroupBox("RX Simulator (No CAN)")
        sim_layout = QVBoxLayout(sim_box)
        sim_row = QHBoxLayout()
        self.spin_sim_value = QDoubleSpinBox()
        self.spin_sim_value.setDecimals(3)
        self.spin_sim_value.setRange(-1000000.0, 1000000.0)
        self.spin_sim_value.setValue(1.0)
        self.spin_sim_value.setToolTip("Manual RX simulator value. Displays up to 3 decimals; integers are shown without trailing .000.")
        self.btn_sim_selected = QPushButton("Apply Selected RX")
        self.btn_sim_all = QPushButton("Apply All RX")
        self.btn_sim_auto = QPushButton("Auto Sim: OFF")
        self.btn_sim_auto.setCheckable(True)
        self.label_sim_help = QLabel(
            "Value is the manual RX simulator input. Apply Selected / Apply All updates RX tools without CAN; Auto Sim uses the same value range while running."
        )
        self.label_sim_help.setWordWrap(True)
        self.label_sim_help.setStyleSheet("color:#555;")

        self.btn_sim_selected.clicked.connect(self.simulate_selected_rx)
        self.btn_sim_all.clicked.connect(self.simulate_all_rx)
        self.btn_sim_auto.toggled.connect(self._toggle_auto_sim)

        sim_row.addWidget(QLabel("Value"))
        sim_row.addWidget(self.spin_sim_value)
        sim_layout.addLayout(sim_row)
        sim_layout.addWidget(self.label_sim_help)
        sim_layout.addWidget(self.btn_sim_selected)
        sim_layout.addWidget(self.btn_sim_all)
        sim_layout.addWidget(self.btn_sim_auto)
        left_lay.addWidget(sim_box)

        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)

        self.canvas = GridCanvas(self)
        self.canvas.setFocusPolicy(Qt.StrongFocus)
        self._setup_shortcuts()
        self.canvas_layout = QGridLayout(self.canvas)
        # Keep canvas grid and widget placement perfectly aligned to cell borders.
        self.canvas_layout.setContentsMargins(0, 0, 0, 0)
        self.canvas_layout.setHorizontalSpacing(0)
        self.canvas_layout.setVerticalSpacing(0)
        self._sync_canvas_size()
        self.canvas.mousePressEvent = self._on_canvas_mouse_press
        self.canvas.mouseReleaseEvent = self._on_canvas_mouse_release

        self.canvas_scroll = QScrollArea()
        self.canvas_scroll.setWidgetResizable(True)
        self.canvas_scroll.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.canvas_scroll.setWidget(self.canvas)
        right_lay.addWidget(self.canvas_scroll)

        split.addWidget(left)
        split.addWidget(right)
        self.properties = ToolProperties(self)
        split.addWidget(self.properties)
        split.setStretchFactor(1, 1)
        split.setSizes([210, 630, 340])

        root.addWidget(split, 1)

        self._sync_geom_editor_from_selection()

    def _setup_menu_actions(self):
        menu_file = self.menu_bar.addMenu("File")
        menu_edit = self.menu_bar.addMenu("Edit")
        self.act_undo = QAction("Undo", self)
        self.act_redo = QAction("Redo", self)
        self.act_undo.setShortcut(QKeySequence("Ctrl+Z"))
        self.act_redo.setShortcut(QKeySequence("Ctrl+Y"))
        self.act_undo.triggered.connect(self.undo_edit)
        self.act_redo.triggered.connect(self.redo_edit)
        menu_edit.addAction(self.act_undo)
        menu_edit.addAction(self.act_redo)
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
            sc = QShortcut(QKeySequence(keyseq), self.canvas)
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
        delete_from_list = QShortcut(QKeySequence(Qt.Key_Delete), self.list_tools)
        delete_from_list.setContext(Qt.WidgetWithChildrenShortcut)
        delete_from_list.activated.connect(self.delete_selected_widget)
        self._shortcuts.append(delete_from_list)

    def manage_tx_packets(self):
        if self.mode != 'edit':
            return
        dialog = PacketRegistryDialog(self)
        if dialog.exec_() != dialog.Accepted:
            return
        configs = copy.deepcopy(self.widgets_config)
        init_steps = copy.deepcopy(self.init_steps)
        try:
            validate_tool(dialog.packets, dict(behavior='tx', widget_type='sequence', binding=dict(sequence_steps=init_steps)))
            for cfg in configs:
                validate_tool(dialog.packets, cfg)
        except ValueError as exc:
            QMessageBox.warning(self, 'TX 패킷', str(exc))
            return
        self.tx_packets = dialog.packets
        self.widgets_config = configs
        self.init_steps = init_steps
        self._packet_runtimes.clear()
        self.rebuild_grid()
        self.properties.refresh(force=True)

    def edit_init_sequence(self):
        if self.mode != 'edit':
            return
        from .sequence_dialog import SequenceDialog
        dialog = SequenceDialog(self.db_messages, self.init_steps, self, self.tx_packets,
                                actions_only=True, allow_empty=True, allow_failure=False)
        dialog.setWindowTitle('RUN Init 시퀀스 (비우면 사용 안함)')
        if dialog.exec_() == dialog.Accepted:
            self.init_steps = copy.deepcopy(dialog.steps)
            if not self.init_steps:
                self.init_control.hide()
            self._record_history()

    def _init_finished(self, success):
        if not self._init_running:
            return
        self._init_running = False
        if not success:
            self.mode = 'standby'
            self.refresh_mode_ui()
            self.label_mode.setText('Init NG / 중단: STANDARD로 전환했습니다. 로그를 확인하세요.')
            return
        self.label_mode.setText('RUN: Init OK · 정지 지정되지 않은 등록 패킷 주기 전송')
        self._set_init_tool_state()
        self._sync_frame_timers_from_configs()

    def _set_init_tool_state(self):
        for cfg in self.widgets_config:
            if cfg.get('behavior') == 'tx':
                ctrl = self.widget_controls.get(cfg.get('id'))
                if ctrl:
                    ctrl.setEnabled(not self._init_running)

    def set_packet_transmission(self, packet_id, enabled):
        if self.mode != 'run':
            raise ValueError('RUN에서만 주기 전송을 제어할 수 있습니다.')
        targets = {p['packet_id'] for p in self.tx_packets}
        if packet_id != '*':
            if packet_id not in targets:
                raise ValueError('시작/정지 대상 패킷이 등록되어 있지 않습니다.')
            targets = {packet_id}
        if enabled:
            self._paused_packets.difference_update(targets)
        else:
            self._paused_packets.update(targets)
            for target in targets:
                timer = self._frame_timers.pop(target, None)
                if timer:
                    timer.stop()
                    timer.deleteLater()
        self._sync_frame_timers_from_configs()

    def _report_packet_error(self, exc):
        self.label_mode.setText(f'TX 패킷 오류: {exc}')
        if hasattr(self.main_window, 'statusBar'):
            self.main_window.statusBar().showMessage(f'User panel TX: {exc}', 6000)

    def _prepare_registered_packets(self):
        validate_steps(self.init_steps, actions_only=True, allow_empty=True)
        validate_tool(self.tx_packets, dict(behavior='tx', widget_type='sequence', binding=dict(sequence_steps=self.init_steps)))
        for cfg in self.widgets_config:
            validate_tool(self.tx_packets, cfg)
        runtimes = {}
        keys = set()
        for p in self.tx_packets:
            validate_packet(p, self.db_messages)
            key = (p['bus'], p['id'])
            if key in keys or not 0 <= int(p.get('cycle', -1)) <= 600000:
                raise ValueError('등록 패킷의 BUS/ID 중복 또는 딜레이 설정을 확인하세요.')
            keys.add(key)
            runtimes[p['packet_id']] = PacketRuntime(p, self.db_messages, self.main_window)
        # Initialize from the displayed tool values before the first periodic send.
        def is_checked_toggle(cfg):
            ctrl = self.widget_controls.get(cfg.get('id'))
            return cfg.get('widget_type') == 'toggle' and ctrl is not None and ctrl.isChecked()
        for cfg in sorted(self.widgets_config, key=is_checked_toggle):
            if cfg.get('behavior') != 'tx' or cfg.get('widget_type') == 'sequence':
                continue
            binding = cfg['binding']
            ctrl = self.widget_controls.get(cfg['id'])
            kind = cfg.get('widget_type')
            if kind == 'slider':
                slider = ctrl.findChild(QSlider) if ctrl else None
                low, high = binding.get('min', 0), binding.get('max', 100)
                value = low + (high - low) * slider.value() / max(1, slider.maximum()) if slider else binding.get('tx_initial_value', low)
            elif kind == 'spinbox':
                value = ctrl.value() if ctrl else binding.get('min', 0)
            elif kind == 'toggle':
                value = binding.get('tx_on_value', 1) if ctrl and ctrl.isChecked() else binding.get('tx_off_value', 0)
            elif kind == 'button':
                value = binding.get('tx_release_value', binding.get('min', 0))
            else:
                continue
            runtimes[binding['packet_id']].stage(binding, value)
        self._packet_runtimes = runtimes

    def set_mode(self, new_mode):
        if new_mode == 'standard':
            new_mode = 'standby'
        if new_mode == self.mode:
            return

        if new_mode == "edit" and self.mode != "edit":
            enabled = bool(self.security_config.get("enabled", False))
            password = str(self.security_config.get("password", ""))
            if not verify_edit_password(self, enabled, password):
                QMessageBox.warning(self, "Denied", "Invalid password for EDIT mode.")
                return

        self.stop_panel_commands("모드 변경")
        if new_mode == 'run':
            try:
                self._prepare_registered_packets()
            except ValueError as exc:
                QMessageBox.warning(self, 'TX 패킷', str(exc))
                return
        self.mode = new_mode
        if new_mode == 'run':
            self._paused_packets.clear()
            self._init_running = bool(self.init_steps)
            self.init_control.setVisible(bool(self.init_steps))
        self.refresh_mode_ui()
        if new_mode == 'run' and self.init_steps:
            self.init_control.cfg['binding'] = dict(sequence_steps=copy.deepcopy(self.init_steps))
            self.init_control.show()
            self.label_mode.setText('RUN: Init 실행 중 · 등록 패킷 주기 전송 대기')
            self.init_control.toggle()

    def stop_panel_commands(self, reason="패널 정지"):
        self._init_running = False
        if hasattr(self, 'init_control'):
            self.init_control.stop(reason)
        self._stop_all_frame_timers()
        for ctrl in self.widget_controls.values():
            if isinstance(ctrl, SequenceControl):
                ctrl.stop(reason)
            for timer in ctrl.findChildren(QTimer, "panel_hold_timer"):
                timer.stop()
                timer.deleteLater()

    def closeEvent(self, event):
        self.stop_panel_commands("패널 닫힘")
        self._sim_timer.stop()
        self.mode = "standby"
        super().closeEvent(event)

    def on_sequence_receive(self, ts, bus, can_id, data, extended, fd, brs=False):
        if self.mode == "run" and self.isVisible():
            for ctrl in self.widget_controls.values():
                if isinstance(ctrl, SequenceControl):
                    ctrl.receive(ts, bus, can_id, data, extended, fd, brs)

    def refresh_mode_ui(self):
        is_edit = self.mode == "edit"
        if self.mode != "run":
            self.stop_panel_commands("패널 상태 변경")
        self.label_mode.setText(
            "EDIT: create/delete/arrange tools"
            if self.mode == "edit"
            else ("STANDARD: RX 갱신 / 모든 TX 정지" if self.mode == "standby" else "RUN: 등록 패킷 주기 전송 / 딜레이 0은 도구 값 변경 시 전송")
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
        self.btn_packets.setEnabled(is_edit)
        self.btn_init.setEnabled(is_edit)
        self._set_init_tool_state()

        self.act_sim_auto.blockSignals(True)
        self.act_sim_auto.setChecked(self.btn_sim_auto.isChecked())
        self.act_sim_auto.blockSignals(False)

        # RUN/STANDBY 모드에서는 위젯 선택 기능을 비활성화합니다.
        if not is_edit:
            self._cancel_draw_mode(refresh=False)
            self.selected_widget_id = None
            self.selected_widget_ids.clear()
            self.list_tools.clearSelection()

        self.list_tools.setEnabled(is_edit)
        self._refresh_selection_ui()

        self._sync_frame_timers_from_configs()
        self._refresh_history_actions()

    def _history_snapshot(self):
        return dict(widgets=copy.deepcopy(self.widgets_config),
                    tx_packets=copy.deepcopy(self.tx_packets),
                    init_steps=copy.deepcopy(self.init_steps),
                    selected=self.selected_widget_id, ids=set(self.selected_widget_ids))

    def _reset_history(self):
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._history_current = self._history_snapshot()
        self._refresh_history_actions()

    def _refresh_history_actions(self):
        if not hasattr(self, "act_undo"):
            return
        self.act_undo.setEnabled(self.mode == "edit" and bool(self._undo_stack))
        self.act_redo.setEnabled(self.mode == "edit" and bool(self._redo_stack))
        self.act_undo.setText(f"Undo ({len(self._undo_stack)})")
        self.act_redo.setText(f"Redo ({len(self._redo_stack)})")

    def _record_history(self):
        if self._history_suspended:
            return
        current = self._history_snapshot()
        if self._history_current is not None and current["widgets"] != self._history_current["widgets"]:
            self._undo_stack.append(self._history_current)
            del self._undo_stack[:-self.HISTORY_LIMIT]
            self._redo_stack.clear()
        self._history_current = current
        self._refresh_history_actions()

    def _restore_history(self, source, destination):
        if self.mode != "edit" or not source or self._history_suspended:
            return
        destination.append(self._history_snapshot())
        state = source.pop()
        self._history_suspended = True
        try:
            self._cancel_draw_mode(refresh=False)
            self._drag_target_id = None
            self.widgets_config = copy.deepcopy(state["widgets"])
            self.tx_packets = copy.deepcopy(state.get('tx_packets', []))
            self.init_steps = copy.deepcopy(state.get('init_steps', []))
            for cfg in self.widgets_config:
                reconcile_binding(self.db_messages, cfg.get("binding", {}))
            self.selected_widget_id = state["selected"]
            self.selected_widget_ids = set(state["ids"])
            self.rebuild_grid()
        finally:
            self._history_suspended = False
        self._history_current = self._history_snapshot()
        self._refresh_history_actions()

    def undo_edit(self):
        self._restore_history(self._undo_stack, self._redo_stack)

    def redo_edit(self):
        self._restore_history(self._redo_stack, self._undo_stack)

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
        col = self._cell_index_from_coord(x, self.canvas.width(), self.grid_cols)
        row = self._cell_index_from_coord(y, self.canvas.height(), self.grid_rows)
        return row, col

    def _cell_index_from_coord(self, coord, size, count):
        size = max(1, int(size))
        count = max(1, int(count))
        c = max(0, min(size - 1, int(coord)))

        for i in range(count):
            end = int(round((i + 1) * size / float(count)))
            if c < end:
                return i
        return count - 1

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
        if behavior == 'tx' and not self.tx_packets:
            QMessageBox.information(self, 'TX 패킷', '먼저 TX 패킷 등록 / 관리에서 패킷을 등록하세요.')
            return
        dlg = WidgetConfigDialog(
            self.db_messages,
            self,
            fixed_behavior=behavior,
            parent_candidates=self._group_parent_candidates(),
            live_preview_default=False,
            grid_rows=self.grid_rows,
            grid_cols=self.grid_cols,
            tx_packets=self.tx_packets,
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
        self._history_suspended = True
        try:
            result = dlg.exec_()
        finally:
            self._history_suspended = False
        if result != dlg.Accepted:
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

        if self.mode != "edit":
            return
        self.properties.refresh(force=True)
        self.properties.show()
        self.properties.setFocus()

    def refresh_dbc_bindings(self):
        for cfg in self.widgets_config:
            reconcile_binding(self.db_messages, cfg.get("binding", {}))
        self.properties.refresh(force=True)
        self._history_current = self._history_snapshot()

    def delete_selected_widget(self):
        if self.mode != "edit":
            return
        cfg = self._get_selected_config()
        if not cfg:
            QMessageBox.information(self, "Info", "Select a widget first.")
            return

        ids = {c["id"] for c in self.selected_configs()}
        self.widgets_config = [x for x in self.widgets_config if x.get("id") not in ids]
        for item in self.widgets_config:
            if item.get("parent_id") in ids:
                item["parent_id"] = None
        self.selected_widget_id = None
        self.selected_widget_ids.clear()
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

    def selected_configs(self):
        ids = self.selected_widget_ids & {c["id"] for c in self.widgets_config}
        if self.selected_widget_id and self.selected_widget_id not in ids:
            ids = {self.selected_widget_id}
        if not self.selected_widget_id:
            ids = set()
        self.selected_widget_ids = ids
        return [c for c in self.widgets_config if c["id"] in ids]

    def _normalize_config(self, cfg):
        cfg.setdefault("id", str(uuid.uuid4()))
        cfg.setdefault("widget_type", "label")
        cfg.setdefault("title", "Widget")
        cfg.setdefault("title_align", "center")
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
        binding.pop("tx_cycle_mode", None)
        binding.pop("tx_cycle_ms", None)
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

        wtype = cfg.get("widget_type", "label")
        min_row_span = 1 if wtype == "shape_line" else 2
        min_col_span = 1 if wtype == "shape_line" else 4

        cfg["row"] = max(0, min(self.grid_rows - 1, int(cfg.get("row", 0))))
        cfg["col"] = max(0, min(self.grid_cols - 1, int(cfg.get("col", 0))))
        cfg["row_span"] = max(min_row_span, min(self.grid_rows, int(cfg.get("row_span", 1))))
        cfg["col_span"] = max(min_col_span, min(self.grid_cols, int(cfg.get("col_span", 1))))

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
            it.setSelected(wid in self.selected_widget_ids)
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
                col = self._cell_index_from_coord(x, host_widget.width(), self.grid_cols)
                row = self._cell_index_from_coord(y, host_widget.height(), self.grid_rows)
                return row, col

        local = self.canvas.mapFromGlobal(global_pos)
        x = max(0, min(max(0, self.canvas.width() - 1), int(local.x())))
        y = max(0, min(max(0, self.canvas.height() - 1), int(local.y())))
        col = self._cell_index_from_coord(x, self.canvas.width(), self.grid_cols)
        row = self._cell_index_from_coord(y, self.canvas.height(), self.grid_rows)
        return row, col

    def _on_tool_list_selection_changed(self, *_args):
        if self._tool_list_syncing:
            return
        items = self.list_tools.selectedItems()
        self.selected_widget_ids = {i.data(Qt.UserRole) for i in items}
        current = self.list_tools.currentItem()
        self.selected_widget_id = (current.data(Qt.UserRole) if current and current.isSelected()
                                   else (items[-1].data(Qt.UserRole) if items else None))
        self._refresh_selection_ui()

    def _on_tool_list_double_clicked(self, item):
        if item is None:
            return
        wid = item.data(Qt.UserRole)
        target = item.data(Qt.UserRole + 1)
        if not wid or not target:
            self.edit_selected_widget()
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

            self.spin_sel_row.setRange(0, self.grid_rows - 1)
            self.spin_sel_col.setRange(0, self.grid_cols - 1)

            if not cfg:
                # 선택된 위젯이 없을 경우: 기본 최소값으로 범위를 설정하고 값을 초기화합니다.
                self.spin_sel_row_span.setRange(2, self.grid_rows)
                self.spin_sel_col_span.setRange(4, self.grid_cols)
                self.spin_sel_row.setValue(0)
                self.spin_sel_col.setValue(0)
                self.spin_sel_row_span.setValue(2)
                self.spin_sel_col_span.setValue(4)
                return

            # 선택된 위젯이 있을 경우: 위젯 타입에 맞는 최소 크기 제약을 적용합니다.
            wtype = cfg.get("widget_type")
            min_row_span = 1 if wtype == "shape_line" else 2
            min_col_span = 1 if wtype == "shape_line" else 4

            self.spin_sel_row_span.setRange(min_row_span, self.grid_rows)
            self.spin_sel_col_span.setRange(min_col_span, self.grid_cols)

            self.spin_sel_row.setValue(max(0, min(self.grid_rows - 1, int(cfg.get("row", 0)))))
            self.spin_sel_col.setValue(max(0, min(self.grid_cols - 1, int(cfg.get("col", 0)))))
            self.spin_sel_row_span.setValue(max(min_row_span, min(self.grid_rows, int(cfg.get("row_span", 1)))))
            self.spin_sel_col_span.setValue(max(min_col_span, min(self.grid_cols, int(cfg.get("col_span", 1)))))
        finally:
            self._prop_syncing = False

    def _show_tool_context_menu(self, pos):
        item = self.list_tools.itemAt(pos)
        if item is not None:
            self.selected_widget_id = item.data(Qt.UserRole)
            if self.selected_widget_id not in self.selected_widget_ids:
                self.selected_widget_ids = {self.selected_widget_id}
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

    def _sync_canvas_size(self):
        self.canvas.setMinimumSize(
            self.grid_cols * self.grid_cell_size,
            self.grid_rows * self.grid_cell_size,
        )
        # Clear obsolete tracks when loading a panel with fewer rows/columns.
        for r in range(max(self.grid_rows, self.canvas_layout.rowCount())):
            self.canvas_layout.setRowStretch(r, 1 if r < self.grid_rows else 0)
            self.canvas_layout.setRowMinimumHeight(r, self.grid_cell_size if r < self.grid_rows else 0)
        for c in range(max(self.grid_cols, self.canvas_layout.columnCount())):
            self.canvas_layout.setColumnStretch(c, 1 if c < self.grid_cols else 0)
            self.canvas_layout.setColumnMinimumWidth(c, self.grid_cell_size if c < self.grid_cols else 0)

    def rebuild_grid(self):
        self.stop_panel_commands("패널 도구 갱신")
        while self.canvas_layout.count():
            item = self.canvas_layout.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()

        self.widget_frames.clear()
        self.widget_controls.clear()
        self.widget_child_hosts.clear()
        self._hide_drag_preview()
        self._sync_canvas_size()

        sorted_cfg = sorted(self.widgets_config, key=lambda c: int(c.get("z_index", 0)))

        for cfg in sorted_cfg:
            frame = QFrame()
            frame.setFrameShape(QFrame.StyledPanel)
            frame.setObjectName(cfg.get("id"))
            frame.setProperty("panelCard", True)
            frame.setStyleSheet(TOOL_STYLE)

            frame_layout = QVBoxLayout(frame)
            frame_layout.setContentsMargins(6, 6, 6, 6)
            frame_layout.setSpacing(4)

            wtype = cfg.get("widget_type")
            title_widget_for_binding = None

            # group_box와 tab_container는 자체적으로 제목을 표시하므로,
            # 중복되는 외부 라벨을 생성하지 않습니다.
            if wtype not in ("group_box", "tab_container"):
                behavior = str(cfg.get("behavior", "none")).upper()
                title = QLabel(f"[{behavior}] {cfg.get('title', 'Widget')}")
                title.setProperty("panelTitle", True)
                # 라벨이 수직으로 늘어나는 것을 방지하고 컨트롤 위젯이 공간을 차지하도록 합니다.
                title.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
                title_align_str = str(cfg.get("title_align", "center")).lower()
                if title_align_str == "left":
                    align_flag = Qt.AlignLeft | Qt.AlignVCenter
                elif title_align_str == "right":
                    align_flag = Qt.AlignRight | Qt.AlignVCenter
                else:
                    align_flag = Qt.AlignCenter
                title.setAlignment(align_flag)
                frame_layout.addWidget(title)
                title_widget_for_binding = title

            ctrl, child_host = self._create_runtime_widget(cfg)
            # Stretch factor 1 allows the control to expand and fill available vertical space.
            frame_layout.addWidget(ctrl, 1)

            wid = cfg.get("id")
            self.widget_frames[wid] = frame
            self.widget_controls[wid] = ctrl
            self.widget_child_hosts[wid] = child_host

            self._bind_select(frame, wid)
            if title_widget_for_binding:
                self._bind_select(title_widget_for_binding, wid)

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
        self._record_history()

    def _bind_select(self, widget, widget_id):
        widget.setMouseTracking(True)

        def _update_cursor(event):
            if self.mode != "edit" or self.draw_mode is not None:
                widget.unsetCursor()
                return

            cfg = self._get_selected_config()
            if not cfg or cfg.get("id") != widget_id:
                widget.setCursor(Qt.ArrowCursor)
                return

            local = event.pos() if event is not None else None
            if local is None:
                widget.setCursor(Qt.ArrowCursor)
                return

            if local.x() >= (max(1, widget.width()) - 16) and local.y() >= (max(1, widget.height()) - 16):
                widget.setCursor(Qt.SizeFDiagCursor)
            else:
                widget.setCursor(Qt.OpenHandCursor)

        def _on_press(event):
            # RUN/STANDBY 모드에서는 위젯을 클릭해도 선택되지 않습니다.
            if self.mode != "edit":
                return
            self.canvas.setFocus()

            if event is not None and event.modifiers() & Qt.ControlModifier:
                ids = {c["id"] for c in self.selected_configs()}
                if widget_id in ids:
                    ids.remove(widget_id)
                else:
                    ids.add(widget_id)
                self.selected_widget_ids = ids
                self.selected_widget_id = widget_id if widget_id in ids else next(iter(ids), None)
                self._refresh_selection_ui()
                return
            self.selected_widget_ids = {widget_id}
            self.selected_widget_id = widget_id
            self._refresh_selection_ui()

            if self.draw_mode is None and event is not None and event.button() == Qt.LeftButton:
                try:
                    self._drag_target_id = widget_id
                    self._drag_start_global = event.globalPos()

                    # 드래그 대상인 전체 프레임(widget_frames[widget_id])을 기준으로 오프셋을 계산합니다.
                    # 이렇게 하면 제목 라벨이나 다른 내부 위젯 중 어느 것을 클릭해도
                    # 항상 전체 프레임의 좌상단을 기준으로 상대 위치가 유지됩니다.
                    frame_widget = self.widget_frames.get(widget_id)
                    self._drag_offset_global = event.globalPos() - frame_widget.mapToGlobal(QPoint(0, 0))
                    self._drag_origin_parent = self._get_selected_config().get("parent_id") if self._get_selected_config() else None
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
                    self._drag_offset_global = None
                    self._drag_origin_cell = None
                    self._drag_origin_span = None
                    self._drag_resize_mode = False

        def _on_move(event):
            _update_cursor(event)
            if self.mode != "edit" or self.draw_mode is not None:
                return
            if self._drag_target_id != widget_id:
                return
            if self._drag_start_global is None or event is None:
                return
            if not (event.buttons() & Qt.LeftButton):
                return

            cfg = self._get_selected_config()
            if not cfg:
                return

            end_pos = event.globalPos()

            if self._drag_resize_mode:
                parent_id = cfg.get("parent_id")
                r_end, c_end = self._cell_from_global_in_parent(parent_id, end_pos)
                r_start = int(cfg.get("row", 0))
                c_start = int(cfg.get("col", 0))
                preview_row_span = max(1, r_end - r_start + 1)
                preview_col_span = max(1, c_end - c_start + 1)
                self._show_drag_preview(cfg, preview_row_span, preview_col_span, resize_mode=True)
            else:
                new_parent = self._hit_group_parent_from_global(end_pos, exclude_id=widget_id)
                # 위젯의 좌상단이 위치할 목표 지점을 오프셋을 적용하여 계산합니다.
                adjusted_pos = end_pos
                if self._drag_offset_global:
                    adjusted_pos -= self._drag_offset_global
                preview_row, preview_col = self._cell_from_global_in_parent(new_parent, adjusted_pos)
                self._show_drag_preview(cfg, preview_row, preview_col, parent_id=new_parent, resize_mode=False)

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

                # 마우스가 거의 움직이지 않았다면(클릭), 드래그로 처리하지 않고 종료합니다.
                if (end_pos - self._drag_start_global).manhattanLength() < QApplication.startDragDistance():
                    return

                cfg = self._get_selected_config()
                if not cfg:
                    return

                if self._drag_resize_mode:
                    parent_id = cfg.get("parent_id")
                    r_end, c_end = self._cell_from_global_in_parent(parent_id, end_pos)
                    r_start = int(cfg.get("row", 0))
                    c_start = int(cfg.get("col", 0))

                    wtype = cfg.get("widget_type")
                    min_row_span = 1 if wtype == "shape_line" else 2
                    min_col_span = 1 if wtype == "shape_line" else 4
                    cfg["row_span"] = max(min_row_span, r_end - r_start + 1)
                    cfg["col_span"] = max(min_col_span, c_end - c_start + 1)
                    self.rebuild_grid()
                else:
                    new_parent = self._hit_group_parent_from_global(end_pos, exclude_id=widget_id)
                    # 최종 위치를 오프셋을 적용하여 계산합니다.
                    adjusted_pos = end_pos
                    if self._drag_offset_global:
                        adjusted_pos -= self._drag_offset_global
                    row_new, col_new = self._cell_from_global_in_parent(new_parent, adjusted_pos)

                    cfg["parent_id"] = new_parent
                    cfg["row"] = row_new
                    cfg["col"] = col_new
                    self.rebuild_grid()
            finally:
                self._drag_target_id = None
                self._drag_start_global = None
                self._drag_offset_global = None
                self._drag_origin_cell = None
                self._drag_origin_span = None
                self._drag_origin_parent = None
                self._drag_resize_mode = False
                self._hide_drag_preview()

        widget.mousePressEvent = _on_press
        widget.mouseMoveEvent = _on_move
        widget.mouseReleaseEvent = _on_release

    def _refresh_selection_ui(self):
        ids = {c["id"] for c in self.selected_configs()}
        for wid, frame in self.widget_frames.items():
            selected = wid in ids
            frame.setProperty("selected", selected)
            frame.style().unpolish(frame)
            frame.style().polish(frame)
            frame.update()

        self._tool_list_syncing = True
        for i in range(self.list_tools.count()):
            it = self.list_tools.item(i)
            it.setSelected(it.data(Qt.UserRole) in ids)
        self._tool_list_syncing = False

        self._sync_geom_editor_from_selection()
        if hasattr(self, "properties"):
            self.properties.refresh()
        if self._history_current is not None and self._history_current["widgets"] == self.widgets_config:
            self._history_current["selected"] = self.selected_widget_id
            self._history_current["ids"] = set(self.selected_widget_ids)

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

        if wtype == "sequence":
            return SequenceControl(self, cfg), None

        if wtype == "button":
            btn = QPushButton("Send")
            btn.setProperty("panelPrimary", True)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            push_value = float(binding.get("tx_press_value", max_v))
            pull_value = float(binding.get("tx_release_value", min_v))
            def _pressed():
                if self.mode != "run":
                    return
                self._emit_tx(cfg, push_value)

            def _released():
                self._emit_tx(cfg, pull_value)

            btn.pressed.connect(_pressed)
            btn.released.connect(_released)
            return btn, None

        if wtype == "toggle":
            btn = QPushButton("OFF")
            btn.setCheckable(True)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            on_value = float(binding.get("tx_on_value", max_v))
            off_value = float(binding.get("tx_off_value", min_v))

            def _toggle(checked):
                btn.setText("ON" if checked else "OFF")
                if checked and behavior == "tx":
                    self._uncheck_signal_toggles(cfg)
                self._emit_tx(cfg, on_value if checked else off_value)

            btn.toggled.connect(_toggle)
            return btn, None

        if wtype == "slider":
            container = QWidget()
            lay = QGridLayout(container)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setHorizontalSpacing(6)
            lay.setVerticalSpacing(0)
            slider = QSlider(Qt.Horizontal)
            slider.setObjectName("slider")
            steps = self._slider_steps(binding, min_v, max_v)
            slider.setRange(0, steps)
            initial = max(min_v, min(max_v, float(binding.get("tx_initial_value", min_v))))
            initial_step = int(round((initial - min_v) / (max_v - min_v) * steps))
            slider.setValue(initial_step)
            initial = min_v + (max_v - min_v) * slider.value() / steps
            value_label = QLabel(self._format_slider_value(binding, initial))
            value_label.setObjectName("value_label")
            value_label.setAlignment(Qt.AlignCenter)
            lay.addWidget(slider, 0, 1)
            lay.addWidget(value_label, 1, 1)
            home = QPushButton("Home")
            home.setObjectName("slider_home")
            home.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            home.setToolTip("Return to Initial Value")
            lay.addWidget(home, 0, 0, 2, 1)
            lay.setColumnStretch(1, 1)
            lay.setRowStretch(0, 1)

            def _on_changed(v):
                ratio = 0.0 if steps <= 0 else (v / float(steps))
                phys = min_v + ((max_v - min_v) * ratio)
                value_label.setText(self._format_slider_value(binding, phys))
                if behavior == "tx":
                    self._emit_tx(cfg, phys)

            slider.valueChanged.connect(_on_changed)
            def _home():
                if slider.value() == initial_step:
                    _on_changed(initial_step)
                else:
                    slider.setValue(initial_step)
            home.clicked.connect(_home)
            return container, None

        if wtype == "spinbox":
            spin = QDoubleSpinBox()
            spin.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
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
            bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
            bar.setRange(0, 1000)
            bar.setValue(0)
            return bar, None

        if wtype == "status_lamp":
            lamp = QLabel("OFF")
            lamp.setAlignment(Qt.AlignCenter)
            lamp.setStyleSheet(lamp_style(False))
            return lamp, None

        if wtype == "group_box":
            grp = QGroupBox(cfg.get("title", "Group"))
            inner = QWidget()
            inner_layout = QGridLayout(inner)
            inner_layout.setContentsMargins(4, 4, 4, 4)
            inner_layout.setHorizontalSpacing(4)
            inner_layout.setVerticalSpacing(4)
            for r in range(self.grid_rows):
                inner_layout.setRowStretch(r, 1)
            for c in range(self.grid_cols):
                inner_layout.setColumnStretch(c, 1)
            grp_lay = QVBoxLayout(grp)
            grp_lay.setContentsMargins(6, 6, 6, 6)
            grp_lay.addWidget(inner, 1)
            return grp, inner_layout

        if wtype == "tab_container":
            tabs = QTabWidget()
            tab1 = QWidget()
            tab1_layout = QGridLayout(tab1)
            tab1_layout.setContentsMargins(4, 4, 4, 4)
            tab1_layout.setHorizontalSpacing(4)
            tab1_layout.setVerticalSpacing(4)
            for r in range(self.grid_rows):
                tab1_layout.setRowStretch(r, 1)
            for c in range(self.grid_cols):
                tab1_layout.setColumnStretch(c, 1)
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

        label = QLabel("-")
        label.setProperty("panelValue", True)
        label.setAlignment(Qt.AlignCenter)
        return label, None

    def _preview_parent_widget(self, cfg, parent_id=None):
        target_parent_id = cfg.get("parent_id") if parent_id is None else parent_id
        parent_id = target_parent_id
        if parent_id and parent_id in self.widget_child_hosts and self.widget_child_hosts[parent_id] is not None:
            host_layout = self.widget_child_hosts[parent_id]
            host_widget = host_layout.parentWidget()
            if host_widget is not None:
                return host_widget
        return self.canvas

    def _show_drag_preview(self, cfg, row_or_span, col_or_span, parent_id=None, resize_mode=False):
        parent_widget = self._preview_parent_widget(cfg, parent_id=parent_id)
        if parent_widget is None:
            return

        if resize_mode:
            row = int(cfg.get("row", 0))
            col = int(cfg.get("col", 0))
            row_span = int(row_or_span)
            col_span = int(col_or_span)
        else:
            row = int(row_or_span)
            col = int(col_or_span)
            row_span = max(1, int(cfg.get("row_span", 1)))
            col_span = max(1, int(cfg.get("col_span", 1)))

        parent_w = max(1, parent_widget.width())
        parent_h = max(1, parent_widget.height())
        cell_w = float(parent_w) / max(1, self.grid_cols)
        cell_h = float(parent_h) / max(1, self.grid_rows)
        x = int(round(col * cell_w))
        y = int(round(row * cell_h))
        x2 = int(round((col + col_span) * cell_w))
        y2 = int(round((row + row_span) * cell_h))
        w = max(1, x2 - x)
        h = max(1, y2 - y)

        if self._drag_preview_band is None or self._drag_preview_band.parent() is not parent_widget:
            self._hide_drag_preview()
            self._drag_preview_band = QRubberBand(QRubberBand.Rectangle, parent_widget)
            self._drag_preview_band.setStyleSheet("border: 2px dashed #0078D7; background: rgba(0,120,215,30);")

        self._drag_preview_band.setGeometry(QRect(x, y, w, h))
        self._drag_preview_band.show()
        self._drag_preview_band.raise_()

    def _hide_drag_preview(self):
        if self._drag_preview_band is not None:
            try:
                self._drag_preview_band.hide()
                self._drag_preview_band.deleteLater()
            except Exception:
                pass
            self._drag_preview_band = None

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

        wtype = cfg.get("widget_type")
        min_row_span = 1 if wtype == "shape_line" else 2
        min_col_span = 1 if wtype == "shape_line" else 4

        col_span = int(cfg.get("col_span", 1)) + int(dcol_span)
        row_span = int(cfg.get("row_span", 1)) + int(drow_span)
        cfg["col_span"] = max(min_col_span, min(self.grid_cols, col_span))
        cfg["row_span"] = max(min_row_span, min(self.grid_rows, row_span))
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
        ids, mapping, _ = self._collect_overlap_issue_lines()
        return ids, mapping

    def _collect_overlap_issue_lines(self):
        frames = {}
        ids, mapping, issues = set(), {}, []
        for cfg in self.widgets_config:
            if cfg.get("behavior") != "tx" or cfg.get("widget_type") == "sequence":
                continue
            binding = cfg.get("binding", {})
            key = self._frame_key_from_binding(binding)
            try:
                bits = set(bit_positions(binding, key[2]))
            except ValueError:
                continue
            frames.setdefault(key, []).append((cfg, bits))
        for key, items in frames.items():
            for index, (a, a_bits) in enumerate(items):
                for b, b_bits in items[index + 1:]:
                    shared = a_bits & b_bits
                    if shared:
                        ids.update((a["id"], b["id"]))
                        mapping.setdefault(a["id"], set()).add(b["id"])
                        mapping.setdefault(b["id"], set()).add(a["id"])
                        issues.append(f"Frame B{key[0]} 0x{key[1]:X} DLC {key[2]}: "
                                      f"{a.get('title', 'Widget')} <-> {b.get('title', 'Widget')} "
                                      f"(bits {', '.join(map(str, sorted(shared)))})")
        return ids, mapping, issues

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
        self._emit_tx(dict(behavior="tx", binding=binding), value)

    def _uncheck_signal_toggles(self, selected_cfg):
        def signal_key(binding):
            return (
                int(binding.get("bus", 1)),
                int(binding.get("can_id", 0)),
                int(binding.get("start_bit", 0)),
                int(binding.get("bit_length", 8)),
                str(binding.get("byte_order", "little_endian")),
            )

        selected_key = signal_key(selected_cfg.get("binding", {}))
        for cfg in self.widgets_config:
            if cfg.get("id") == selected_cfg.get("id"):
                continue
            if cfg.get("widget_type") != "toggle" or cfg.get("behavior") != "tx":
                continue
            if signal_key(cfg.get("binding", {})) != selected_key:
                continue
            ctrl = self.widget_controls.get(cfg.get("id"))
            if isinstance(ctrl, QPushButton) and ctrl.isCheckable():
                # Deselect visually without sending OFF over the selected ON value.
                was_blocked = ctrl.blockSignals(True)
                try:
                    ctrl.setChecked(False)
                    ctrl.setText("OFF")
                finally:
                    ctrl.blockSignals(was_blocked)

    def _emit_tx(self, cfg, value):
        if self.mode != "run" or self._init_running or not self.isVisible() or cfg.get("behavior") != "tx":
            return
        try:
            packet = find_packet(self.tx_packets, cfg.get("binding", {}))
            if packet is None:
                raise ValueError("Register the TX packet first.")
            runtime = self._packet_runtimes[packet['packet_id']]
            if runtime.stage(cfg['binding'], value) and packet['cycle'] == 0:
                runtime.send()
        except Exception as exc:
            self._report_packet_error(exc)

    def _frame_key_from_binding(self, binding):
        return (
            int(binding.get("bus", 1)),
            int(binding.get("can_id", 0)),
            max(1, min(64, int(binding.get("dlc", 8)))),
        )

    def _flush_frame(self, packet_id):
        if self.mode != "run" or self._init_running or packet_id in self._paused_packets or not self.isVisible():
            return
        try:
            self._packet_runtimes[packet_id].send()
        except Exception as exc:
            timer = self._frame_timers.pop(packet_id, None)
            if timer:
                timer.stop()
                timer.deleteLater()
            self._report_packet_error(exc)

    def _stop_all_frame_timers(self):
        for timer in self._frame_timers.values():
            try:
                timer.stop()
                timer.deleteLater()
            except Exception:
                pass
        self._frame_timers.clear()

    def _sync_frame_timers_from_configs(self):
        if self.mode != "run" or self._init_running:
            self._stop_all_frame_timers()
            return
        for packet in self.tx_packets:
            key = packet['packet_id']
            if packet['cycle'] <= 0 or key in self._paused_packets or key in self._frame_timers:
                continue
            timer = QTimer(self)
            timer.setTimerType(Qt.PreciseTimer)
            timer.setInterval(packet['cycle'])
            timer.timeout.connect(lambda key=key: self._flush_frame(key))
            self._frame_timers[key] = timer
            timer.start()

    def _slider_steps(self, binding, min_v, max_v):
        resolution = float(binding.get("tx_resolution", 1.0))
        resolution = max(resolution, 0.000001)
        steps = int(round((max_v - min_v) / resolution))
        return max(1, min(steps, 5000))

    def _format_slider_value(self, binding, value):
        decimals = self._resolution_decimals(binding.get("tx_resolution", 1.0))
        msg = self.db_messages.get(int(binding.get("bus", 1)), {}).get(int(binding.get("can_id", 0)))
        if msg and binding.get("signal_name"):
            try:
                sig = msg.get_signal_by_name(binding["signal_name"])
                if (not getattr(sig, "is_float", False)
                        and float(binding.get("scale", 1.0)).is_integer()
                        and float(binding.get("offset", 0.0)).is_integer()):
                    decimals = 0
            except KeyError:
                pass
        return f"{float(value):.{decimals}f}"

    def _resolution_decimals(self, step):
        text = f"{float(step):.10f}".rstrip("0")
        if "." not in text:
            return 0
        return min(6, len(text.split(".", 1)[1]))

    def _format_display_value(self, value):
        try:
            num = round(float(value), 3)
        except Exception:
            return str(value)

        if abs(num - round(num)) < 0.0005:
            return str(int(round(num)))

        text = f"{num:.3f}".rstrip("0").rstrip(".")
        return text if text else "0"

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
            signal = matching_signal(self.db_messages, binding)
            if signal is None:
                continue
            if (float(binding.get("scale", 1)) != float(signal.scale)
                    or float(binding.get("offset", 0)) != float(signal.offset)
                    or bool(binding.get("signed", False)) != bool(signal.is_signed)):
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
                        value_label.setText(self._format_slider_value(binding, v))
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
            ctrl.setStyleSheet(lamp_style(is_on))
            return

        if wtype == "label":
            ctrl.setText(self._format_display_value(v))
            return

    def _extract_raw_value(self, payload, binding):
        try:
            return unpack_raw(payload, binding)
        except (ValueError, TypeError, IndexError):
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
            "version": 4,
            "tx_packets": copy.deepcopy(self.tx_packets),
            "init_steps": copy.deepcopy(self.init_steps),
            "grid": {"rows": self.grid_rows, "cols": self.grid_cols, "cell_size": self.grid_cell_size},
            "mode": self.mode,
            "widgets": self.widgets_config,
            "channel_settings": copy.deepcopy(self.channel_settings),
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

        self.stop_panel_commands('패널 불러오기')
        self._packet_runtimes.clear()
        self.tx_packets = copy.deepcopy(data.get('tx_packets', []))
        self.init_steps = copy.deepcopy(data.get('init_steps', []))
        validate_steps(self.init_steps, actions_only=True, allow_empty=True)
        for packet in self.tx_packets:
            packet.setdefault('packet_id', str(uuid.uuid4()))

        self.grid_rows = max(1, int(data.get("grid", {}).get("rows", 12)))
        self.grid_cols = max(1, int(data.get("grid", {}).get("cols", 12)))
        self.grid_cell_size = max(16, int(data.get("grid", {}).get("cell_size", 32)))
        self.widgets_config = list(data.get("widgets", []))
        self.channel_settings = copy.deepcopy(data.get("channel_settings", {}))
        self.selected_widget_ids.clear()
        for cfg in self.widgets_config:
            self._normalize_config(cfg)
            if cfg.get('behavior') == 'tx' and cfg.get('widget_type') != 'sequence':
                packet = find_packet(self.tx_packets, cfg['binding'])
                if packet:
                    bind_packet(cfg['binding'], packet)
            reconcile_binding(self.db_messages, cfg["binding"])
        self.selected_widget_id = self.widgets_config[0].get("id") if self.widgets_config else None

        shape_count = sum(1 for c in self.widgets_config if str(c.get("widget_type", "")).startswith("shape_"))
        self._shape_counter = max(1, shape_count + 1)

        self.mode = 'edit'

        self._reset_history()
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
