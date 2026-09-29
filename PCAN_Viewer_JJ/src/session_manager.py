"""Main-window session coordinator: validate first, then replace and reconnect."""
import copy
import hashlib
import os
from pathlib import Path
import uuid
from types import SimpleNamespace

from PyQt5.QtCore import QObject, QStandardPaths, Qt, QTimer
from PyQt5.QtWidgets import QFileDialog, QMessageBox

from src.session_storage import (EXTENSION, FORMAT, atomic_write, decode_db, encode_db,
                                 read_session, serialize, validate_structure, write_session,
                                 validate_graph, validate_panel)
from src.session_graph import graph_state, restore_graph, restore_geometry


def device_identity(data):
    if not isinstance(data, dict) or data.get('handle') is None:
        return None
    handle = data['handle']
    handle = getattr(handle, 'value', handle)
    identity = dict(bustype=data.get('bustype', 'pcan'), handle=handle)
    for key in ('device_id', 'device_type', 'controller_number'):
        if key in data:
            identity[key] = data[key]
    return identity


class SessionManager(QObject):
    def __init__(self, main, storage_dir=None):
        super().__init__(main)
        self.main = main
        base = storage_dir or os.path.join(
            QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation), 'PCAN_Viewer_JJ')
        self.directory = Path(base)
        self.autosave_path = self.directory / ('session' + EXTENSION)
        self.busy = False
        self.ready = False
        self.enabled = True
        self.errors = None
        self.last_digest = None
        self.pending_can = {}
        self.timer = QTimer(self)
        self.timer.setInterval(5000)
        self.timer.timeout.connect(self.autosave)

    def start(self):
        if self.main.viewer_only:
            return
        if self.autosave_path.exists():
            if not self.load(self.autosave_path):
                # Keep the damaged file available for recovery; don't overwrite it.
                self.enabled = False
        else:
            self.main.tx_panel.auto_load_packets()
        self.ready = True
        self.timer.start()

    def report(self, title, summary, issues):
        if self.main.user_panel_window is not None:
            self.main.user_panel_window.log_system(summary + ': ' + ' | '.join(issues), 'WARN')
        box = QMessageBox(self.main.user_panel_window or self.main)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Warning)
        box.setText(summary)
        box.setInformativeText('\n'.join(issues[:8]))
        if len(issues) > 8:
            box.setDetailedText('\n'.join(issues))
        box.exec_()

    def capture_can(self, bus):
        m = self.main
        cfg = dict(device=device_identity(m.combo_channels[bus].currentData()),
                   channel=m.combo_channels[bus].currentText(),
                   bitrate=m.combo_bitrate[bus].currentText(),
                   fd_iso=m.combo_fd_iso[bus].currentText(),
                   data_bitrate=m.combo_data_bitrate[bus].currentText(),
                   is_open=m.buses[bus] is not None)
        pending = self.pending_can.get(bus)
        if pending and cfg == pending[1]:
            # Retain unavailable FD settings and device identity for another PC.
            desired = copy.deepcopy(pending[0])
            desired['is_open'] = cfg['is_open']
            return desired
        self.pending_can.pop(bus, None)
        return cfg

    def capture(self):
        m = self.main
        databases = {}
        for bus, listing in m.list_db_files.items():
            entries = []
            for i in range(listing.count()):
                item = listing.item(i)
                raw = item.data(Qt.UserRole + 2)
                if raw is None:
                    raise ValueError(f'BUS {bus}: {item.text()} 원문이 없습니다. DB를 다시 등록하세요.')
                ident = item.data(Qt.UserRole + 3)
                entries.append(encode_db(item.text(), bytes(raw), ident))
            databases[str(bus)] = entries
        packets = []
        for i in range(m.tx_panel.tree.topLevelItemCount()):
            packet = copy.deepcopy(m.tx_panel.tree.topLevelItem(i).packet_data)
            packet['count'] = 0
            packets.append(packet)
        graphs = [graph_state(g) for g in m.active_graphs
                  if g.isVisible() or getattr(g, 'is_in_combined_view', False) or getattr(g, '_panel_only_hidden', False)]
        panel = m.user_panel_window
        panel_state = None
        if panel is not None:
            panel_state = dict(data=copy.deepcopy(panel._panel_data()), visible=panel.isVisible(),
                               geometry=panel.geometry().getRect())
            panel_state['data']['mode'] = 'standby'
        return dict(format=FORMAT, version=1, databases=databases,
                    can={str(b): self.capture_can(b) for b in (1, 2, 3)},
                    tx_packets=packets, graphs=graphs, panel=panel_state)

    def autosave(self):
        if (not self.ready or not self.enabled or self.busy or self.main.viewer_only
                or getattr(self.main, '_is_closing', False)):
            return
        try:
            raw = serialize(self.capture())
            digest = hashlib.sha256(raw).digest()
            if digest != self.last_digest:
                atomic_write(self.autosave_path, raw)
                self.last_digest = digest
        except Exception as exc:
            self.main.statusBar().showMessage(f'설정 자동 저장 실패: {exc}', 10000)

    def save_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self.main, '통합 설정 저장',
                    str(self.directory / ('settings' + EXTENSION)), f'통합 설정 (*{EXTENSION})')
        if not path:
            return
        if not path.lower().endswith(EXTENSION):
            path += EXTENSION
        try:
            write_session(path, self.capture())
            self.enabled = True
            self.autosave()
            self.main.statusBar().showMessage(f'통합 설정 저장 완료: {path}', 10000)
        except Exception as exc:
            self.report('저장 실패', '통합 설정을 저장하지 못했습니다.', [str(exc)])

    def load_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self.main, '통합 설정 불러오기',
                    str(self.directory), f'통합 설정 (*{EXTENSION})')
        if path:
            self.load(path)

    def prepare(self, data, strict=True):
        """Build hidden replacement widgets with disconnected CAN, without touching live state."""
        from src.graph_realtime import SignalGraphWindow
        from src.user_panel import UserPanelWindow
        from src.user_panel_v2.packets import validate_packet, UnregisteredPacketError
        from src.user_panel_v2.sequence import validate_steps
        validate_structure(data)
        prepared = dict(databases={}, messages={1: {}, 2: {}, 3: {}}, graphs=[], panel=None)
        issues = []
        for bus in (1, 2, 3):
            prepared['databases'][bus] = []
            for entry in data['databases'][str(bus)]:
                try:
                    raw = decode_db(entry)
                    db = self.main.parse_database_bytes(entry['name'], raw)
                    prepared['databases'][bus].append((entry, raw, db))
                    for msg in db.messages:
                        prepared['messages'][bus].setdefault(msg.frame_id, msg)
                except Exception as exc:
                    issues.append(f'BUS {bus} / {entry["name"]}: {exc}')
        for i, packet in enumerate(data['tx_packets']):
            try:
                if packet['bus'] not in (1, 2, 3):
                    raise ValueError('BUS는 1~3이어야 합니다.')
                if not isinstance(packet.get('symbol'), str) or not isinstance(packet.get('note'), str):
                    raise ValueError('심볼과 메모는 문자열이어야 합니다.')
                validate_packet(packet, prepared['messages'])
            except Exception as exc:
                issues.append(f'TX {i + 1}: {exc}')
        for i, state in enumerate(data['graphs']):
            graph = None
            try:
                validate_graph(state)
                for key, binding in state['bindings'].items():
                    self.resolve_binding(binding, prepared['databases'])
                graph = SignalGraphWindow(state['signals'], main_window=None)
                restore_graph(graph, state)
                prepared['graphs'].append(graph)
            except Exception as exc:
                if graph:
                    graph.close()
                    graph.deleteLater()
                issues.append(f'그래프 {i + 1}: {exc}')
        if data['panel'] is not None:
            try:
                validate_panel(data['panel']['data'])
                # No connected hardware or callbacks during validation/construction.
                proxy = SimpleNamespace(buses={1: None, 2: None, 3: None},
                                        db_messages=prepared['messages'])
                panel = UserPanelWindow(proxy, prepared['messages'],
                                        security_config=self.main.user_panel_security)
                prepared['panel'] = panel
                panel._load_panel_data(copy.deepcopy(data['panel']['data']))
                if strict:
                    # Restore editable, unfinished tools without allowing transmission.
                    # Packet corruption still rejects the file before readiness checks.
                    for packet in panel.tx_packets:
                        validate_packet(packet, prepared['messages'])
                    try:
                        panel._prepare_registered_packets()
                    except UnregisteredPacketError as exc:
                        panel.log_system(f'패널 복원 완료 / 송신 준비 미완료: {exc} RUN 전에 TX 패킷 등록/연결이 필요합니다.', 'WARN')
                for cfg in panel.widgets_config:
                    if cfg.get('widget_type') == 'sequence':
                        binding = cfg.get('binding', {})
                        validate_steps(binding.get('sequence_steps', []), allow_empty=True)
                        validate_steps(binding.get('sequence_failure_steps', []), actions_only=True, allow_empty=True)
                panel.stop_panel_commands('통합 복원')
                panel._packet_runtimes.clear()
                panel.mode = 'standby'
                panel.refresh_mode_ui()
                restore_geometry(panel, data['panel'].get('geometry'))
            except Exception as exc:
                issues.append(f'UserPanel: {exc}')
        if issues:
            self.dispose(prepared)
            raise ValueError('\n'.join(issues))
        return prepared

    @staticmethod
    def dispose(prepared):
        from PyQt5 import sip
        for window in prepared.get('graphs', []) + ([prepared['panel']] if prepared.get('panel') else []):
            if not sip.isdeleted(window):
                window.close()
                window.deleteLater()

    @staticmethod
    def resolve_binding(binding, databases):
        for entry, raw, db in databases[int(binding['bus'])]:
            if entry['id'] != binding['database']:
                continue
            for msg in db.messages:
                if msg.frame_id == binding['id'] and msg.is_extended_frame == binding['extended']:
                    return msg, msg.get_signal_by_name(binding['signal'])
        raise ValueError(f'그래프 신호를 찾을 수 없습니다: {binding}')

    def bind_signal(self, bus, can_id, signal):
        listing = self.main.list_db_files[bus]
        active = self.main.db_messages[bus].get(can_id)
        for i in range(listing.count()):
            item = listing.item(i)
            for msg in item.data(Qt.UserRole).messages:
                if msg is active and any(s.name == signal for s in msg.signals):
                    ident = item.data(Qt.UserRole + 3)
                    key = f'B{bus}:{can_id:X}:{int(msg.is_extended_frame)}:{signal}'
                    return key, dict(bus=bus, database=ident, id=can_id,
                                     extended=msg.is_extended_frame, signal=signal)
        raise ValueError(f'BUS {bus} / {can_id:X} / {signal}: DB 신호를 찾을 수 없습니다.')

    def stop_all(self):
        m = self.main
        m.tx_panel.stop_all_timers()
        panel = m.user_panel_window
        if panel is not None:
            panel.stop_panel_commands('전체 송신 정지')
            panel._sim_timer.stop()
            panel.mode = 'standby'
            panel.refresh_mode_ui()
        for viewer in list(m.log_viewers):
            viewer.stop_sending()

    def preserve_record(self):
        record = self.main.record_window
        from PyQt5 import sip
        if record is not None and sip.isdeleted(record):
            self.main.record_window = None
            return
        if record and record.isVisible() and not record.is_saved and record.msg_count:
            # Write before stopping/closing anything; a disk failure leaves the recording open.
            folder = self.directory / 'Log'
            target = folder / f'CAN_Log_{uuid.uuid4().hex}.trc'
            atomic_write(target, ('\n'.join(record.log_lines) + '\n').encode('utf-8'))
            record.is_saved = True

    def clear_live(self):
        m = self.main
        self.stop_all()
        m._session_generation += 1
        for viewer in list(m.log_viewers):
            viewer.close()
            viewer.deleteLater()
        if m.record_window:
            m.record_window.close()
            m.record_window = None
        if m.combined_view_window:
            combined = m.combined_view_window
            combined.close()  # Restore widget ownership before disposing graphs.
            combined.deleteLater()
        for graph in m.active_graphs:
            graph.close()
            graph.deleteLater()
        m.active_graphs = []
        m.synced_graphs_ordered = []
        m.combined_view_window = None
        if m.user_panel_window:
            m.user_panel_window.close()
            m.user_panel_window.deleteLater()
            m.user_panel_window = None
        m.close_can()
        m.tree.clear()
        m.signal_tree_items.clear()
        m.signal_choices.clear()
        m.msg_tree_items.clear()
        m.user_tx_cache.clear()
        m.user_frame_properties.clear()
        m._graph_pending_frames.clear()
        m.tx_panel.tree.clear()
        for bus in (1, 2, 3):
            m.list_db_files[bus].clear()
            m.db_messages[bus].clear()

    def apply_can(self, bus, cfg):
        m = self.main
        combo = m.combo_channels[bus]
        desired = cfg['device']
        index = next((i for i in range(combo.count())
                      if desired is not None and device_identity(combo.itemData(i)) == desired), -1)
        if index < 0:
            combo.setCurrentIndex(-1)
        else:
            combo.setCurrentIndex(index)
        m.on_channel_changed(bus)
        errors = []
        if desired is not None and index < 0:
            errors.append('저장된 장치를 찾을 수 없습니다')
        if desired is None and cfg['is_open']:
            errors.append('장치 정보가 없습니다')
        fd = cfg['data_bitrate'] not in ('Off', 'N/A', '')
        if fd and (index < 0 or not (combo.currentData() or {}).get('is_fd', False)):
            errors.append('장치가 CAN FD를 지원하지 않습니다')
        for widget, value in ((m.combo_bitrate[bus], cfg['bitrate']),
                              (m.combo_fd_iso[bus], cfg['fd_iso']),
                              (m.combo_data_bitrate[bus], cfg['data_bitrate'])):
            i = widget.findText(value)
            if i < 0 and value in ('Off', 'N/A'):
                i = widget.findText('Off' if value == 'N/A' else 'N/A')
            if i < 0:
                errors.append(f'지원하지 않는 설정: {value}')
                widget.addItem(value, None)
                widget.setCurrentIndex(widget.count() - 1)
            else:
                widget.setCurrentIndex(i)
        if not errors and cfg['is_open']:
            try:
                m.open_can(bus)
            except Exception as exc:
                errors.append(str(exc))
            if m.buses[bus] is None:
                errors.append('재연결에 실패했습니다')
        if errors:
            m.close_can(bus)
            self.errors.append(f'BUS {bus}: Close — ' + '; '.join(errors))
        actual = dict(device=device_identity(combo.currentData()), channel=combo.currentText(),
                      bitrate=m.combo_bitrate[bus].currentText(), fd_iso=m.combo_fd_iso[bus].currentText(),
                      data_bitrate=m.combo_data_bitrate[bus].currentText(), is_open=m.buses[bus] is not None)
        if errors:
            self.pending_can[bus] = (copy.deepcopy(cfg), actual)

    def apply(self, data, prepared):
        m = self.main
        self.clear_live()
        m.search_can_channels()
        self.pending_can.clear()
        for bus in (1, 2, 3):
            for entry, raw, db in prepared['databases'][bus]:
                m.install_database(db, bus, entry['name'], raw, '', entry['id'])
        for packet in data['tx_packets']:
            packet = copy.deepcopy(packet)
            packet['count'] = 0
            m.tx_panel.add_packet_to_tree(packet)
        panel = prepared['panel']
        if panel:
            panel.main_window = m
            panel.db_messages = m.db_messages
            m.user_panel_window = panel
            if data['panel'].get('visible', False) or getattr(m, 'user_panel_only', False):
                panel.show()
        for graph in prepared['graphs']:
            graph.main_window = m
            graph._bound_signals = m.resolve_graph_bindings(graph.signal_bindings)
            m.active_graphs.append(graph)
            graph._panel_only_hidden = bool(getattr(m, 'user_panel_only', False))
            if not getattr(m, 'user_panel_only', False):
                graph.show()
        for bus in (1, 2, 3):
            self.apply_can(bus, data['can'][str(bus)])
        m.btn_open_log.setEnabled(any(m.db_messages.values()))
        m.tx_panel.update_all_action_buttons()

    def load(self, path):
        if self.main.viewer_only or self.busy:
            return False
        prepared = backup_prepared = None
        try:
            data = read_session(path)
            prepared = self.prepare(data)
            backup = self.capture()
            backup_prepared = self.prepare(backup, strict=False)
            self.preserve_record()
        except Exception as exc:
            if prepared:
                self.dispose(prepared)
            if backup_prepared:
                self.dispose(backup_prepared)
            self.report('불러오기 실패', '기존 설정과 창을 유지했습니다.', str(exc).splitlines())
            return False
        self.busy = True
        self.errors = []
        success = False
        try:
            self.apply(data, prepared)
            success = True
        except Exception as exc:
            self.errors.append(f'설정 적용 실패: {exc}')
            try:
                self.apply(backup, backup_prepared)
                backup_prepared = None
                self.errors.append('이전 설정을 복원했습니다. 송신은 정지 상태이며 로그뷰는 다시 열어야 합니다.')
            except Exception as rollback_exc:
                self.enabled = False
                self.errors.append(f'이전 설정 복구 실패: {rollback_exc}. 자동 저장을 중지했습니다.')
            # Staged windows not yet attached when apply failed also need disposal.
            self.dispose(prepared)
        finally:
            if backup_prepared:
                self.dispose(backup_prepared)
            self.busy = False
        if success:
            self.enabled = True
            try:
                raw = serialize(self.capture())
                atomic_write(self.autosave_path, raw)
                self.last_digest = hashlib.sha256(raw).digest()
            except Exception as exc:
                self.errors.append(f'화면 적용은 완료했지만 자동 복원 파일 저장 실패: {exc}')
            self.main.statusBar().showMessage('통합 설정 적용 완료 · 전체 송신 정지', 10000)
        issues, self.errors = self.errors, None
        if issues:
            status = [f'BUS {b}: {"Open" if self.main.buses[b] else "Close"}' for b in (1, 2, 3)]
            self.report('통합 불러오기 결과',
                        '설정을 적용했습니다. 아래 항목을 확인하세요.' if success else '설정 적용에 실패했습니다.',
                        issues + status)
        return success

    def export_databases(self, bus=None, selected=False):
        m = self.main
        entries = []
        for b in ((bus,) if bus else (1, 2, 3)):
            listing = m.list_db_files[b]
            items = listing.selectedItems() if selected else [listing.item(i) for i in range(listing.count())]
            entries.extend((b, item) for item in items)
        if not entries:
            m.statusBar().showMessage('내보낼 DB를 선택/등록하세요.', 5000)
            return
        folder = QFileDialog.getExistingDirectory(m, 'DBC/SYM 내보내기', str(self.directory))
        if not folder:
            return
        issues = []
        for b, item in entries:
            try:
                target_dir = Path(folder) / f'BUS{b}'
                target_dir.mkdir(parents=True, exist_ok=True)
                name = Path(item.text()).name
                raw = item.data(Qt.UserRole + 2)
                if raw is None:
                    raise ValueError('DB 원문이 없습니다.')
                stem, suffix = os.path.splitext(name)
                for n in range(100000):
                    target = target_dir / (name if n == 0 else f'{stem}_{n}{suffix}')
                    try:
                        with target.open('xb') as stream:
                            stream.write(bytes(raw))
                        break
                    except FileExistsError:
                        continue
                else:
                    raise ValueError('중복되지 않는 파일명을 만들 수 없습니다.')
            except Exception as exc:
                issues.append(f'BUS {b} / {item.text()}: {exc}')
        if issues:
            self.report('DB 내보내기 결과', '일부 파일을 내보내지 못했습니다.', issues)
        else:
            m.statusBar().showMessage(f'DB {len(entries)}개 내보내기 완료: {folder}', 10000)
