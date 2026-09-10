"""Registered TX packets, bit overlays, and panel-owned transmission state."""
import copy
import uuid
import can
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                             QListWidget, QDialogButtonBox, QMessageBox, QComboBox, QSpinBox, QLabel)
from src.tx_panel import TxPacketDialog
from src.tx_counter import counter_payload
from src.crc_utils import calculate_crc16_ccitt_false
from .binding import pack_value, bit_positions


def validate_packet(packet, db_messages):
    n = packet['length']
    if n not in (list(range(9)) + ([12, 16, 20, 24, 32, 48, 64] if packet['is_fd'] else [])) or len(packet['data']) != n:
        raise ValueError('등록 패킷의 데이터 길이를 확인하세요.')
    if type(packet.get('cycle')) is not int or not 0 <= packet['cycle'] <= 600000:
        raise ValueError('패킷 딜레이는 0~600000 ms로 입력하세요.')
    can.Message(arbitration_id=packet['id'], data=packet['data'], is_fd=packet['is_fd'],
                is_extended_id=packet.get('is_extended_id', packet['id'] > 0x7FF),
                bitrate_switch=packet.get('is_brs', False), check=True)
    if packet.get('crc_type') == 'Hyundai_CRC' and (n < 3 or packet['id'] + 0xF800 > 65535):
        raise ValueError('Hyundai CRC는 3바이트 이상 및 호환 가능한 CAN ID가 필요합니다.')
    if packet.get('signal_counters'):
        msg = db_messages.get(packet['bus'], {}).get(packet['id'])
        if msg is None:
            raise ValueError('카운트/CRC 신호가 포함된 DBC/SYM을 불러오세요.')
        try:
            counter_payload(msg, bytes(packet['data']), packet['signal_counters'], {})
        except Exception as exc:
            raise ValueError(f'등록 패킷의 카운트/CRC 설정을 확인하세요: {exc}') from exc


def find_packet(packets, binding):
    packet_id = binding.get('packet_id')
    if packet_id:
        return next((p for p in packets if p['packet_id'] == packet_id), None)
    return next((p for p in packets if (p['bus'], p['id']) ==
                 (int(binding.get('bus', 1)), int(binding.get('can_id', 0)))), None)


def bind_packet(binding, packet):
    binding.update(packet_id=packet['packet_id'], bus=packet['bus'], can_id=packet['id'],
                   dlc=packet['length'], is_fd=packet['is_fd'], brs=packet.get('is_brs', False))
    binding.pop('tx_cycle_mode', None)
    binding.pop('tx_cycle_ms', None)


def validate_tool(packets, cfg):
    if cfg.get('behavior') != 'tx':
        return
    if cfg.get('widget_type') == 'sequence':
        for step in cfg.get('binding', {}).get('sequence_steps', []):
            if step.get('kind') == 'CMD':
                p = step.get('packet', {})
                packet = find_packet(packets, dict(packet_id=p.get('packet_id'), bus=p.get('bus', 1), can_id=p.get('id', 0)))
                if packet is None:
                    raise ValueError('시퀀스 CMD는 등록한 TX 패킷을 선택하세요.')
                step['packet'] = copy.deepcopy(packet)
        return
    binding = cfg['binding']
    packet = find_packet(packets, binding)
    if packet is None:
        raise ValueError(f"{cfg.get('title', 'TX')}: 먼저 TX 패킷을 등록하고 도구에 연결하세요.")
    bind_packet(binding, packet)
    bit_positions(binding, packet['length'])


class PacketRuntime:
    def __init__(self, packet, db_messages, main):
        self.packet = packet
        self.db_messages = db_messages
        self.main = main
        self.overlay = bytearray(packet['data'])
        self.states = {}
        self.alive = 0

    def stage(self, binding, value):
        updated = pack_value(self.overlay, binding, value)
        changed = updated != self.overlay
        self.overlay = updated
        return changed

    def send(self):
        p = self.packet
        bus = getattr(self.main, 'buses', {}).get(p['bus'])
        if bus is None:
            raise ValueError(f"CAN BUS {p['bus']}가 연결되지 않았습니다.")
        if p['is_fd'] and not self.main.bus_capabilities[p['bus']].get('is_fd'):
            raise ValueError(f"CAN BUS {p['bus']}를 FD로 연결하세요.")
        payload = bytes(self.overlay)
        states = self.states
        if p.get('signal_counters'):
            message = self.db_messages.get(p['bus'], {}).get(p['id'])
            if message is None:
                raise ValueError('카운트/CRC 신호가 포함된 DBC/SYM을 불러오세요.')
            payload, states = counter_payload(message, payload, p['signal_counters'], self.states)
        if p.get('crc_type') == 'Hyundai_CRC':
            body = bytes([self.alive]) + payload[3:]
            crc = calculate_crc16_ccitt_false(body + (0xF800 + p['id']).to_bytes(2, 'little'))
            payload = crc.to_bytes(2, 'little') + body
        message = can.Message(arbitration_id=p['id'], data=payload, is_fd=p['is_fd'],
                              bitrate_switch=p.get('is_brs', False),
                              is_extended_id=p.get('is_extended_id', p['id'] > 0x7FF), check=True)
        bus.send(message)
        self.states = states
        self.alive = (self.alive + 1) % 256
        if hasattr(self.main, 'record_tx_activity'):
            self.main.record_tx_activity(p['bus'], p['id'], payload, p['is_fd'])
        return payload


class RegisteredPacketDialog(TxPacketDialog):
    def __init__(self, db_messages, parent=None, packet=None):
        super().__init__(db_messages, parent)
        self.setWindowTitle('유저 패널 TX 패킷 등록')
        self.edit_cycle.setRange(-1, 600000)
        self.edit_cycle.setSpecialValueText('딜레이 입력 필요')
        self.edit_cycle.setSuffix(' ms (0=도구 값 변경 시 전송)')
        self.edit_cycle.setValue(-1)
        if packet:
            self.set_packet_data(packet)

    def get_packet_data(self):
        if self.edit_cycle.value() < 0:
            raise ValueError('패킷 딜레이를 입력하세요. 0은 도구 값이 변경될 때만 전송합니다.')
        packet = super().get_packet_data()
        validate_packet(packet, self.db_messages)
        return packet


class RegisteredCommandDialog(QDialog):
    def __init__(self, packets, step, parent=None):
        super().__init__(parent)
        self.setWindowTitle('등록 TX 패킷 선택')
        self.packets = packets
        layout = QVBoxLayout(self)
        self.combo = QComboBox()
        for packet in packets:
            self.combo.addItem(f"BUS {packet['bus']} · 0x{packet['id']:X} · {packet.get('symbol', 'N/A')}", packet['packet_id'])
        self.combo.setCurrentIndex(max(0, self.combo.findData(step.get('packet', {}).get('packet_id'))))
        layout.addWidget(self.combo)
        layout.addWidget(QLabel('반복 횟수 (간격은 등록 패킷의 딜레이 사용)'))
        self.repeat = QSpinBox()
        self.repeat.setRange(1, 10000)
        self.repeat.setValue(step.get('repeat', 1))
        layout.addWidget(self.repeat)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        if self.combo.currentIndex() < 0:
            QMessageBox.warning(self, 'TX 패킷', '먼저 TX 패킷을 등록하세요.')
            return
        packet = copy.deepcopy(self.packets[self.combo.currentIndex()])
        self.result_step = dict(kind='CMD', packet=packet, repeat=self.repeat.value(),
                                summary=f"BUS {packet['bus']} · 0x{packet['id']:X} · {packet['cycle']} ms")
        super().accept()


class PacketRegistryDialog(QDialog):
    def __init__(self, panel):
        super().__init__(panel)
        self.main_window = panel.main_window
        self.panel = panel
        self.packets = copy.deepcopy(panel.tx_packets)
        self.setWindowTitle('유저 패널 TX 패킷')
        self.resize(730, 420)
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        layout.addWidget(self.list)
        actions = QHBoxLayout()
        for label, callback in [('패킷 등록', lambda: self.edit_packet(False)),
                                ('선택 패킷 수정', lambda: self.edit_packet(True)),
                                ('선택 패킷 삭제', self.remove_packet)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.list.itemDoubleClicked.connect(lambda _: self.edit_packet(True))
        self.refresh()

    def refresh(self):
        self.list.clear()
        for p in self.packets:
            cycle = f"{p['cycle']} ms" if p['cycle'] else '값 변경 시'
            self.list.addItem(f"BUS {p['bus']} · 0x{p['id']:X} · {p.get('symbol', 'N/A')} · "
                              f"{'FD' if p['is_fd'] else 'Classic'} · {p['length']} bytes · {cycle}")

    def edit_packet(self, editing):
        row = self.list.currentRow()
        if editing and row < 0:
            return
        old = self.packets[row] if editing else None
        dlg = RegisteredPacketDialog(self.panel.db_messages, self, old)
        if dlg.exec_() != QDialog.Accepted:
            return
        packet = dlg.get_packet_data()
        packet['packet_id'] = old['packet_id'] if old else str(uuid.uuid4())
        if any(p['packet_id'] != packet['packet_id'] and (p['bus'], p['id']) == (packet['bus'], packet['id']) for p in self.packets):
            QMessageBox.warning(self, '패킷 등록', '같은 BUS와 CAN ID의 패킷이 이미 등록되어 있습니다.')
            return
        if editing:
            self.packets[row] = packet
        else:
            self.packets.append(packet)
        self.refresh()

    def remove_packet(self):
        row = self.list.currentRow()
        if row >= 0:
            packet = self.packets[row]
            if any(c.get('behavior') == 'tx' and find_packet([packet], c.get('binding', {})) for c in self.panel.widgets_config):
                QMessageBox.warning(self, '패킷 삭제', '연결된 TX 도구를 먼저 삭제하거나 다른 패킷에 연결하세요.')
                return
            del self.packets[row]
            self.refresh()
