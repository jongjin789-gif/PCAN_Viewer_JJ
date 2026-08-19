import sys, os, re
import platform
import subprocess
import time
import can, cantools
from src.PCANBasic import *
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QGroupBox, QHBoxLayout, QLabel, 
                             QComboBox, QPushButton, QListWidget, QListWidgetItem, QShortcut, QLineEdit,
                             QTreeWidget, QSplitter, QMessageBox, QFileDialog, QTreeWidgetItemIterator)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QIcon, QKeySequence
from src.utils import get_resource_path, SortableTreeWidgetItem
from src.can_threads import CANReceiverThread
from src.graph_realtime import SignalGraphWindow
from src.record_window import RecordWindow
from src.log_viewer import LogViewerWindow
from src.tx_panel import TxPanel
from src.user_panel import UserPanelWindow

class UniversalCANMonitor(QMainWindow):
    def __init__(self, viewer_only=False, user_panel_security=None):
        super().__init__()
        self.viewer_only = viewer_only
        self.user_panel_security = user_panel_security or {"enabled": False, "password": ""}
        
        app_version = self.get_app_version()
        version_str = f" - {app_version}" if app_version else ""
        
        if self.viewer_only:
            self.setWindowTitle(f'Log Viewer{version_str}')
        else:
            self.setWindowTitle(f'PCAN Monitoring{version_str}')
        self.setWindowIcon(QIcon(get_resource_path(os.path.join("icon", "viewer.png"))))
        self.resize(600, 200) if self.viewer_only else self.resize(1280, 800)
        
        self.buses = {1: None, 2: None, 3: None}
        self.bus_capabilities = {1: {'is_fd': False}, 2: {'is_fd': False}, 3: {'is_fd': False}}
        self.rx_threads = {1: None, 2: None, 3: None}
        self.db_messages = {1: {}, 2: {}, 3: {}} # {bus_num: {can_id: cantools.message.Message}}
        self.signal_tree_items = {} # {(bus_num, signal_name): QTreeWidgetItem}
        self.signal_choices = {} # {(bus_num, signal_name): choices} Enum 딕셔너리 정보
        self.msg_tree_items = {} # {(bus_num, can_id): QTreeWidgetItem}
        self.active_graphs = [] # [SignalGraphWindow, ...]
        self.synced_graphs_ordered = []
        self.combined_view_window = None
        self.record_window = None
        self.log_viewers = [] # [LogViewerWindow, ...]
        self.user_panel_window = None
        self.user_tx_cache = {}
        self.user_frame_properties = {} # User Panel 프레임 속성(BRS 등) 캐시
        
        self.init_ui()
        if not self.viewer_only:
            self.search_can_channels()
        
        # UI 갱신 타이머 (GUI 프리징 방지를 위해 50ms마다 렌더링) - 자동 연결(Open) 전에 미리 생성되어야 함
        self.ui_update_timer = QTimer(self)
        self.ui_update_timer.timeout.connect(self.update_ui_data)
        
        if hasattr(self, 'tx_panel') and not self.viewer_only:
            self.tx_panel.auto_load_packets()
        
    def get_app_version(self):
        """build_exe.py 파일 또는 실행 파일명에서 APP_VERSION을 추출하여 타이틀에 표시합니다."""
        if getattr(sys, 'frozen', False):
            try:
                exe_name = os.path.basename(sys.executable)
                match = re.search(r'Viewer_JJ_(.+?)_(?:win|linux|mac)', exe_name, re.IGNORECASE)
                if match:
                    return match.group(1)
            except Exception:
                pass
        else:
            try:
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                build_script = os.path.join(base_dir, 'build_exe.py')
                if os.path.exists(build_script):
                    with open(build_script, 'r', encoding='utf-8') as f:
                        for line in f:
                            if line.startswith('APP_VERSION') and '=' in line:
                                return line.split('=')[1].strip().strip('"\' ')
            except Exception:
                pass
        return ""

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        if self.viewer_only:
            main_layout.setContentsMargins(5, 5, 5, 5) # 뷰어 모드일 때 불필요한 테두리 여백 축소
        
        # ---------------------------------------------------------
        # 1. 상단 컨트롤 패널 (PCAN 채널 선택 및 연결)
        # ---------------------------------------------------------
        conn_group = QGroupBox("Connection Control")
        conn_layout = QVBoxLayout()
        
        self.combo_channels = {1: QComboBox(), 2: QComboBox(), 3: QComboBox()}
        self.combo_bitrate = {1: QComboBox(), 2: QComboBox(), 3: QComboBox()}
        self.combo_fd_iso = {1: QComboBox(), 2: QComboBox(), 3: QComboBox()}
        self.combo_data_bitrate = {1: QComboBox(), 2: QComboBox(), 3: QComboBox()}
        self.btn_refresh = {1: QPushButton("Refresh"), 2: QPushButton("Refresh"), 3: QPushButton("Refresh")}
        self.btn_open = {1: QPushButton("Open"), 2: QPushButton("Open"), 3: QPushButton("Open")}
        self.btn_close = {1: QPushButton("Close"), 2: QPushButton("Close"), 3: QPushButton("Close")}
        
        for i in range(1, 4):
            row_layout = QHBoxLayout()
            row_layout.addWidget(QLabel(f"Bus {i}:"))
            self.combo_channels[i].setMinimumWidth(160) # 너비 축소 (약 25글자)
            row_layout.addWidget(self.combo_channels[i])
            
            row_layout.addWidget(QLabel("Baudrate:"))
            self.combo_bitrate[i].setFixedWidth(90) # 통신속도 콤보박스 절반으로 축소
            row_layout.addWidget(self.combo_bitrate[i])
            
            # FD 지원 시 활성화될 콤보박스 2개 (ISO/Non-ISO, Data Bit Rate)
            self.combo_fd_iso[i].addItems(["ISO", "Non-ISO"])
            self.combo_fd_iso[i].setFixedWidth(75)
            self.combo_fd_iso[i].setEnabled(False)
            row_layout.addWidget(self.combo_fd_iso[i])
            
            self.combo_data_bitrate[i].setFixedWidth(90)
            self.combo_data_bitrate[i].setEnabled(False)
            row_layout.addWidget(self.combo_data_bitrate[i])
            
            # 채널 선택 변경 시 통신 속도 목록을 동적으로 업데이트하는 이벤트 연결
            self.combo_channels[i].currentIndexChanged.connect(lambda idx, b=i: self.on_channel_changed(b))
            self.on_channel_changed(i)
            
            self.btn_refresh[i].clicked.connect(lambda checked=False, b=i: self.search_can_channels(b))
            row_layout.addWidget(self.btn_refresh[i])
            
            self.btn_open[i].clicked.connect(lambda checked=False, b=i: self.open_can(b))
            row_layout.addWidget(self.btn_open[i])
            
            self.btn_close[i].clicked.connect(lambda checked=False, b=i: self.close_can(b))
            self.btn_close[i].setEnabled(False)
            row_layout.addWidget(self.btn_close[i])
            
            row_layout.addStretch()
            conn_layout.addLayout(row_layout)
            
        conn_group.setLayout(conn_layout)
        main_layout.addWidget(conn_group)
        conn_group.setVisible(not self.viewer_only)
        
        # ---------------------------------------------------------
        # 2. 데이터베이스 파일 로드 패널
        # ---------------------------------------------------------
        db_group = QGroupBox("Database Files (.dbc, .sym)")
        db_layout = QVBoxLayout()
        
        db_cols_layout = QHBoxLayout()
        self.btn_load_db = {}
        self.list_db_files = {}
        self.shortcut_delete_db = {}
        
        for i in range(1, 4):
            col_layout = QVBoxLayout()
            self.btn_load_db[i] = QPushButton(f"Load DBC/SYM (Bus {i})")
            self.btn_load_db[i].clicked.connect(lambda checked=False, b=i: self.load_database_file(b))
            col_layout.addWidget(self.btn_load_db[i])
            
            self.list_db_files[i] = QListWidget()
            if not self.viewer_only:
                self.list_db_files[i].setMaximumHeight(50)
            self.list_db_files[i].itemDoubleClicked.connect(lambda item, b=i: self.remove_database_file(item, b))
            col_layout.addWidget(self.list_db_files[i])
            
            # Delete 키 입력 시 삭제 이벤트 연결
            self.shortcut_delete_db[i] = QShortcut(QKeySequence(Qt.Key_Delete), self.list_db_files[i])
            self.shortcut_delete_db[i].setContext(Qt.WidgetWithChildrenShortcut)
            self.shortcut_delete_db[i].activated.connect(lambda b=i: self.remove_selected_db_file(b))
            
            db_cols_layout.addLayout(col_layout)
            
        db_layout.addLayout(db_cols_layout)
        
        bottom_db_layout = QHBoxLayout()
        bottom_db_layout.addStretch()
        self.btn_clear_all_db = QPushButton("Clear All DB Files")
        self.btn_clear_all_db.clicked.connect(self.clear_all_database_files)
        bottom_db_layout.addWidget(self.btn_clear_all_db)
        
        self.btn_open_log = QPushButton("Open TRC Log Viewer")
        self.btn_open_log.clicked.connect(self.open_log_viewer)
        self.btn_open_log.setEnabled(False)
        bottom_db_layout.addWidget(self.btn_open_log)
        db_layout.addLayout(bottom_db_layout)
        
        db_group.setLayout(db_layout)
        main_layout.addWidget(db_group)
        
        # ---------------------------------------------------------
        # 3. 트리 뷰 (모니터링 데이터 표시)
        # ---------------------------------------------------------
        tree_group = QWidget()
        tree_layout = QVBoxLayout(tree_group)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        
        btn_layout = QHBoxLayout()
        self.btn_view_graph = QPushButton("View Real-time Graph for Selection")
        self.btn_view_graph.clicked.connect(self.open_combined_graph)
        btn_layout.addWidget(self.btn_view_graph)
        
        self.btn_uncheck_all = QPushButton("Uncheck All")
        self.btn_uncheck_all.clicked.connect(self.uncheck_all_signals)
        btn_layout.addWidget(self.btn_uncheck_all)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search (Message/Signal Name or ID)")
        self.search_input.textChanged.connect(self.filter_tree_items)
        btn_layout.addWidget(self.search_input)
        
        btn_layout.addStretch()
        
        self.btn_clear_data = QPushButton("Clear Data")
        self.btn_clear_data.clicked.connect(self.clear_monitoring_data)
        btn_layout.addWidget(self.btn_clear_data)
        
        self.btn_record = QPushButton("Record")
        self.btn_record.clicked.connect(self.open_record_window)
        self.btn_record.setEnabled(False)
        btn_layout.addWidget(self.btn_record)
        
        tree_layout.addLayout(btn_layout)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Bus', 'Type', 'CAN ID (HEX)', 'Message / Signal', 'Direction', 'Value', 'Unit', 'Cycle (ms)', 'Count'])
        self.tree.setColumnWidth(0, 40)  # Bus
        self.tree.setColumnWidth(1, 50)  # Type
        self.tree.setColumnWidth(2, 90)  # CAN ID
        self.tree.setColumnWidth(3, 270) # Message / Signal
        self.tree.setColumnWidth(4, 60)  # Direction
        self.tree.setColumnWidth(5, 200) # Value
        self.tree.setColumnWidth(6, 80)  # Unit
        self.tree.setColumnWidth(7, 100) # Cycle
        self.tree.setColumnWidth(8, 80)  # Count
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(2, Qt.AscendingOrder) # 1. CAN ID
        self.tree.sortByColumn(0, Qt.AscendingOrder) # 2. Bus (Primary Sort Key)
        self.tree.itemChanged.connect(self.on_tree_item_changed)
        tree_layout.addWidget(self.tree)
        
        # ---------------------------------------------------------
        # 4. 송신부 (Tx 패널) 적용 및 QSplitter 구성
        # ---------------------------------------------------------
        self.tx_panel = TxPanel(self.buses, self.db_messages, self)
        self.btn_user_panel = QPushButton("User Panel")
        self.btn_user_panel.clicked.connect(self.open_user_panel)
        self.tx_panel.insert_toolbar_widget_before_clear(self.btn_user_panel)
        
        split_view = QSplitter(Qt.Vertical)
        split_view.addWidget(tree_group)
        split_view.addWidget(self.tx_panel)
        split_view.setSizes([400, 200]) # 상단 수신부와 하단 송신부의 초기 비율
        main_layout.addWidget(split_view, 1)  # stretch 인자를 1로 주어 가능한 많은 공간 할당
        split_view.setVisible(not self.viewer_only)

        # 가독성 향상을 위해 행마다 배경색을 교차로 표시하고, 구분선을 추가합니다.
        self.tree.setAlternatingRowColors(True)
        self.tree.setStyleSheet(
            "QTreeView::item { border-bottom: 1px solid #E0E0E0; }"
            "QTreeView::item:selected { background-color: #0078D7; color: white; }"
        )
        
        # 상태바 초기화
        self.statusBar().showMessage("Ready")
        
    def on_tree_item_changed(self, item, column):
        """트리 아이템의 체크 상태가 변경될 때 호출됩니다."""
        # 'Message / Signal' 컬럼(3)의 체크박스 변경에만 반응합니다.
        if column != 3:
            return

        # --- 재귀 호출 방지를 위해 시그널 처리 중단 ---
        self.tree.blockSignals(True)

        try:
            check_state = item.checkState(3)
            
            # 1. 부모 아이템(메시지)이 변경된 경우 -> 모든 자식(시그널)의 상태를 동기화
            if item.childCount() > 0:
                if check_state != Qt.PartiallyChecked:
                    for i in range(item.childCount()):
                        child = item.child(i)
                        child.setCheckState(3, check_state)
            
            # 2. 자식 아이템(시그널)이 변경된 경우 -> 부모의 상태를 갱신
            else:
                parent = item.parent()
                if parent:
                    checked_count = sum(1 for i in range(parent.childCount()) if parent.child(i).checkState(3) == Qt.Checked)
                    
                    if checked_count == 0:
                        parent.setCheckState(3, Qt.Unchecked)
                    elif checked_count == parent.childCount():
                        parent.setCheckState(3, Qt.Checked)
                    else:
                        parent.setCheckState(3, Qt.PartiallyChecked)
        finally:
            self.tree.blockSignals(False)

    def on_channel_changed(self, bus_num):
        """선택된 PCAN 채널의 FD 지원 여부에 따라 통신 속도(Bitrate) 목록을 동적으로 업데이트합니다."""
        self.combo_bitrate[bus_num].clear()
        self.combo_data_bitrate[bus_num].clear()
        channel_data = self.combo_channels[bus_num].currentData()
        
        is_fd = False
        if isinstance(channel_data, dict):
            is_fd = channel_data.get('is_fd', False)
            
        nom_baudrates = [
            # Classic CAN (Nominal Bitrate)
            ("1 MBit/s", {'bitrate': 1000000, 'nom_brp': 2, 'nom_tseg1': 31, 'nom_tseg2': 8, 'nom_sjw': 8}), 
            ("800 kBit/s", {'bitrate': 800000, 'nom_brp': 2, 'nom_tseg1': 39, 'nom_tseg2': 10, 'nom_sjw': 10}), 
            ("500 kBit/s", {'bitrate': 500000, 'nom_brp': 2, 'nom_tseg1': 63, 'nom_tseg2': 16, 'nom_sjw': 16}),
            ("250 kBit/s", {'bitrate': 250000, 'nom_brp': 4, 'nom_tseg1': 63, 'nom_tseg2': 16, 'nom_sjw': 16}), 
            ("125 kBit/s", {'bitrate': 125000, 'nom_brp': 8, 'nom_tseg1': 63, 'nom_tseg2': 16, 'nom_sjw': 16}), 
            ("100 kBit/s", {'bitrate': 100000, 'nom_brp': 10, 'nom_tseg1': 63, 'nom_tseg2': 16, 'nom_sjw': 16}),
            ("50 kBit/s", {'bitrate': 50000, 'nom_brp': 20, 'nom_tseg1': 63, 'nom_tseg2': 16, 'nom_sjw': 16}), 
            ("20 kBit/s", {'bitrate': 20000, 'nom_brp': 50, 'nom_tseg1': 63, 'nom_tseg2': 16, 'nom_sjw': 16}), 
            ("10 kBit/s", {'bitrate': 10000, 'nom_brp': 100, 'nom_tseg1': 63, 'nom_tseg2': 16, 'nom_sjw': 16})
        ]
            
        for text, rate in nom_baudrates:
            self.combo_bitrate[bus_num].addItem(text, rate)
            
        self.combo_bitrate[bus_num].setCurrentIndex(2) # Default 500 kBit/s
        
        if is_fd:
            self.combo_fd_iso[bus_num].setEnabled(True)
            self.combo_data_bitrate[bus_num].setEnabled(True)
            
            data_baudrates = [
                ("Off", None),
                ("1 MBit/s", {'data_brp': 2, 'data_tseg1': 31, 'data_tseg2': 8, 'data_sjw': 8}),
                ("2 MBit/s", {'data_brp': 2, 'data_tseg1': 15, 'data_tseg2': 4, 'data_sjw': 4}),
                ("4 MBit/s", {'data_brp': 2, 'data_tseg1': 7, 'data_tseg2': 2, 'data_sjw': 2}),
                ("8 MBit/s", {'data_brp': 2, 'data_tseg1': 3, 'data_tseg2': 1, 'data_sjw': 1})
            ]
            for text, data_rate in data_baudrates:
                self.combo_data_bitrate[bus_num].addItem(text, data_rate)
                
            self.combo_data_bitrate[bus_num].setCurrentIndex(0) # Default Off (N/A)
        else:
            self.combo_fd_iso[bus_num].setEnabled(False)
            self.combo_data_bitrate[bus_num].setEnabled(False)
            self.combo_data_bitrate[bus_num].addItem("N/A", None)

    def filter_tree_items(self, text):
        """검색어에 따라 트리 뷰의 메시지/시그널을 필터링합니다."""
        search_text = text.lower()
        for i in range(self.tree.topLevelItemCount()):
            msg_item = self.tree.topLevelItem(i)
            # 메시지 이름 또는 CAN ID (HEX) 매칭 확인
            msg_match = search_text in msg_item.text(3).lower() or search_text in msg_item.text(2).lower()
            
            any_child_match = False
            for j in range(msg_item.childCount()):
                sig_item = msg_item.child(j)
                sig_match = search_text in sig_item.text(3).lower()
                
                if msg_match or search_text == "":
                    sig_item.setHidden(False)
                    any_child_match = True
                elif sig_match:
                    sig_item.setHidden(False)
                    any_child_match = True
                else:
                    sig_item.setHidden(True)
                    
            if msg_match or any_child_match or search_text == "":
                msg_item.setHidden(False)
                if search_text != "" and (msg_match or any_child_match):
                    msg_item.setExpanded(True)
            else:
                msg_item.setHidden(True)

    def open_combined_graph(self):
        """선택된 여러 시그널을 하나의 그래프 창에 띄웁니다"""
        selected_signals = []

        # 기존: self.signal_tree_items 딕셔너리 순회 -> 데이터 수신 순서로 범례 생성
        # 변경: 화면에 보이는 Tree 위젯을 직접 순회 -> 화면에 정렬된 순서대로 범례 생성
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            # 자식 아이템(시그널)이고, 체크된 경우에만 리스트에 추가
            if item.parent() is not None and item.checkState(3) == Qt.Checked:
                parent = item.parent()
                if parent:
                    try:
                        bus_num_str = parent.text(0)
                        sig_name = item.text(3).strip()
                        bus_num = int(bus_num_str)
                        
                        full_sig_name = f"B{bus_num}:{sig_name}"
                        selected_signals.append(full_sig_name)
                    except (ValueError, IndexError):
                        continue # 데이터 파싱 오류 시 해당 시그널은 무시
            iterator += 1

        if not selected_signals:
            QMessageBox.warning(self, "Warning", "그래프를 확인할 시그널을 트리 체크박스에서 1개 이상 선택해주세요.")
            return
            
        graph = SignalGraphWindow(selected_signals, main_window=self)
        
        # 이미 열려있는 그래프 창이 있다면, 가장 최근 창의 크기를 가져와서 똑같이 맞춰줌
        visible_graphs = [g for g in self.active_graphs if g.isVisible()]
        if visible_graphs:
            graph.resize(visible_graphs[-1].size())
            
        self.active_graphs.append(graph)
        graph.show()
        
    def handle_sync_toggle(self, graph_window, is_checked):
        """그래프 창의 Sync 체크 상태 변경을 처리하여 순서가 있는 리스트를 관리합니다."""
        if is_checked:
            if graph_window not in self.synced_graphs_ordered:
                self.synced_graphs_ordered.append(graph_window)
        else:
            if graph_window in self.synced_graphs_ordered:
                self.synced_graphs_ordered.remove(graph_window)

    def open_combined_view(self):
        """동기화된 그래프들을 하나의 창에 모아보는 통합 뷰를 엽니다."""
        from src.combined_graph_view import CombinedGraphView
        if not self.synced_graphs_ordered:
            QMessageBox.information(self, "정보", "통합 보기 기능을 사용하려면 먼저 동기화할 그래프를 1개 이상 선택해주세요.")
            return

        try:
            if self.combined_view_window and self.combined_view_window.isVisible():
                self.combined_view_window.activateWindow()
                return
        except RuntimeError:
            self.combined_view_window = None

        self.combined_view_window = CombinedGraphView(self.synced_graphs_ordered, self)
        self.combined_view_window.show()
        
    def uncheck_all_signals(self):
        """트리에서 체크된 모든 시그널의 체크를 해제합니다."""
        for item in self.signal_tree_items.values():
            item.setCheckState(3, Qt.Unchecked)
            
    def clear_monitoring_data(self):
        """실시간 모니터링 중인 트리 데이터와 수집된 통계를 초기화합니다."""
        for bus_num in self.buses:
            self.reset_tree_values(bus_num)
            
    def open_record_window(self):
        """녹화 창 열기 및 뷰어 띄우기"""
        if not any(self.buses.values()):
            QMessageBox.warning(self, "Warning", "At least one CAN channel must be connected.")
            return
            
        # C++ 객체가 닫혀서 삭제된 경우 RuntimeError가 발생하므로 이를 처리하여 새 창을 생성하도록 함
        try:
            if self.record_window is not None and self.record_window.isVisible():
                self.record_window.raise_()
                self.record_window.activateWindow()
                return
        except RuntimeError:
            self.record_window = None

        # 메인 창과 별개의 독립된 창으로 띄우기 위해 parent를 None으로 설정 (closeEvent에서 자동 종료 처리됨)
        bitrates = {b: self.combo_bitrate[b].currentText() for b in range(1, 4) if self.buses[b]}
        self.record_window = RecordWindow(None, bitrates=bitrates)
        self.record_window.show()
            
    def route_raw_msg_to_record(self, ts, can_id, data, is_ext, is_err, is_fd, is_rx, bus_num):
        try:
            if getattr(self, 'record_window', None) and self.record_window.isVisible():
                self.record_window.add_log_entry(ts, can_id, data, is_ext, is_err, is_fd, is_rx, bus_num)
        except RuntimeError:
            self.record_window = None

    def record_tx_activity(self, bus_num, can_id, data, is_fd):
        """Rx 스레드를 거치지 않는 수동 Tx(로그 재생/Tx 패널)도 메인 트리에 즉시 반영합니다."""
        rx_thread = self.rx_threads.get(bus_num)
        if not rx_thread:
            return

        now = time.time()
        payload = bytes(data)
        stats = rx_thread.latest_msg_stats.get(
            can_id,
            {"count": 0, "cycle": 0.0, "last_time": None, "data": b"", "is_fd": False, "direction": 'Tx'}
        )
        stats["count"] += 1
        if stats["last_time"] is not None:
            stats["cycle"] = (now - stats["last_time"]) * 1000.0
        stats["last_time"] = now
        stats["data"] = payload
        stats["is_fd"] = bool(is_fd)
        stats["direction"] = 'Tx'
        rx_thread.latest_msg_stats[can_id] = stats

        # 상위 메시지 행뿐 아니라 하위 시그널 값도 갱신되도록 Tx 데이터도 즉시 디코딩합니다.
        db_msg = self.db_messages.get(bus_num, {}).get(can_id)
        if db_msg:
            try:
                decoded_data = db_msg.decode(payload, decode_choices=False)
                for sig_name, sig_val in decoded_data.items():
                    signal_def = db_msg.get_signal_by_name(sig_name)
                    unit = signal_def.unit if signal_def and signal_def.unit else ""
                    rx_thread.latest_data[sig_name] = (sig_val, unit, now)
            except Exception:
                pass

        self.route_raw_msg_to_record(
            now,
            can_id,
            payload,
            can_id > 0x7FF,
            False,
            bool(is_fd),
            False,
            bus_num
        )

    def _pack_signal_to_payload(self, payload, binding, phys_value):
        """저장된 바인딩 정보로 payload에 값을 비트 필드로 반영합니다.
        현재 fallback 경로는 little_endian만 지원합니다.
        """
        start_bit = int(binding.get("start_bit", 0))
        bit_length = int(binding.get("bit_length", 1))
        scale = float(binding.get("scale", 1.0))
        offset = float(binding.get("offset", 0.0))
        signed = bool(binding.get("signed", False))
        byte_order = str(binding.get("byte_order", "little_endian"))

        if byte_order == "big_endian":
            raise ValueError("Big endian fallback encoding is not supported yet.")

        if bit_length <= 0 or bit_length > 64:
            raise ValueError("Invalid bit length.")

        raw_f = (float(phys_value) - offset) / scale if scale != 0 else 0.0
        raw = int(round(raw_f))

        if signed:
            min_raw = -(1 << (bit_length - 1))
            max_raw = (1 << (bit_length - 1)) - 1
        else:
            min_raw = 0
            max_raw = (1 << bit_length) - 1

        raw = max(min_raw, min(max_raw, raw))

        if signed and raw < 0:
            raw = (1 << bit_length) + raw

        max_bits = len(payload) * 8
        if start_bit + bit_length > max_bits:
            raise ValueError("Bit range exceeds DLC.")

        current = int.from_bytes(payload, byteorder="little", signed=False)
        mask = ((1 << bit_length) - 1) << start_bit
        current = (current & ~mask) | ((raw << start_bit) & mask)
        new_payload = current.to_bytes(len(payload), byteorder="little", signed=False)
        return bytearray(new_payload)

    def send_user_panel_value(self, binding, phys_value):
        """User Panel에서 전달된 값을 CAN 프레임으로 인코딩하여 단발 전송합니다."""
        bus_num, can_id, dlc, _key = self.stage_user_panel_value(binding, phys_value)
        self.flush_user_panel_frame(bus_num, can_id, dlc)

    def stage_user_panel_value(self, binding, phys_value):
        """User Panel 값을 내부 CAN 프레임 캐시에만 반영하고 즉시 송신하지 않습니다."""
        bus_num = int(binding.get("bus", 1))
        can_id = int(binding.get("can_id", 0))
        dlc = int(binding.get("dlc", 8))
        dlc = max(1, min(64, dlc))

        key = (bus_num, can_id, dlc)
        payload = bytearray(self.user_tx_cache.get(key, bytes([0] * dlc)))
        if len(payload) != dlc:
            payload = bytearray([0] * dlc)

        payload = self._pack_signal_to_payload(payload, binding, phys_value)
        self.user_tx_cache[key] = bytes(payload)

        # BRS와 같은 프레임 레벨 속성을 캐시에 저장합니다.
        # 여러 도구가 동일 프레임에 다른 BRS 설정을 가질 경우, 마지막에 업데이트한 도구의 설정이 적용됩니다.
        is_brs = bool(binding.get("brs", False))
        if key not in self.user_frame_properties:
            self.user_frame_properties[key] = {}
        self.user_frame_properties[key]['brs'] = is_brs

        return bus_num, can_id, dlc, key

    def flush_user_panel_frame(self, bus_num, can_id, dlc):
        """내부 캐시에 저장된 User Panel 프레임을 송신합니다."""
        dlc = max(1, min(64, int(dlc)))
        key = (int(bus_num), int(can_id), dlc)
        payload = bytes(self.user_tx_cache.get(key, bytes([0] * dlc)))

        bus_obj = self.buses.get(int(bus_num))
        if bus_obj is None:
            raise RuntimeError(f"Bus {bus_num} is not connected.")

        # 프레임 속성 캐시에서 BRS 설정값을 가져옵니다.
        frame_props = self.user_frame_properties.get(key, {})
        is_brs = frame_props.get('brs', False)

        is_fd = dlc > 8 or is_brs
        if is_fd and not self.bus_capabilities[int(bus_num)].get('is_fd', False):
            raise RuntimeError(f"Bus {bus_num} does not support FD payload length {dlc}.")

        msg = can.Message(
            arbitration_id=int(can_id),
            data=payload,
            is_extended_id=(int(can_id) > 0x7FF),
            is_fd=is_fd,
            bitrate_switch=is_brs
        )
        bus_obj.send(msg)
        self.record_tx_activity(int(bus_num), int(can_id), payload, is_fd)

    def open_user_panel(self):
        if self.viewer_only:
            QMessageBox.information(self, "Info", "User panel is disabled in viewer-only mode.")
            return

        try:
            if self.user_panel_window is not None and self.user_panel_window.isVisible():
                self.user_panel_window.raise_()
                self.user_panel_window.activateWindow()
                return
        except RuntimeError:
            self.user_panel_window = None

        self.user_panel_window = UserPanelWindow(
            self,
            self.db_messages,
            None,
            security_config=self.user_panel_security,
        )
        self.user_panel_window.show()

    def get_db_file_paths_by_bus(self):
        result = {1: [], 2: [], 3: []}
        for bus_num in (1, 2, 3):
            lw = self.list_db_files.get(bus_num)
            if not lw:
                continue
            for i in range(lw.count()):
                p = lw.item(i).data(Qt.UserRole + 1)
                if p:
                    result[bus_num].append(p)
        return result

    def replace_db_files_by_bus(self, db_paths_by_bus):
        # 열린 그래프는 DB 기준이 바뀌면 무효가 되므로 먼저 닫습니다.
        for g in list(self.active_graphs):
            try:
                g.close()
            except Exception:
                pass
        self.active_graphs = []

        for bus_num in (1, 2, 3):
            self.list_db_files[bus_num].clear()
            self.db_messages[bus_num].clear()
            self.reset_tree_values(bus_num)

        for bus_num in (1, 2, 3):
            for p in db_paths_by_bus.get(bus_num, []):
                if os.path.exists(p):
                    self.load_db_from_path(p, bus_num, auto_save=False)

        self.btn_open_log.setEnabled(any(self.db_messages.values()))

        if hasattr(self, 'tx_panel') and not self.viewer_only:
            for bus_num in (1, 2, 3):
                self.tx_panel.refresh_db_symbols(bus_num)
            self.tx_panel.auto_save_packets()

    def search_can_channels(self, bus_num=None):
        """OS에 따라 CAN 채널 탐색 로직을 분기합니다."""
        if platform.system() == 'Linux':
            self.search_linux_socketcan_channels(bus_num)
        else:
            self.search_windows_can_channels(bus_num)

    def search_windows_can_channels(self, bus_num=None):
        """PCAN 및 기타 CAN 하드웨어 채널 탐색 및 ComboBox 업데이트 (Windows 전용)"""
        buses_to_update = [bus_num] if bus_num else [1, 2, 3]
        for b in buses_to_update:
            self.combo_channels[b].clear()
            self.combo_channels[b].setEnabled(True)
            self.combo_bitrate[b].setEnabled(True)
            self.btn_refresh[b].setEnabled(True)
            self.btn_open[b].setEnabled(True)
            
        # 1. PCAN 장치 탐색 (우선순위 높음, 상세 정보 표시)
        try:
            pcan = PCANBasic()
            result, data = pcan.GetValue(PCAN_NONEBUS, PCAN_ATTACHED_CHANNELS)
            
            if result == PCAN_ERROR_OK:
                for ch in data:
                    if ch.channel_handle != 0 and ch.channel_condition == PCAN_CHANNEL_AVAILABLE:
                        name = ch.device_name.decode(errors="ignore").strip('\x00')
                        handle_hex = hex(ch.channel_handle)
                        is_fd = bool(ch.device_features & FEATURE_FD_CAPABLE)
                        for b in buses_to_update:
                            self.combo_channels[b].addItem(f"{name} ({handle_hex}) {'[FD]' if is_fd else ''}", {'bustype': 'pcan', 'handle': ch.channel_handle, 'is_fd': is_fd})
        except Exception:
            pass
            
        # 2. python-can을 통한 기타 하드웨어 탐색 로직 (주석 처리)
        # 아래 로직은 PCAN 외 다양한 장치를 탐색하지만, 검색에 시간이 오래 걸릴 수 있어 주석 처리합니다.
        # 다른 종류의 CAN 장비(Vector, Ixxat, CANable 등)를 사용해야 할 경우, 이 아래의 주석을 해제하세요.
        # try:
        #     configs = can.detect_available_configs()
        #     for cfg in configs:
        #         iface = cfg.get('interface')
        #         if iface in ('pcan', 'virtual'): continue # PCAN은 별도 처리, virtual은 하단에서 수동 추가
                
        #         ch = cfg.get('channel')
        #         if iface == 'gs_usb':
        #             name = f"candleLight / gs_usb ({ch})"
        #         else:
        #             name = f"{iface.capitalize()} CAN {ch}" if isinstance(ch, int) else f"{iface.capitalize()} ({ch})"
        #         for b in buses_to_update:
        #             self.combo_channels[b].addItem(name, {'bustype': iface, 'handle': ch, 'is_fd': True})
        # except Exception:
        #     pass
            
        # # 2.5. 직렬(Serial/COM) 포트 기반 CANable (slcan 펌웨어) 탐색
        # try:
        #     import serial.tools.list_ports
        #     ports = serial.tools.list_ports.comports()
        #     for p in ports:
        #         if "COM" in p.device: # Windows COM 포트 필터링
        #             name = f"CANable / slcan ({p.device})"
        #             for b in buses_to_update:
        #                 self.combo_channels[b].addItem(name, {'bustype': 'slcan', 'handle': p.device, 'is_fd': False})
        # except ImportError:
        #     pass

        # 3. 물리 장비 없이도 테스트할 수 있는 가상 인터페이스(Virtual CAN) 추가 (숨김 처리)
        # for b in buses_to_update:
        #     self.combo_channels[b].addItem(f"Test-Only (Virtual {b})", {'bustype': 'virtual', 'handle': f'vcan{b}', 'is_fd': True})
            
        for b in buses_to_update:
            if self.combo_channels[b].count() == 0:
                self.combo_channels[b].addItem("No available PCAN channels found", None)
                self.combo_channels[b].setEnabled(False)
                self.btn_open[b].setEnabled(False)
            else:
                self.on_channel_changed(b) # 초기화 시 FD UI 갱신

    def search_linux_socketcan_channels(self, bus_num=None):
        """SocketCAN 채널 탐색 및 ComboBox 업데이트 (Linux 전용, PCAN-Basic API 미사용)"""
        buses_to_update = [bus_num] if bus_num else [1, 2, 3]
        for b in buses_to_update:
            self.combo_channels[b].clear()
            self.combo_channels[b].setEnabled(True)
            self.combo_bitrate[b].setEnabled(True)
            self.btn_refresh[b].setEnabled(True)
            self.btn_open[b].setEnabled(True)

        # 1. SocketCAN 인터페이스 탐색 (can, vcan 등)
        channels = []
        try:
            # /sys/class/net 디렉토리에서 can 및 vcan으로 시작하는 네트워크 인터페이스 탐색
            for iface in os.listdir('/sys/class/net'):
                if iface.startswith('can') or iface.startswith('vcan'):
                    channels.append(iface)
            channels.sort()
        except Exception:
            pass # /sys/class/net이 없는 비정상적인 리눅스 환경일 수 있음
            
        for b in buses_to_update:
            for ch in channels:
                # vcan 인터페이스의 경우, 테스트용임을 명확히 표기
                if ch.startswith('vcan'):
                    display_name = f"Test-Only ({ch})"
                else:
                    # PCAN 장치가 peak_usb 드라이버로 잡힌 경우 'canX'로 표시됨
                    display_name = f"{ch} [SocketCAN]"
                self.combo_channels[b].addItem(display_name, {'bustype': 'socketcan', 'handle': ch, 'is_fd': True})

            # 2. 물리 장비 없이도 테스트할 수 있는 python-can의 가상 인터페이스 추가 (숨김 처리)
            # self.combo_channels[b].addItem(f"Test-Only (Virtual {b})", {'bustype': 'virtual', 'handle': f'vcan{b}', 'is_fd': True})

            if self.combo_channels[b].count() == 0:
                self.combo_channels[b].addItem("No available CAN channels found", None)
                self.combo_channels[b].setEnabled(False)
                self.btn_open[b].setEnabled(False)
            else:
                self.on_channel_changed(b) # 초기화 시 FD UI 갱신

    def open_can(self, bus_num):
        """OS에 따라 CAN 채널 열기 로직을 분기합니다."""
        channel_data = self.combo_channels[bus_num].currentData()
        if not isinstance(channel_data, dict):
             QMessageBox.warning(self, "Warning", f"Please select a valid CAN channel for Bus {bus_num}.")
             return

        bustype = channel_data.get('bustype', 'pcan')

        if platform.system() == 'Linux' and bustype == 'socketcan':
            self.open_linux_socketcan(bus_num)
        else:
            # 윈도우의 모든 경우와, 리눅스의 virtual 등은 이 함수로 처리
            self.open_generic_can(bus_num)

    def open_generic_can(self, bus_num):
        """python-can 기반의 채널 열기 및 모니터링 시작 (PCAN, Virtual 등)"""
        channel_data = self.combo_channels[bus_num].currentData()
        if not isinstance(channel_data, dict) or channel_data.get('handle') is None:
            QMessageBox.warning(self, "Warning", f"Please select a valid CAN channel for Bus {bus_num}.")
            return
        channel_handle = channel_data.get('handle')
        bustype = channel_data.get('bustype', 'pcan')
            
        try:
            self.reset_tree_values(bus_num)
            
            # 선택된 통신 속도 가져오기 (dict 형태)
            selected_bitrate_kwargs = self.combo_bitrate[bus_num].currentData()
            kwargs = {'bustype': bustype, 'channel': channel_handle, 'receive_own_messages': True}
            
            # FD 통신 설정이 활성화 되어있는지 (Data Bitrate) 확인
            if bustype == 'pcan':
                if self.combo_data_bitrate[bus_num].isEnabled():
                    data_kwargs = self.combo_data_bitrate[bus_num].currentData()
                    if data_kwargs: 
                        kwargs['fd'] = True
                        kwargs['f_clock_mhz'] = 80
                        kwargs['iso_fd'] = (self.combo_fd_iso[bus_num].currentText() == "ISO")
                        kwargs.update(selected_bitrate_kwargs)
                        kwargs.update(data_kwargs)
                    else:
                        kwargs['bitrate'] = selected_bitrate_kwargs['bitrate']
                else:
                    kwargs['bitrate'] = selected_bitrate_kwargs['bitrate']
            elif bustype == 'virtual':
                if self.combo_data_bitrate[bus_num].isEnabled() and self.combo_data_bitrate[bus_num].currentData():
                    kwargs['fd'] = True
            else:
                kwargs['bitrate'] = selected_bitrate_kwargs['bitrate']
                if self.combo_data_bitrate[bus_num].isEnabled():
                    data_kwargs = self.combo_data_bitrate[bus_num].currentData()
                    if data_kwargs:
                        kwargs['fd'] = True
                        dbitrate_text = self.combo_data_bitrate[bus_num].currentText()
                        dbitrate = int(dbitrate_text.replace(' MBit/s', '000000').replace(' kBit/s', '000'))
                        kwargs['data_bitrate'] = dbitrate
            
            self.bus_capabilities[bus_num]['is_fd'] = kwargs.get('fd', False)
            self.buses[bus_num] = can.interface.Bus(**kwargs)
            
            self.rx_threads[bus_num] = CANReceiverThread(self.buses[bus_num], self.db_messages[bus_num])
            self.rx_threads[bus_num].error_signal.connect(lambda err, b=bus_num: self.handle_rx_error(err, b))
            self.rx_threads[bus_num].raw_msg_signal.connect(
                lambda ts, cid, data, ext, err, fd, is_rx, b=bus_num: self.route_raw_msg_to_record(ts, cid, data, ext, err, fd, is_rx, b)
            )
            self.rx_threads[bus_num].start()
            
            if not self.ui_update_timer.isActive():
                self.ui_update_timer.start(50)
            
            self.btn_open[bus_num].setEnabled(False)
            self.combo_channels[bus_num].setEnabled(False)
            self.combo_bitrate[bus_num].setEnabled(False)
            self.combo_fd_iso[bus_num].setEnabled(False)
            self.combo_data_bitrate[bus_num].setEnabled(False)
            self.btn_close[bus_num].setEnabled(True)
            self.btn_record.setEnabled(True)
            
            if hasattr(self, 'tx_panel'):
                self.tx_panel.update_all_action_buttons()
                self.tx_panel.auto_save_packets()
            
            self.statusBar().showMessage(f"Bus {bus_num} Opened: {channel_handle} ({bustype})", 5000)
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open CAN channel for Bus {bus_num}:\n{str(e)}")

    def open_linux_socketcan(self, bus_num):
        """선택된 채널 열기 및 모니터링 시작 (Linux SocketCAN 전용)"""
        channel_data = self.combo_channels[bus_num].currentData()
        if not isinstance(channel_data, dict) or channel_data.get('handle') is None:
            QMessageBox.warning(self, "Warning", f"Please select a valid CAN channel for Bus {bus_num}.")
            return
        channel_handle = channel_data['handle']
        
        try:
            self.reset_tree_values(bus_num)
            
            # UI에 표시된 콤보박스 텍스트를 파싱하여 숫자형 bitrate(bps) 추출
            bitrate_text = self.combo_bitrate[bus_num].currentText()
            bitrate = int(bitrate_text.replace(' MBit/s', '000000').replace(' kBit/s', '000'))
            
            fd_enabled = False
            dbitrate = None
            if self.combo_data_bitrate[bus_num].isEnabled():
                dbitrate_text = self.combo_data_bitrate[bus_num].currentText()
                if dbitrate_text not in ("Off", "N/A"):
                    fd_enabled = True
                    dbitrate = int(dbitrate_text.replace(' MBit/s', '000000').replace(' kBit/s', '000'))
            
            # vcan(가상 CAN)이 아닌 실제 하드웨어 CAN의 경우 ip link 설정 수행
            if not channel_handle.startswith('vcan'): # 실제 CAN 하드웨어
                # 인터페이스 설정을 위해 먼저 down -> up을 시도합니다. (sudo 없이)
                # 권한이 없는 경우, 사용자가 직접 터미널에서 실행하도록 안내합니다.
                subprocess.run(['ip', 'link', 'set', channel_handle, 'down'], stderr=subprocess.DEVNULL)
                
                ip_cmd = ['ip', 'link', 'set', channel_handle, 'up', 'type', 'can', 'bitrate', str(bitrate)]
                if fd_enabled and dbitrate:
                    ip_cmd.extend(['dbitrate', str(dbitrate), 'fd', 'on'])
                    
                res = subprocess.run(ip_cmd, capture_output=True, text=True)
                if res.returncode != 0:
                    is_root = False
                    try:
                        is_root = (os.geteuid() == 0)
                    except AttributeError: # Non-Linux
                        pass

                    if is_root:
                        # root 권한으로 실행했음에도 실패한 경우 (예: 존재하지 않는 인터페이스)
                        QMessageBox.warning(self, "명령 실행 오류",
                                              f"CAN 인터페이스 '{channel_handle}' 설정 중 오류가 발생했습니다.\n"
                                              f"인터페이스 이름이 정확한지 확인해주세요.\n\n"
                                              f"실행된 명령어: {' '.join(ip_cmd)}\n"
                                              f"에러: {res.stderr.strip()}")
                        return
                    else:
                        # root 권한이 없어 실패한 경우, sudo로 실행하도록 안내
                        sudo_cmd_str = f"sudo ip link set {channel_handle} down && sudo {' '.join(ip_cmd)}"
                        QMessageBox.warning(self, "권한 필요",
                                              f"CAN 인터페이스 '{channel_handle}' 설정에 실패했습니다.\n"
                                              "이 작업은 일반적으로 root 권한이 필요합니다.\n\n"
                                              "프로그램을 'sudo'로 다시 시작하거나,\n"
                                              "아래 명령어를 터미널에 복사하여 실행한 후 다시 시도해 주세요:\n"
                                              f"<code>{sudo_cmd_str}</code>")
                        return
            else: # vcan (가상 CAN)
                # vcan은 일반적으로 sudo 없이도 up 가능하지만, 실패 시 안내
                res = subprocess.run(['ip', 'link', 'set', channel_handle, 'up'], capture_output=True, text=True)
                if res.returncode != 0:
                    QMessageBox.warning(self, "권한 오류 가능성",
                                          f"가상 CAN 인터페이스 '{channel_handle}' 활성화에 실패했습니다.\n"
                                          "터미널에서 아래 명령어를 실행한 후 다시 시도해 주세요:\n"
                                          f"<code>sudo ip link set {channel_handle} up</code>")
                    return

            # python-can 객체 생성 (SocketCAN 기반)
            kwargs = {'bustype': 'socketcan', 'channel': channel_handle}
            if fd_enabled:
                kwargs['fd'] = True
            self.bus_capabilities[bus_num]['is_fd'] = fd_enabled
                
            self.buses[bus_num] = can.interface.Bus(**kwargs)
            
            self.rx_threads[bus_num] = CANReceiverThread(self.buses[bus_num], self.db_messages[bus_num])
            self.rx_threads[bus_num].error_signal.connect(lambda err, b=bus_num: self.handle_rx_error(err, b))
            self.rx_threads[bus_num].raw_msg_signal.connect(
                lambda ts, cid, data, ext, err, fd, is_rx, b=bus_num: self.route_raw_msg_to_record(ts, cid, data, ext, err, fd, is_rx, b)
            )
            self.rx_threads[bus_num].start()
            
            if not self.ui_update_timer.isActive():
                self.ui_update_timer.start(50)
            
            self.btn_open[bus_num].setEnabled(False)
            self.combo_channels[bus_num].setEnabled(False)
            self.combo_bitrate[bus_num].setEnabled(False)
            self.combo_fd_iso[bus_num].setEnabled(False)
            self.combo_data_bitrate[bus_num].setEnabled(False)
            self.btn_close[bus_num].setEnabled(True)
            self.btn_record.setEnabled(True)
            
            if hasattr(self, 'tx_panel'):
                self.tx_panel.update_all_action_buttons()
                self.tx_panel.auto_save_packets()
            
            self.statusBar().showMessage(f"Bus {bus_num} Opened: {channel_handle} (SocketCAN)", 5000)
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open Linux CAN channel for Bus {bus_num}:\n{str(e)}")

    def close_can(self, bus_num=None):
        """채널 닫기 및 초기화"""
        buses_to_close = [bus_num] if bus_num else [1, 2, 3]
        
        for b in buses_to_close:
            if self.rx_threads[b]:
                self.rx_threads[b].stop()
                self.rx_threads[b] = None
                
            if self.buses[b]:
                self.buses[b].shutdown()
                self.buses[b] = None
                self.bus_capabilities[b]['is_fd'] = False
                
            self.btn_open[b].setEnabled(True)
            self.combo_channels[b].setEnabled(True)
            self.combo_bitrate[b].setEnabled(True)
            
            channel_data = self.combo_channels[b].currentData()
            is_fd = isinstance(channel_data, dict) and channel_data.get('is_fd', False)
            if is_fd:
                self.combo_fd_iso[b].setEnabled(True)
                self.combo_data_bitrate[b].setEnabled(True)
                
            self.btn_close[b].setEnabled(False)
            
            self.statusBar().showMessage(f"Bus {b} Closed.", 5000)
            
        if not any(self.rx_threads.values()):
            self.ui_update_timer.stop()
            self.btn_record.setEnabled(False)
            
        if hasattr(self, 'tx_panel'):
            self.tx_panel.update_all_action_buttons()
            
        if not getattr(self, '_is_closing', False) and hasattr(self, 'tx_panel'):
            self.tx_panel.auto_save_packets()

    def handle_rx_error(self, err_msg, bus_num):
        err_lower = (err_msg or "").lower()
        if "receive queue was read too late" in err_lower or err_lower.startswith("rx warning"):
            self.statusBar().showMessage(f"Bus {bus_num}: {err_msg}", 5000)
            return

        self.close_can(bus_num)
        QMessageBox.critical(self, f"CAN Rx Error (Bus {bus_num})", err_msg)
   
    def load_database_file(self, bus_num):
        """DBC 또는 SYM 파일 로드 후 파싱하여 트리 구조 생성"""
        file_paths, _ = QFileDialog.getOpenFileNames(self, f"Select DBC/SYM files for Bus {bus_num}", "", "CAN DB Files (*.dbc *.sym)")
        
        if not file_paths:
            return
            
        for path in file_paths:
            self.load_db_from_path(path, bus_num, auto_save=True)

    def load_db_from_path(self, path, bus_num, auto_save=False):
        if not os.path.exists(path):
            return
            
        try:
            if path.lower().endswith('.sym'):
                format_version = "6.0"  # 기본값
                head_lines = []
                for enc in ['utf-8-sig', 'cp949', 'cp1252', 'latin1']:
                    try:
                        with open(path, 'r', encoding=enc) as f:
                            head_lines = [f.readline() for _ in range(10)]
                        break
                    except UnicodeDecodeError:
                        pass
                else:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        head_lines = [f.readline() for _ in range(10)]

                for line in head_lines:
                    if 'FormatVersion=' in line:
                        if '5.0' in line:
                            format_version = "5.0"
                        break
                        
                if format_version == "5.0":
                    db = self._load_sym_v5(path)
                else:
                    db = self._load_sym_v6(path)
            else:
                db = cantools.database.load_file(path)
            
            file_name = os.path.basename(path)
            item = QListWidgetItem(file_name)
            item.setData(Qt.UserRole, db)
            item.setData(Qt.UserRole + 1, path)
            self.list_db_files[bus_num].addItem(item)

            # DB 로드 후, 각 메시지 내의 시그널을 start_bit 기준으로 영구적으로 정렬합니다.
            # cantools 라이브러리는 메시지 내 시그널 목록(.signals)을 매번 알파벳 순으로 반환할 수 있으므로,
            # DB를 로드하는 시점에 한 번만 start_bit 기준으로 정렬해두면, 프로그램 전체에서 일관된 순서를 보장할 수 있습니다.
            for msg in db.messages:
                try:
                    # .sort()는 리스트를 내부적으로(in-place) 정렬합니다.
                    msg.signals.sort(key=lambda s: s.start_bit)
                except AttributeError:
                    # .sym 파일 등 start_bit 속성이 없는 경우, cantools의 기본 정렬(알파벳순)을 유지합니다.
                    pass

            self.register_db_messages(db, bus_num)

            if any(self.db_messages.values()):
                self.btn_open_log.setEnabled(True)
                
            if hasattr(self, 'tx_panel'):
                if not self.viewer_only:
                    self.tx_panel.refresh_db_symbols(bus_num)
                    if auto_save:
                        self.tx_panel.auto_save_packets()
                
            self.statusBar().showMessage(f"Loaded Database: {file_name} (Bus {bus_num})", 5000)
                
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to parse {path}:\n{str(e)}")

    def _load_sym_v6(self, file_path):
        """FormatVersion=6.0 심볼 파일을 읽어들이는 함수"""
        content = ""
        for enc in ['utf-8-sig', 'cp949', 'cp1252', 'latin1']:
            try:
                with open(file_path, 'r', encoding=enc) as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                pass
        else:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
        lines = content.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            lower_stripped = stripped.lower()
            
            # 1. 헤더 버전 라인 청소 (주석 제거 및 6.0 강제 적용)
            if 'FormatVersion=' in line:
                lines[i] = 'FormatVersion=6.0'
                continue
            
            # 2. cantools가 인식하지 못하는 전용 메타데이터 라인 자동 주석화
            # 예: Title="Untitled", Version=1.0, Author=... 등
            if lower_stripped.startswith(('title=', 'version=', 'author=', 'date=', 'description=', 'brs=')):
                lines[i] = '// ' + line
                
        cleaned_content = '\n'.join(lines)
        try:
            return cantools.database.load_string(cleaned_content, database_format='sym', strict=False)
        except Exception as e:
            error_msg = str(e)
            line_match = re.search(r'line:\s*(\d+)', error_msg, re.IGNORECASE)
            if line_match:
                line_num = int(line_match.group(1))
                if 1 <= line_num <= len(lines):
                    modified_line = lines[line_num - 1]
                    error_msg += f"\n\n[파싱 오류 발생 위치 (Line: {line_num})]\n- 변환된 내용: {modified_line}"
            raise Exception(error_msg)

    def _load_sym_v5(self, file_path):
        """FormatVersion=5.0 심볼 파일을 읽어들이는 함수"""
        content = ""
        for enc in ['utf-8-sig', 'cp949', 'cp1252', 'latin1']:
            try:
                with open(file_path, 'r', encoding=enc) as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                pass
        else:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

        # cantools가 SYM v5.0의 멀티라인 Enum 또는 대소문자 오류 등을 정상적으로 파싱하지 못하는 문제를 해결하기 위해
        # 파싱 전 파일을 전처리하여 해당 구문을 cantools 친화적인 형태로 변환합니다.
        original_lines = content.splitlines()
        processed_lines = []
        in_multiline_enum = False
        current_enum_line = ""

        for line in original_lines:
            stripped = line.strip()

            # 1. 멀티라인 Enum 정의 결합
            if not in_multiline_enum:
                if stripped.lower().startswith('enum '):
                    current_enum_line = " ".join(stripped.split())
                    if ')' in current_enum_line:
                        processed_lines.append(current_enum_line)
                        current_enum_line = ""
                    else:
                        in_multiline_enum = True
                else:
                    processed_lines.append(line)
            else:
                current_enum_line += " " + " ".join(stripped.split())
                if ')' in current_enum_line:
                    processed_lines.append(current_enum_line)
                    current_enum_line = ""
                    in_multiline_enum = False

        if in_multiline_enum:
            processed_lines.append(current_enum_line)

        lines = processed_lines
        for i, line in enumerate(lines):
            stripped = line.strip()
            lower_stripped = stripped.lower()

            # 1. cantools는 SYM 6.0만 지원하므로 5.0 파일이더라도 6.0으로 속여서 파싱하도록 강제 변경
            if 'FormatVersion=' in line:
                lines[i] = 'FormatVersion=6.0'
                continue

            # 2. 사용자 정의 5.0 규칙: 'DLC=<심볼 바이트 수>' -> V6.0의 'Len='으로 변환
            # (CycleTime은 생략 가능, Var 구조 동일하므로 해당 키워드만 맞춰주면 내부적으로 동일 처리됨)
            if lower_stripped.startswith('dlc'):
                lines[i] = re.sub(r'(?i)^DLC\s*=', 'Len=', stripped)
                continue

            # 3. cantools가 인식하지 못하는 전용 메타데이터 라인 자동 주석화
            # 예: Title="Untitled", Version=1.0, Author=... 등
            if lower_stripped.startswith(('title=', 'version=', 'author=', 'date=', 'description=', 'brs=')):
                lines[i] = '// ' + line
                continue

            # 4. cantools는 'Enum=NAME(...)' 포맷을 기대하지만, 일부 파일은 'enum NAME(...)'을 사용합니다.
            #    호환성을 위해 'enum '을 'Enum='으로 치환합니다. (대소문자 무시)
            if lower_stripped.startswith('enum '):
                lines[i] = re.sub(r'(?i)^enum\s+', 'Enum=', stripped)
                continue

            # 5. 단위(/u:) 등에 공백이 포함된 큰따옴표 문자열이 있을 경우 cantools 파서 오류 방지를 위해 공백을 밑줄로 치환하고 따옴표 제거
            if stripped.startswith('Var=') and '"' in stripped:
                def replace_spaces(match):
                    return match.group(0).replace(' ', '_').replace('"', '')
                lines[i] = re.sub(r'"[^"]+"', replace_spaces, lines[i])
                
        cleaned_content = '\n'.join(lines)
        try:
            return cantools.database.load_string(cleaned_content, database_format='sym', strict=False)
        except Exception as e:
            error_msg = str(e)
            line_match = re.search(r'line:\s*(\d+)', error_msg, re.IGNORECASE)
            if line_match:
                line_num = int(line_match.group(1))
                if 1 <= line_num <= len(lines):
                    modified_line = lines[line_num - 1]
                    error_msg += f"\n\n[파싱 오류 발생 위치 (Line: {line_num})]\n- 변환된 내용: {modified_line}"
            raise Exception(error_msg)

    def remove_database_file(self, item, bus_num):
        """더블클릭된 DB 파일을 목록에서 삭제하고 캐시/트리/뷰어를 갱신"""
        # 해당 버스(Bus)의 실시간 그래프가 하나라도 열려있는지 확인
        bus_prefix = f"B{bus_num}:"
        is_graph_open = False
        for g in self.active_graphs:
            if g.isVisible():
                if any(sig_name.startswith(bus_prefix) for sig_name in g.signal_names):
                    is_graph_open = True
                    break
                    
        if is_graph_open:
            QMessageBox.warning(self, "Warning", f"Bus {bus_num}에 해당하는 실시간 그래프가 켜져있습니다.\n해당 그래프 창을 닫은 후 삭제를 다시 시도해주세요.")
            return
            
        row = self.list_db_files[bus_num].row(item)
        self.list_db_files[bus_num].takeItem(row)
        
        self.db_messages[bus_num].clear()
        self.reset_tree_values(bus_num)
        
        for i in range(self.list_db_files[bus_num].count()):
            db = self.list_db_files[bus_num].item(i).data(Qt.UserRole)
            if db:
                self.register_db_messages(db, bus_num)
                
        if not any(self.db_messages.values()):
            self.btn_open_log.setEnabled(False)
            
        for viewer in getattr(self, 'log_viewers', []):
            if viewer.isVisible():
                viewer.refresh_parsing()
                
        if hasattr(self, 'tx_panel'):
            if not self.viewer_only:
                self.tx_panel.refresh_db_symbols(bus_num)
                self.tx_panel.auto_save_packets()
            
    def remove_selected_db_file(self, bus_num):
        """Delete 키를 통해 선택된 DB 파일을 목록에서 삭제"""
        selected_items = self.list_db_files[bus_num].selectedItems()
        for item in selected_items:
            self.remove_database_file(item, bus_num)
            
    def clear_all_database_files(self):
        """등록된 모든 데이터베이스 파일을 삭제합니다."""
        is_graph_open = False
        for g in self.active_graphs:
            if g.isVisible():
                is_graph_open = True
                break
                
        if is_graph_open:
            QMessageBox.warning(self, "Warning", "Real-time graphs are currently open.\nPlease close all graph windows and try again.")
            return
            
        reply = QMessageBox.question(self, 'Confirm', 'Are you sure you want to clear all loaded database files?', QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            for bus_num in range(1, 4):
                while self.list_db_files[bus_num].count() > 0:
                    item = self.list_db_files[bus_num].item(0)
                    self.remove_database_file(item, bus_num)

    def register_db_messages(self, db, bus_num):
        """데이터베이스의 메시지를 메모리에 등록 (수신 시 트리 추가용)"""
        new_ids = []
        for msg in db.messages:
            if msg.frame_id in self.db_messages[bus_num]:
                continue
            self.db_messages[bus_num][msg.frame_id] = msg
            new_ids.append(msg.frame_id)
            
        for can_id in new_ids:
            if (bus_num, can_id) in self.msg_tree_items:
                old_item = self.msg_tree_items[(bus_num, can_id)]
                index = self.tree.indexOfTopLevelItem(old_item)
                if index != -1:
                    self.tree.takeTopLevelItem(index)
                del self.msg_tree_items[(bus_num, can_id)]
                
                self.add_message_to_tree(bus_num, can_id)

    def add_message_to_tree(self, bus_num, can_id, direction='Rx'):
        """CAN 데이터가 수신되었을 때 해당 메시지와 시그널을 트리에 동적 생성"""
        if can_id in self.db_messages[bus_num]:
            db_msg = self.db_messages[bus_num][can_id]
            msg_name = db_msg.name
            # DB 로드 시점에 이미 영구적으로 정렬되었으므로, 여기서는 db_msg.signals를 그대로 사용합니다.
            signals = db_msg.signals
        else:
            msg_name = f"Unknown ID: {hex(can_id).upper()}"
            signals = []
        
        # 정렬이 활성화된 상태에서 자식 노드를 추가하면 __lt__ 비교 함수에 의해 자동 정렬되지만,
        # 간혹 순서가 꼬이는 문제가 있어, 수동으로 정렬된 순서대로 삽입되도록 잠시 비활성화합니다.
        # is_sorting_enabled = self.tree.isSortingEnabled()
        # self.tree.setSortingEnabled(False)

        # 1. Message Node (Root)를 메모리에서 먼저 생성 (트리에 추가하기 전)
        msg_item = SortableTreeWidgetItem()
        can_id_str = f"0x{can_id:03X}" if can_id <= 0x7FF else f"0x{can_id:X}"
        msg_item.setText(0, str(bus_num))
        msg_item.setText(1, "-") # Type
        msg_item.setText(2, can_id_str)
        msg_item.setText(3, msg_name)
        msg_item.setText(4, direction)
        msg_item.setText(5, "-") # Value
        msg_item.setText(7, "-") # Cycle
        msg_item.setText(8, "0") # Count
        
        # 부모 노드는 굵은 글씨체 적용
        font = QFont()
        font.setBold(True)
        msg_item.setFont(3, font)
        
        # 부모 노드(메시지)에도 체크박스 추가
        msg_item.setFlags(msg_item.flags() | Qt.ItemIsUserCheckable)
        msg_item.setCheckState(3, Qt.Unchecked)
        
        # 2. Signal Node (Child)를 생성하여 메모리 상의 부모 노드에 추가
        for sig in signals:
            sig_item = SortableTreeWidgetItem(msg_item)
            # .sym 파일 등 start_bit 속성이 없는 경우를 대비하여 방어 코드 추가
            if hasattr(sig, 'start_bit'):
                sig_item.setData(3, Qt.UserRole, sig.start_bit) # 정렬을 위해 start_bit 저장
            # 시그널(세부항목) 행은 이름과 값만 표시하여 가독성 향상
            sig_item.setText(0, "") # Bus
            sig_item.setText(1, "") # Type
            sig_item.setText(2, "") # CAN ID
            sig_item.setText(3, f"    {sig.name}")
            sig_item.setText(4, "") # Direction
            sig_item.setText(5, "-") # Value
            sig_item.setText(6, sig.unit if sig.unit else "")
            
            # 체크박스 추가
            sig_item.setFlags(sig_item.flags() | Qt.ItemIsUserCheckable)
            sig_item.setCheckState(3, Qt.Unchecked)
            
            self.signal_tree_items[(bus_num, sig.name)] = sig_item
            
            # Enum 정보 저장
            if getattr(sig, 'choices', None):
                self.signal_choices[(bus_num, sig.name)] = sig.choices
            
        # 3. 완성된 메시지 노드(자식 포함)를 트리에 추가
        self.tree.addTopLevelItem(msg_item)
        self.msg_tree_items[(bus_num, can_id)] = msg_item
        
        # 4. 추가된 노드 펼치기
        msg_item.setExpanded(True)
        
        # 원래 정렬 상태로 복원
        # self.tree.setSortingEnabled(is_sorting_enabled)

        # 현재 검색어가 있다면 새로 추가된 항목에도 필터링 상태 즉시 적용
        if hasattr(self, 'search_input') and self.search_input.text():
            self.filter_tree_items(self.search_input.text())

    def open_log_viewer(self):
        """로컬 TRC 로그 파일을 열어 새 뷰어 창을 생성"""
        file_paths, _ = QFileDialog.getOpenFileNames(self, "Open TRC Log Files", "", "TRC Files (*.trc)")
        for file_path in file_paths:
            viewer = LogViewerWindow(file_path, self.db_messages, main_window=self)
            self.log_viewers.append(viewer)
            viewer.show()
            self.statusBar().showMessage(f"Opened TRC Log: {os.path.basename(file_path)}", 5000)

    def update_ui_data(self):
        """Rx 스레드에서 수집한 최신 데이터를 기반으로 UI만 업데이트"""
        # 닫힌 그래프 창 메모리 정리.
        # Combined View에 포함되어 숨겨진(is_visible=False) 그래프도 업데이트 대상에 포함시켜야 하므로,
        # is_in_combined_view 플래그를 함께 확인하여 목록에서 제외되지 않도록 합니다.
        self.active_graphs = [g for g in self.active_graphs if g.isVisible() or getattr(g, 'is_in_combined_view', False)]
        
        # 닫힌 그래프는 동기화 목록에서도 동일한 기준으로 정리합니다.
        self.synced_graphs_ordered = [g for g in self.synced_graphs_ordered if g.isVisible() or getattr(g, 'is_in_combined_view', False)]
        
        for bus_num, rx_thread in self.rx_threads.items():
            if not rx_thread: continue
            
            try:
                for can_id, stats in list(rx_thread.latest_msg_stats.items()):
                    if (bus_num, can_id) not in self.msg_tree_items:
                        self.add_message_to_tree(bus_num, can_id)
                        
                    if (bus_num, can_id) in self.msg_tree_items:
                        item = self.msg_tree_items[(bus_num, can_id)]
                        from PyQt5.QtGui import QColor

                        direction = stats.get("direction", 'Rx')
                        if direction == 'Tx':
                            color = QColor(230, 240, 255) # Light blue for Tx
                        else:
                            color = QColor(Qt.transparent)
                        
                        for i in range(self.tree.columnCount()):
                            item.setBackground(i, color)
                        
                        hex_str = " ".join(f"{b:02X}" for b in stats["data"])
                        msg_type = "FD" if stats.get("is_fd") else "CAN"
                        item.setText(1, msg_type)
                        item.setText(4, direction)
                        item.setText(5, hex_str)
                        item.setText(7, f"{stats['cycle']:.1f}")
                        item.setText(8, str(stats['count']))

                        if self.user_panel_window and self.user_panel_window.isVisible():
                            try:
                                self.user_panel_window.on_message_update(
                                    bus_num,
                                    can_id,
                                    stats.get("data", b""),
                                    stats.get("last_time", time.time())
                                )
                            except RuntimeError:
                                self.user_panel_window = None
            except RuntimeError:
                pass
                
            try:
                for sig_name, (val, unit, ts) in list(rx_thread.latest_data.items()):
                    if (bus_num, sig_name) in self.signal_tree_items:
                        item = self.signal_tree_items[(bus_num, sig_name)]
                        from PyQt5.QtGui import QColor
                        for i in range(self.tree.columnCount()):
                            item.setBackground(i, QColor(Qt.transparent))
                        
                        choices = getattr(self, 'signal_choices', {}).get((bus_num, sig_name))
                        if choices:
                            if isinstance(val, (int, float)) and int(val) in choices:
                                display_val = f"{choices[int(val)]} ({val})" # Enum 매칭 시 문자열과 수치값 함께 출력
                            else:
                                val_str = str(val)
                                num_val = next((k for k, v in choices.items() if str(v) == val_str), None)
                                display_val = f"{val_str} ({num_val})" if num_val is not None else val_str
                        else:
                            display_val = val if isinstance(val, str) else (f"{val:.3f}" if isinstance(val, float) else str(val))
                        item.setText(5, display_val)

                    if self.user_panel_window and self.user_panel_window.isVisible():
                        try:
                            self.user_panel_window.on_signal_update(bus_num, sig_name, val, unit, ts)
                        except RuntimeError:
                            self.user_panel_window = None
                            
                    item_unit = item.text(6)
                    for graph in self.active_graphs:
                        graph_sig_name = f"B{bus_num}:{sig_name}"
                        if graph_sig_name in graph.signal_names:
                            graph.update_data(graph_sig_name, ts, val, item_unit)
            except RuntimeError:
                pass

    def reset_tree_values(self, bus_num):
        """채널 재연결 시 기존 트리 데이터 및 UI 초기화"""
        items_to_remove = []
        for (b, can_id), item in list(self.msg_tree_items.items()):
            if b == bus_num:
                items_to_remove.append(item)
                del self.msg_tree_items[(b, can_id)]
                
        for (b, sig_name) in list(self.signal_tree_items.keys()):
            if b == bus_num:
                del self.signal_tree_items[(b, sig_name)]
                if (b, sig_name) in getattr(self, 'signal_choices', {}):
                    del self.signal_choices[(b, sig_name)]
                
        for item in items_to_remove:
            index = self.tree.indexOfTopLevelItem(item)
            if index != -1:
                self.tree.takeTopLevelItem(index)
        
        if self.rx_threads[bus_num]:
            self.rx_threads[bus_num].latest_data.clear()
            self.rx_threads[bus_num].latest_msg_stats.clear()

    def closeEvent(self, event):
        """프로그램 종료 시 포트 안전 종료"""
        self._is_closing = True
        if not self.viewer_only:
            for i in range(1, 4):
                self.close_can(i)
        
        # 메인 윈도우가 닫힐 때 실시간 그래프 창 모두 닫기
        for graph in list(getattr(self, 'active_graphs', [])):
            graph.close()
            
        # 메인 윈도우가 닫힐 때 Record 창이 켜져있다면 강제로 닫기
        try:
            if getattr(self, 'record_window', None) and self.record_window.isVisible():
                self.record_window.close()
        except RuntimeError:
            pass
            
        # 메인 윈도우가 닫힐 때 모든 로그 뷰어 창도 닫기
        for viewer in list(getattr(self, 'log_viewers', [])):
            viewer.close()

        # 사용자 패널 창이 열려 있으면 함께 종료
        try:
            if self.user_panel_window and self.user_panel_window.isVisible():
                self.user_panel_window.close()
        except RuntimeError:
            pass
            
        # 메인 윈도우가 닫힐 때 Combined View 창도 닫기
        try:
            if self.combined_view_window and self.combined_view_window.isVisible():
                self.combined_view_window.parent_is_closing = True
                self.combined_view_window.close()
        except RuntimeError:
            self.combined_view_window = None
            
        # 메인 윈도우가 닫힐 때 송신부 타이머 종료
        if hasattr(self, 'tx_panel') and not self.viewer_only:
            for i in range(self.tx_panel.tree.topLevelItemCount()):
                item = self.tx_panel.tree.topLevelItem(i)
                if hasattr(item, 'stop_timer'):
                    item.stop_timer()

        event.accept()
