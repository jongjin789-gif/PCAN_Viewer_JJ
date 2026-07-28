import os
import can
import time
from PyQt5.QtWidgets import *
import json
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon, QFont, QColor, QKeySequence
from src.utils import get_resource_path, SortableTreeWidgetItem
from src.can_threads import LogParserThread
from src.graph_log import LogGraphWindow


class LogViewerWindow(QMainWindow):
    """분석된 로그의 DBC 데이터를 표시하고 개별 시그널 그래프 창을 띄울 수 있는 창"""
    def __init__(self, file_path, db_messages, main_window=None):
        super().__init__()
        self.file_path = file_path
        self.db_messages = db_messages
        self.main_window = main_window
        self.active_graphs = []
        self.signal_data = {}
        self.signal_choices = {}
        self.raw_log_data = []
        self.highlighted_row = None
        self._populate_index = 0
        self._populate_chunk_size = 1000
        self._populate_progress = None
        self._is_closing = False
        self._fallback_notice_buses = set()

        # Transmission state
        self.is_sending = False
        self.current_send_index = 0
        self.send_timer = QTimer(self)
        self.send_timer.setTimerType(Qt.PreciseTimer)
        self.send_timer.setSingleShot(True)
        self.send_timer.timeout.connect(self.send_next_packet)
        self.send_start_time = 0
        self.log_start_offset_ms = 0
        
        self.setWindowTitle(f"Log Viewer - {os.path.basename(file_path)}")
        self.setWindowIcon(QIcon(get_resource_path(os.path.join("icon", "viewer.png"))))
        self.resize(800, 700)
        
        self.init_ui()
        self.start_parsing()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- Tab Widget ---
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # --- DBC Tab ---
        self.dbc_tab = QWidget()
        self.tabs.addTab(self.dbc_tab, "DBC")
        dbc_layout = QVBoxLayout(self.dbc_tab)
        
        dbc_btn_layout = QHBoxLayout()
        self.btn_view_graph = QPushButton("View Graph for Selection")
        self.btn_view_graph.clicked.connect(self.open_graph)
        dbc_btn_layout.addWidget(self.btn_view_graph)
        
        self.btn_uncheck_all = QPushButton("Uncheck All")
        self.btn_uncheck_all.clicked.connect(self.uncheck_all_signals)
        dbc_btn_layout.addWidget(self.btn_uncheck_all)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search (Message/Signal Name or ID)")
        self.search_input.textChanged.connect(self.filter_tree_items)
        dbc_btn_layout.addWidget(self.search_input)
        
        dbc_btn_layout.addStretch()
        dbc_layout.addLayout(dbc_btn_layout)
        
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Message / Signal', 'Bus', 'CAN ID (HEX)'])
        self.tree.setColumnWidth(0, 300)
        self.tree.setColumnWidth(1, 50)
        self.tree.setColumnWidth(2, 100)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(2, Qt.AscendingOrder) # 2. CAN ID
        self.tree.sortByColumn(1, Qt.AscendingOrder) # 1. Bus (Primary Sort Key)
        self.tree.itemChanged.connect(self.on_tree_item_changed)
        self.tree.setStyleSheet(
            "QTreeView::item { border-bottom: 1px solid #E0E0E0; }"
            "QTreeView::item:selected { background-color: #0078D7; color: white; }"
        )
        dbc_layout.addWidget(self.tree)

        # --- LOG Tab ---
        self.log_tab = QWidget()
        self.tabs.addTab(self.log_tab, "LOG")
        log_layout = QVBoxLayout(self.log_tab)

        # Control layout
        log_ctrl_layout1 = QHBoxLayout()
        self.btn_send = QPushButton("전송")
        self.btn_send.setCheckable(True)
        self.btn_send_single = QPushButton("선택 전송")
        self.chk_repeat = QCheckBox("반복")
        log_ctrl_layout1.addWidget(self.btn_send)
        log_ctrl_layout1.addWidget(self.btn_send_single)
        log_ctrl_layout1.addWidget(self.chk_repeat)
        log_ctrl_layout1.addStretch()

        log_ctrl_layout1.addWidget(QLabel("CAN ID Filter:"))
        self.edit_filter_low = QLineEdit("0x00")
        self.edit_filter_low.setMaximumWidth(50)
        self.edit_filter_high = QLineEdit("0x7FF")
        self.edit_filter_high.setMaximumWidth(50)
        self.btn_filter = QPushButton("필터")
        self.btn_filter.setCheckable(True)
        log_ctrl_layout1.addWidget(self.edit_filter_low)
        log_ctrl_layout1.addWidget(QLabel("~"))
        log_ctrl_layout1.addWidget(self.edit_filter_high)
        log_ctrl_layout1.addWidget(self.btn_filter)

        log_layout.addLayout(log_ctrl_layout1)

        # Log grid view
        self.log_table = QTableWidget()
        self.log_table.setColumnCount(7)
        self.log_table.setHorizontalHeaderLabels(["번호", "시간(ms)", "타입", "버스", "CAN ID", "DLC", "데이터"])
        self.log_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.log_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.log_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.log_table.horizontalHeader().setStretchLastSection(True)
        self.log_table.setFont(QFont("Consolas", 9))
        self.log_table.itemSelectionChanged.connect(self.update_control_states)
        log_layout.addWidget(self.log_table)

        # Connect signals
        self.btn_send.clicked.connect(self.on_send_toggled)
        self.btn_send_single.clicked.connect(self.on_send_single_clicked)
        self.btn_filter.toggled.connect(self.apply_filter)

        # Shortcuts
        self.shortcut_send_single = QShortcut(QKeySequence(Qt.Key_Space), self.log_table)
        self.shortcut_send_single.setContext(Qt.WidgetWithChildrenShortcut)
        self.shortcut_send_single.activated.connect(self.on_send_single_clicked)
        self.shortcut_copy = QShortcut(QKeySequence.Copy, self.log_table)
        self.shortcut_copy.setContext(Qt.WidgetWithChildrenShortcut)
        self.shortcut_copy.activated.connect(self.copy_selected_logs_to_clipboard)

        self.update_control_states()

    def update_control_states(self):
        any_bus_connected = False
        if self.main_window:
            any_bus_connected = any(bus is not None for bus in self.main_window.buses.values())

        self.btn_send.setEnabled(any_bus_connected)
        self.btn_send.setText("정지" if self.is_sending else "전송")

        is_row_selected = self.log_table.currentRow() >= 0
        self.btn_send_single.setEnabled(any_bus_connected and not self.is_sending and is_row_selected)

        self.chk_repeat.setEnabled(not self.is_sending)
        self.edit_filter_low.setEnabled(not self.is_sending)
        self.edit_filter_high.setEnabled(not self.is_sending)
        self.btn_filter.setEnabled(not self.is_sending)
        
        if not any_bus_connected and self.is_sending:
            self.stop_sending()

    def on_tree_item_changed(self, item, column):
        """트리 아이템의 체크 상태가 변경될 때 호출됩니다."""
        # 'Message / Signal' 컬럼(0)의 체크박스 변경에만 반응합니다.
        if column != 0:
            return

        # --- 재귀 호출 방지를 위해 시그널 처리 중단 ---
        self.tree.blockSignals(True)

        try:
            check_state = item.checkState(0)
            
            # 1. 부모 아이템(메시지)이 변경된 경우 -> 모든 자식(시그널)의 상태를 동기화
            if item.childCount() > 0:
                if check_state != Qt.PartiallyChecked:
                    for i in range(item.childCount()):
                        child = item.child(i)
                        child.setCheckState(0, check_state)
            
            # 2. 자식 아이템(시그널)이 변경된 경우 -> 부모의 상태를 갱신
            else:
                parent = item.parent()
                if parent:
                    checked_count = sum(1 for i in range(parent.childCount()) if parent.child(i).checkState(0) == Qt.Checked)
                    
                    if checked_count == 0:
                        parent.setCheckState(0, Qt.Unchecked)
                    elif checked_count == parent.childCount():
                        parent.setCheckState(0, Qt.Checked)
                    else:
                        parent.setCheckState(0, Qt.PartiallyChecked)
        finally:
            self.tree.blockSignals(False)
        
    def start_parsing(self):
        self.progress = QProgressDialog("Parsing TRC log file...", "Cancel", 0, 100, self)
        self.progress.setWindowModality(Qt.WindowModal)
        
        self.parser_thread = LogParserThread(self.file_path, self.db_messages)
        self.parser_thread.progress_signal.connect(self.progress.setValue)
        self.parser_thread.finished_signal.connect(self.on_parse_finished)
        self.parser_thread.error_signal.connect(self.on_parse_error)
        self.progress.canceled.connect(self.parser_thread.cancel)
        
        self.parser_thread.start()
        self.progress.show()

    def on_parse_finished(self, signal_data, found_msgs, raw_logs):
        self.progress.close()
        self.signal_data = signal_data
        self.raw_log_data = raw_logs
        self.populate_tree(found_msgs)
        self.populate_log_table()

    def on_parse_error(self, err_msg):
        self.progress.close()
        QMessageBox.critical(self, "Parse Error", f"Failed to parse log file:\n{err_msg}")

    def populate_log_table(self):
        self.log_table.setRowCount(0)
        total = len(self.raw_log_data)
        if total == 0:
            self.update_control_states()
            return

        self.log_table.setSortingEnabled(False)
        self.log_table.setUpdatesEnabled(False)
        self.log_table.setRowCount(total)

        self._populate_index = 0
        self._populate_progress = QProgressDialog("Rendering TRC log entries...", None, 0, total, self)
        self._populate_progress.setWindowModality(Qt.WindowModal)
        self._populate_progress.setCancelButton(None)
        self._populate_progress.show()
        QTimer.singleShot(0, self._populate_log_table_chunk)

    def _populate_log_table_chunk(self):
        if self._is_closing:
            return

        total = len(self.raw_log_data)
        end = min(self._populate_index + self._populate_chunk_size, total)

        for i in range(self._populate_index, end):
            log_entry = self.raw_log_data[i]
            self.log_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.log_table.setItem(i, 1, QTableWidgetItem(f"{log_entry['offset_ms']:.3f}"))
            self.log_table.setItem(i, 2, QTableWidgetItem(log_entry['type']))
            self.log_table.setItem(i, 3, QTableWidgetItem(str(log_entry['bus'])))
            self.log_table.setItem(i, 4, QTableWidgetItem(f"{log_entry['can_id']:X}"))
            self.log_table.setItem(i, 5, QTableWidgetItem(str(log_entry['dlc'])))
            self.log_table.setItem(i, 6, QTableWidgetItem(" ".join(f"{b:02X}" for b in log_entry['data'])))

        self._populate_index = end

        if self._populate_progress:
            self._populate_progress.setValue(end)

        if end < total:
            QTimer.singleShot(0, self._populate_log_table_chunk)
            return

        if self._populate_progress:
            self._populate_progress.close()
            self._populate_progress = None

        self.log_table.setUpdatesEnabled(True)
        if total <= 5000:
            self.log_table.resizeColumnsToContents()
        else:
            self.log_table.setColumnWidth(0, 70)
            self.log_table.setColumnWidth(1, 110)
            self.log_table.setColumnWidth(2, 70)
            self.log_table.setColumnWidth(3, 55)
            self.log_table.setColumnWidth(4, 90)
            self.log_table.setColumnWidth(5, 55)
        self.update_control_states()

    def populate_tree(self, found_msgs):
        self.tree.setSortingEnabled(False)

        for bus_num, can_id in sorted(found_msgs):
            if can_id in self.db_messages[bus_num]:
                msg_def = self.db_messages[bus_num][can_id]
                # 1. 부모 아이템을 메모리에서 먼저 생성합니다. (트리에 추가하기 전)
                msg_item = SortableTreeWidgetItem()
                msg_item.setText(0, msg_def.name)
                msg_item.setText(1, str(bus_num))
                msg_item.setText(2, hex(can_id).upper())

                font = QFont()
                font.setBold(True)
                # TypeError를 수정하고, 체크박스 렌더링 충돌을 피하기 위해
                # 메시지 아이템의 모든 컬럼에 폰트를 적용합니다.
                for i in range(self.tree.columnCount()):
                    msg_item.setFont(i, font)

                msg_item.setFlags(msg_item.flags() | Qt.ItemIsUserCheckable)
                msg_item.setCheckState(0, Qt.Unchecked)

                # 2. 자식 아이템들을 생성하여 메모리상의 부모 아이템에 추가합니다.
                for sig in msg_def.signals:
                    key = (bus_num, can_id)
                    if key in self.signal_data and sig.name in self.signal_data[key]:
                        sig_item = SortableTreeWidgetItem(msg_item)
                        if hasattr(sig, 'start_bit'):
                            sig_item.setData(0, Qt.UserRole, sig.start_bit)
                        sig_item.setText(0, sig.name)
                        sig_item.setText(1, "")
                        sig_item.setText(2, "")
                        sig_item.setFlags(sig_item.flags() | Qt.ItemIsUserCheckable)
                        sig_item.setCheckState(0, Qt.Unchecked)
                        sig_item.setData(0, Qt.UserRole + 1, (bus_num, can_id))
                    if getattr(sig, 'choices', None):
                        self.signal_choices[(bus_num, sig.name)] = sig.choices

                # 3. 자식까지 모두 포함된 부모 아이템을 트리에 추가합니다.
                self.tree.addTopLevelItem(msg_item)

        self.tree.setSortingEnabled(True)
        self.tree.expandAll()
        
        # 파싱 완료 후 검색어가 유지되고 있다면 즉시 필터링 적용
        if hasattr(self, 'search_input') and self.search_input.text():
            self.filter_tree_items(self.search_input.text())

    def apply_filter(self, checked):
        if not checked:
            for i in range(self.log_table.rowCount()):
                self.log_table.setRowHidden(i, False)
            return

        try:
            low_id = int(self.edit_filter_low.text(), 16)
            high_id = int(self.edit_filter_high.text(), 16)
        except ValueError:
            QMessageBox.warning(self, "입력 오류", "CAN ID는 16진수 형식으로 입력해야 합니다.")
            self.btn_filter.setChecked(False)
            return

        for i in range(self.log_table.rowCount()):
            try:
                can_id = int(self.log_table.item(i, 4).text(), 16)
                if low_id <= can_id <= high_id:
                    self.log_table.setRowHidden(i, False)
                else:
                    self.log_table.setRowHidden(i, True)
            except (ValueError, AttributeError):
                self.log_table.setRowHidden(i, True)

    def get_visible_log_data(self):
        """필터를 존중하여 현재 표시되는 로그 데이터 목록을 반환합니다."""
        visible_logs = []
        for i in range(self.log_table.rowCount()):
            if not self.log_table.isRowHidden(i):
                visible_logs.append(self.raw_log_data[i])
        return visible_logs

    def _resolve_target_bus(self, original_bus_num):
        """원본 버스가 미연결이면 현재 연결된 첫 번째 버스로 폴백합니다."""
        bus_obj = self.main_window.buses.get(original_bus_num)
        if bus_obj:
            return original_bus_num, bus_obj

        connected_buses = [b for b, obj in self.main_window.buses.items() if obj is not None]
        if not connected_buses:
            return original_bus_num, None

        fallback_bus = connected_buses[0]
        if original_bus_num not in self._fallback_notice_buses:
            self._fallback_notice_buses.add(original_bus_num)
            if self.main_window:
                self.main_window.statusBar().showMessage(
                    f"Bus {original_bus_num} 로그는 미연결 상태라 Bus {fallback_bus}로 전송합니다.",
                    4000
                )
        return fallback_bus, self.main_window.buses.get(fallback_bus)

    def copy_selected_logs_to_clipboard(self):
        selected_rows = sorted(list(set(index.row() for index in self.log_table.selectedIndexes())))
        if not selected_rows:
            return

        packets_to_copy = []
        for row in selected_rows:
            if row < len(self.raw_log_data):
                log_entry = self.raw_log_data[row]
                
                msg_type = log_entry['type']
                is_fd = 'F' in msg_type or 'B' in msg_type or 'E' in msg_type
                
                packet_data = {
                    "bus": log_entry.get('bus', 1), "id": log_entry['can_id'], "is_fd": is_fd,
                    "length": log_entry['dlc'], "data": list(log_entry['data']), "cycle": 0,
                    "note": f"From log at {log_entry['offset_ms']:.3f}ms", "symbol": "N/A",
                    "count": 0, "crc_type": "N/A"
                }
                packets_to_copy.append(packet_data)
        
        if packets_to_copy:
            try:
                text_data = json.dumps(packets_to_copy)
                QApplication.clipboard().setText(text_data)
                self.main_window.statusBar().showMessage(f"{len(packets_to_copy)} log entries copied to clipboard.", 3000)
            except Exception as e:
                self.main_window.statusBar().showMessage(f"Failed to copy logs: {e}", 3000)

    def on_send_toggled(self, checked):
        if checked:
            self.start_sending()
        else:
            self.stop_sending()

    def start_sending(self):
        if not self.main_window: return

        if not any(bus is not None for bus in self.main_window.buses.values()):
            QMessageBox.warning(self, "전송 불가", "연결된 CAN 채널이 없습니다.")
            self.btn_send.setChecked(False)
            return

        if hasattr(self.main_window, 'tx_panel'):
            self.main_window.tx_panel.stop_all_timers()

        self.is_sending = True

        # 전송 시작 위치 결정 (선택된 행 또는 처음부터)
        selected_row = self.log_table.currentRow()
        if selected_row >= 0:
            visible_logs = self.get_visible_log_data()
            try:
                # raw_log_data의 인덱스를 visible_logs에서의 인덱스로 변환
                selected_log_entry = self.raw_log_data[selected_row]
                self.current_send_index = visible_logs.index(selected_log_entry)
            except ValueError:
                # Selected row is not visible due to filter, start from beginning of visible logs
                self.current_send_index = 0
        else:
            self.current_send_index = 0
        
        # 드리프트 보정을 위한 타이밍 기준 초기화/리셋
        visible_logs = self.get_visible_log_data()
        if self.current_send_index < len(visible_logs):
            self.send_start_time = time.monotonic()
            self.log_start_offset_ms = visible_logs[self.current_send_index]['offset_ms']
        
        self.update_control_states()
        self.send_next_packet()

    def stop_sending(self):
        was_sending = self.is_sending or self.send_timer.isActive()
        self.is_sending = False
        if self.send_timer.isActive():
            self.send_timer.stop()

        if was_sending and self.highlighted_row is not None:
            self.clear_row_highlight(self.highlighted_row)
            self.highlighted_row = None

        self.update_control_states()
        if self.btn_send.isChecked():
            self.btn_send.setChecked(False)

    def on_send_single_clicked(self):
        if not self.main_window or self.is_sending: return

        selected_row = self.log_table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "전송 불가", "전송할 로그를 선택해주세요.")
            return

        try:
            log_entry = self.raw_log_data[selected_row]
            original_bus_num = log_entry.get('bus', 1)
            target_bus_num, bus_obj = self._resolve_target_bus(original_bus_num)

            if not bus_obj:
                QMessageBox.warning(self, "전송 불가", "연결된 CAN 채널이 없습니다.")
                return

            for j in range(self.log_table.columnCount()):
                item = self.log_table.item(selected_row, j)
                if item: item.setBackground(QColor("#d4edda"))
            self.highlighted_row = selected_row

            # Compatibility check
            msg_type = log_entry['type']
            # BRS(Bit Rate Switch) 플래그가 있거나 DLC가 8을 초과하는 패킷은 FD 전용 기능으로 간주합니다.
            is_incompatible = log_entry['dlc'] > 8 or 'B' in msg_type
            bus_is_fd = self.main_window.bus_capabilities[target_bus_num].get('is_fd', False)
            if is_incompatible and not bus_is_fd:
                QMessageBox.warning(self, "전송 무시됨", f"Bus {target_bus_num}은(는) CAN FD를 지원하지 않아\n"
                                                     f"선택된 FD 패킷(ID: {log_entry['can_id']:X})을 전송할 수 없습니다.")
                self.clear_row_highlight(selected_row)
                return

            is_fd = 'F' in msg_type or 'B' in msg_type or 'E' in msg_type or log_entry['dlc'] > 8
            is_brs = 'B' in msg_type
            msg = can.Message(arbitration_id=log_entry['can_id'], data=log_entry['data'], is_extended_id=log_entry['can_id'] > 0x7FF, is_fd=is_fd, bitrate_switch=is_brs)
            bus_obj.send(msg)

            if hasattr(self.main_window, 'record_tx_activity'):
                self.main_window.record_tx_activity(target_bus_num, log_entry['can_id'], log_entry['data'], is_fd)

            QTimer.singleShot(200, lambda: self.clear_row_highlight(selected_row))
        except Exception as e:
            QMessageBox.critical(self, "전송 오류", f"선택된 로그를 전송하는 중 오류가 발생했습니다:\n{e}")
            self.clear_row_highlight(selected_row)

    def clear_row_highlight(self, row):
        for j in range(self.log_table.columnCount()):
            item = self.log_table.item(row, j)
            if item:
                item.setBackground(QColor(Qt.transparent))
        if self.highlighted_row == row:
            self.highlighted_row = None

    def send_next_packet(self):
        if not self.is_sending:
            self.stop_sending()
            return
        
        if not any(bus is not None for bus in self.main_window.buses.values()):
            self.stop_sending()
            QMessageBox.warning(self, "전송 중지", "CAN 연결이 끊어져 전송을 중지합니다.")
            return

        log_data = self.get_visible_log_data()

        if self.current_send_index > 0:
            prev_log_index = self.current_send_index - 1
            if prev_log_index < len(log_data):
                try:
                    prev_log = log_data[prev_log_index]
                    prev_original_index = self.raw_log_data.index(prev_log)
                    self.clear_row_highlight(prev_original_index)
                except (ValueError, IndexError):
                    pass
        
        if not log_data or self.current_send_index >= len(log_data):
            if self.chk_repeat.isChecked():
                self.current_send_index = 0
                # 반복 시 타이밍 기준 리셋
                if log_data:
                    self.send_start_time = time.monotonic()
                    self.log_start_offset_ms = log_data[0]['offset_ms']
                self.send_timer.start(1)
            else:
                self.stop_sending()
            return

        current_log = log_data[self.current_send_index]
        try:
            original_index = self.raw_log_data.index(current_log)
            self.log_table.selectRow(original_index)
            for j in range(self.log_table.columnCount()):
                item = self.log_table.item(original_index, j)
                if item: item.setBackground(QColor("#d4edda"))
            self.highlighted_row = original_index
        except (ValueError, IndexError):
            pass

        original_bus_num = current_log.get('bus', 1)
        target_bus_num, bus_obj = self._resolve_target_bus(original_bus_num)
        
        should_send = True
        if bus_obj:
            msg_type = current_log['type']
            # BRS(Bit Rate Switch) 플래그가 있거나 DLC가 8을 초과하는 패킷은 FD 전용 기능으로 간주합니다.
            is_incompatible = current_log['dlc'] > 8 or 'B' in msg_type
            
            bus_is_fd = self.main_window.bus_capabilities[target_bus_num].get('is_fd', False)
            if is_incompatible and not bus_is_fd:
                should_send = False
        else:
            should_send = False

        if should_send:
            msg_type = current_log['type']
            is_fd = 'F' in msg_type or 'B' in msg_type or 'E' in msg_type or current_log['dlc'] > 8
            is_brs = 'B' in msg_type
            msg = can.Message(arbitration_id=current_log['can_id'], data=current_log['data'], is_extended_id=current_log['can_id'] > 0x7FF, is_fd=is_fd, bitrate_switch=is_brs)
            try:
                bus_obj.send(msg)
                if hasattr(self.main_window, 'record_tx_activity'):
                    self.main_window.record_tx_activity(target_bus_num, current_log['can_id'], current_log['data'], is_fd)
            except Exception as e:
                if self.main_window:
                    self.main_window.statusBar().showMessage(f"Tx Error: {e}", 3000)

        self.current_send_index += 1
        if self.current_send_index < len(log_data):
            next_log = log_data[self.current_send_index]
            
            # 드리프트 보정 로직: 다음 패킷의 목표 시간과 현재 시간의 차이를 계산하여 지연시간 결정
            # 이렇게 하면 QTimer의 불확실성이나 처리 오버헤드로 인한 누적 오차를 보정할 수 있습니다.
            elapsed_time_ms = (time.monotonic() - self.send_start_time) * 1000
            target_elapsed_time_ms = next_log['offset_ms'] - self.log_start_offset_ms
            delay_ms = target_elapsed_time_ms - elapsed_time_ms
            
            self.send_timer.start(max(1, int(delay_ms)))
        else:
            if self.chk_repeat.isChecked():
                self.current_send_index = 0
                # 반복 시 타이밍 기준 리셋
                if log_data:
                    self.send_start_time = time.monotonic()
                    self.log_start_offset_ms = log_data[0]['offset_ms']
                self.send_timer.start(1)
            else:
                self.stop_sending()

    def uncheck_all_signals(self):
        """트리에서 체크된 모든 시그널의 체크를 해제합니다."""
        for i in range(self.tree.topLevelItemCount()):
            msg_item = self.tree.topLevelItem(i)
            for j in range(msg_item.childCount()):
                sig_item = msg_item.child(j)
                if sig_item.checkState(0) == Qt.Checked:
                    sig_item.setCheckState(0, Qt.Unchecked)
                    
    def filter_tree_items(self, text):
        """검색어에 따라 트리 뷰의 메시지/시그널을 필터링합니다."""
        search_text = text.lower()
        for i in range(self.tree.topLevelItemCount()):
            msg_item = self.tree.topLevelItem(i)
            # 메시지 이름 또는 CAN ID (HEX) 매칭 확인
            msg_match = search_text in msg_item.text(0).lower() or search_text in msg_item.text(2).lower()
            
            any_child_match = False
            for j in range(msg_item.childCount()):
                sig_item = msg_item.child(j)
                sig_match = search_text in sig_item.text(0).lower()
                
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

    def open_graph(self):
        plot_data = {}
        for i in range(self.tree.topLevelItemCount()):
            msg_item = self.tree.topLevelItem(i)
            for j in range(msg_item.childCount()):
                sig_item = msg_item.child(j)
                if sig_item.checkState(0) == Qt.Checked:
                    bus_num, can_id = sig_item.data(0, Qt.UserRole + 1)
                    sig_name = sig_item.text(0)
                    key = (bus_num, can_id)
                    if key in self.signal_data and sig_name in self.signal_data[key]:
                        graph_sig_name = f"B{bus_num}:{sig_name}"
                        db_msg = self.db_messages[bus_num][can_id]
                        sig_def = db_msg.get_signal_by_name(sig_name)
                        unit = sig_def.unit if sig_def.unit else ""
                        plot_data[graph_sig_name] = {
                            "times": self.signal_data[key][sig_name][0],
                            "values": self.signal_data[key][sig_name][1],
                            "unit": unit
                        }
                        
        if not plot_data:
            QMessageBox.warning(self, "Warning", "그래프를 확인할 시그널을 트리에서 체크해주세요.")
            return
            
        graph = LogGraphWindow(plot_data, viewer_window=self)
        self.active_graphs.append(graph)
        graph.show()

    def closeEvent(self, event):
        self._is_closing = True
        self.stop_sending()
        if self._populate_progress:
            self._populate_progress.close()
            self._populate_progress = None
        if hasattr(self, 'parser_thread') and self.parser_thread.isRunning():
            self.parser_thread.cancel()
            self.parser_thread.wait()
        for graph in list(self.active_graphs):
            graph.close()
        if self.main_window and self in getattr(self.main_window, 'log_viewers', []):
            self.main_window.log_viewers.remove(self)
        event.accept()

    def refresh_parsing(self):
        """메인 윈도우에서 DB가 변경되었을 때 로그 뷰어 상태를 갱신합니다"""
        self.stop_sending()
        if hasattr(self, 'parser_thread') and self.parser_thread.isRunning():
            self.parser_thread.cancel()
            self.parser_thread.wait()
        self.tree.clear()
        self.log_table.setRowCount(0)
        self.signal_data.clear()
        for graph in list(self.active_graphs):
            graph.close()
        self.active_graphs.clear()
        self.start_parsing()
