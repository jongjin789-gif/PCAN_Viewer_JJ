"""Generate and validate the BUS1 monitoring panel without transmitting CAN."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from src.db_frame_format import load_sym_with_fd
from src.user_panel_v2.binding import validate_config
from src.user_panel_v2.packets import validate_packet, validate_tool
from src.user_panel_v2.window import UserPanelWindow
from PyQt5.QtWidgets import QApplication

source = ROOT / 'dbc/BUS1/HL_Mando_V2_VCU_CAN1_Monitoring.sym'
db = load_sym_with_fd(source.read_text(encoding='utf-8-sig'))
messages = {m.frame_id: m for m in db.messages}
rx = [messages[i] for i in range(0x130, 0x13e) if i in messages]
widgets = []

def widget(ident, kind, title, row, col, height, width, parent=None, behavior='none', binding=None, **extra):
    cfg = dict(id=ident, page_id='main', widget_type=kind, title=title,
               row=row, col=col, row_span=height, col_span=width,
               parent_id=parent, behavior=behavior, binding=binding or {},
               z_index=1 if parent else 0, primary_enabled=True, tx_commands=[])
    cfg.update(extra)
    widgets.append(cfg)
    return cfg

def binding(message, signal):
    low = -(1 << (signal.length - 1)) if signal.is_signed else 0
    high = (1 << (signal.length - int(signal.is_signed))) - 1
    return dict(bus=1, can_id=message.frame_id, dlc=message.length,
                is_fd=False, brs=False, signal_name=signal.name,
                start_bit=signal.start, bit_length=signal.length,
                byte_order=signal.byte_order, signed=signal.is_signed,
                scale=signal.scale, offset=signal.offset,
                min=signal.minimum if signal.minimum is not None else low * signal.scale + signal.offset,
                max=signal.maximum if signal.maximum is not None else high * signal.scale + signal.offset,
                unit=signal.unit or '', value_precision_decimals=3)

widget('rx-tabs', 'tab_container', 'BUS1 RX', 0, 0, 46, 62,
       tabs=[f'0x{m.frame_id:03X} {m.name.removeprefix("VCU_")}' for m in rx])
for index, message in enumerate(rx):
    for j, signal in enumerate(message.signals):
        # Three columns; coordinates refer to the container's 48 x 96 local grid.
        widget(f'rx-{message.frame_id:x}-{signal.name}', 'label', signal.name,
               (j // 3) * 6, (j % 3) * 32, 6, 32, 'rx-tabs', 'rx',
               binding(message, signal), tab_index=index)

widget('tx-group', 'group_box', 'BUS1 TX | 0x100 VCU_CTRL_MD_CMD | 20 ms',
       0, 63, 46, 33)
tx = messages[0x100]
signals = [s for s in tx.signals if s.name != 'B00_Alive_Counter']
for j, signal in enumerate(signals):
    b = binding(tx, signal)
    b.update(packet_id='pkt-b1-100', tx_resolution=signal.scale,
             tx_initial_value=0, tx_on_value=1, tx_off_value=0)
    widget(f'tx-{signal.name}', 'spinbox', signal.name, (j // 2) * 6,
           (j % 2) * 48, 6, 48, 'tx-group', 'tx', b)
for j, kind in enumerate(('START', 'STOP')):
    widget(f'tx-{kind.lower()}', 'sequence', f'{kind} 0x100', 37, j * 48,
           11, 48, 'tx-group', 'tx',
           dict(sequence_steps=[dict(kind=kind, target_packet_id='pkt-b1-100', name=f'{kind} 20 ms TX')],
                sequence_failure_steps=[]))

packet = dict(packet_id='pkt-b1-100', bus=1, id=256, is_extended_id=False,
              is_fd=False, is_brs=False, length=8, data=[0]*8, cycle=20,
              symbol=tx.name, note='Alive Counter: Upcount 0..15, step 1',
              count=0, crc_type='N/A',
              signal_counters={'B00_Alive_Counter': dict(mode='up', min=0, max=15, step=1)})
data = dict(version=5, title='HL Mando V2 VCU CAN1 Monitoring',
            dbc_signature={'1': ['.sym:' + hashlib.sha256(source.read_bytes()).hexdigest()],
                           '2': [], '3': [], '4': []},
            pages=[dict(id='main', name='VCU CAN1')], active_page_id='main',
            tx_packets=[packet], init_steps=[dict(kind='STOP', target_packet_id='*', name='Stop all TX')],
            grid=dict(rows=48, cols=96, cell_size=32), mode='standby',
            widgets=widgets, channel_settings={})
db_messages = {1: messages, 2: {}, 3: {}, 4: {}}
validate_packet(packet, db_messages)
for cfg in widgets:
    validate_config(cfg)
    validate_tool(data['tx_packets'], copy.deepcopy(cfg))
app = QApplication.instance() or QApplication([])
panel = UserPanelWindow(SimpleNamespace(buses={}, bus_capabilities={},
                        database_content_signature=data['dbc_signature']), db_messages)
panel._load_panel_data(copy.deepcopy(data))
panel._prepare_registered_packets()
tabs = panel.widget_controls['rx-tabs']
assert tabs.count() == len(rx)
for index, message in enumerate(rx):
    assert tabs.widget(index).layout().count() == len(message.signals)
    for signal in message.signals:
        frame = panel.widget_frames[f'rx-{message.frame_id:x}-{signal.name}']
        assert frame.parentWidget() is tabs.widget(index)
assert len(panel.widgets_config) == len(widgets)
saved = panel._panel_data()
assert next(w for w in saved['widgets'] if w['id'] == 'rx-tabs')['tabs'] == widgets[0]['tabs']
assert [w.get('tab_index') for w in saved['widgets']] == [w.get('tab_index') for w in panel.widgets_config]
panel.close()
output = Path(__file__).with_name('HL_Mando_V2_VCU_CAN1_Monitoring.upp.json')
output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(f'Validated {len(rx)} RX tabs, {sum(len(m.signals) for m in rx)} RX signals, {len(signals)} TX controls; no CAN transmission.\n{output}')
