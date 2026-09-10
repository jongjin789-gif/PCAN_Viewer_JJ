import copy
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest
from cantools.database.can import Message, Signal
from src.user_panel_v2.packets import PacketRuntime, RegisteredPacketDialog, bind_packet
from src.user_panel_v2.window import UserPanelWindow
from src.user_panel_v2.config_dialog import WidgetConfigDialog
from src.crc_utils import calculate_crc16_ccitt_false


def packet(ident='p', can_id=0x123, cycle=20):
    return dict(packet_id=ident, bus=1, id=can_id, length=8, is_fd=False, is_brs=False,
                data=[0xAA] * 8, cycle=cycle, symbol='Test', note='', count=0, crc_type='N/A')


def tool(p, ident='tool', start=24, kind='slider'):
    binding = dict(start_bit=start, bit_length=8, byte_order='little_endian', scale=1,
                   offset=0, min=0, max=255, tx_initial_value=7, tx_release_value=0,
                   tx_off_value=0, tx_on_value=1, tx_press_value=1)
    bind_packet(binding, p)
    return dict(id=ident, widget_type=kind, behavior='tx', binding=binding, title=ident,
                row=0, col=0, row_span=3, col_span=4)


class PanelPacketTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def panel(self, packets, configs=(), db=None):
        self.sent = []
        main = SimpleNamespace(buses={1: SimpleNamespace(send=self.sent.append)},
                               bus_capabilities={1: {'is_fd': True}}, record_tx_activity=lambda *args: None)
        panel = UserPanelWindow(main, db or {})
        panel._load_panel_data(dict(tx_packets=copy.deepcopy(packets), widgets=copy.deepcopy(list(configs))))
        panel.show()
        self.app.processEvents()
        self.addCleanup(panel.close)
        return panel

    def test_run_starts_packets_without_tools_and_standard_stops(self):
        p = packet()
        panel = self.panel([p])
        panel.set_mode('run')
        QTest.qWait(65)
        self.assertGreaterEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0].data, bytes(p['data']))
        panel.set_mode('standard')
        count = len(self.sent)
        QTest.qWait(50)
        self.assertEqual(len(self.sent), count)
        self.assertFalse(panel._frame_timers)

    def test_zero_only_changed_bits_and_all_tool_overlays(self):
        p = packet(cycle=0)
        a, b = tool(p), tool(p, 'second', start=32, kind='toggle')
        panel = self.panel([p], [a, b])
        panel.set_mode('run')
        self.assertEqual(self.sent, [])
        panel._emit_tx(a, 7)
        self.assertEqual(self.sent, [])
        panel._emit_tx(a, 20)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[-1].data, bytes([0xAA] * 3 + [20, 0] + [0xAA] * 3))
        panel._emit_tx(a, 20)
        self.assertEqual(len(self.sent), 1)
        panel._emit_tx(b, 1)
        self.assertEqual(self.sent[-1].data[3:5], bytes([20, 1]))
        self.assertEqual(panel.tx_packets[0]['data'], p['data'])
        panel.set_mode('standby')
        panel._emit_tx(a, 21)
        self.assertEqual(len(self.sent), 2)

    def test_periodic_initial_tool_value_and_counter_then_crc(self):
        p = packet()
        p['data'] = [0, 0, 0, 0, 0xAA, 0xAA, 0xAA, 0xAA]
        p['signal_counters'] = {
            'Count': dict(mode='up', min=0, max=255, step=1),
            'CRC': dict(mode='crc16', start=2, size=6, extra=[0, 0], poly=0x1021,
                        init=0xFFFF, xorout=0, refin=False, refout=False)}
        msg = Message(p['id'], 'Test', 8, [Signal('CRC', 0, 16), Signal('Count', 16, 8), Signal('Value', 24, 8)])
        panel = self.panel([p], [tool(p)], {1: {p['id']: msg}})
        panel.set_mode('run')
        panel._flush_frame('p')
        panel._flush_frame('p')
        self.assertEqual([m.data[2] for m in self.sent], [0, 1])
        for m in self.sent:
            self.assertEqual(m.data[3], 7)
            self.assertEqual(m.data[4:], bytes([0xAA] * 4))
            self.assertEqual(int.from_bytes(m.data[:2], 'little'), calculate_crc16_ccitt_false(m.data[2:] + b'\0\0'))

    def test_failed_send_keeps_counter_state(self):
        p = packet()
        p['data'][0] = 3
        p['signal_counters'] = {'Value': dict(mode='up', min=0, max=10, step=1)}
        msg = Message(p['id'], 'Test', 8, [Signal('Value', 0, 8)])
        panel = self.panel([p], db={1: {p['id']: msg}})
        runtime = PacketRuntime(p, panel.db_messages, panel.main_window)
        with patch.object(panel.main_window.buses[1], 'send', side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError):
                runtime.send()
        self.assertEqual(runtime.states, {})
        runtime.send()
        self.assertEqual(self.sent[0].data[0], 3)

    def test_registration_required_delay_and_tx_filter_rx_unchanged(self):
        dialog = RegisteredPacketDialog({})
        with self.assertRaises(ValueError):
            dialog.get_packet_data()
        dialog.edit_cycle.setValue(0)
        self.assertEqual(dialog.get_packet_data()['cycle'], 0)
        dialog.close()
        db = {1: {1: Message(1, 'Registered', 8, []), 2: Message(2, 'Other', 8, [])}}
        p = packet(can_id=1)
        tx = WidgetConfigDialog(db, fixed_behavior='tx', tx_packets=[p])
        self.assertEqual([tx.combo_message.itemData(i) for i in range(tx.combo_message.count())], [1])
        self.assertNotIn('tx_cycle_ms', tx.get_config()['binding'])
        self.assertNotIn('tx_cycle_mode', tx.get_config()['binding'])
        self.assertFalse(hasattr(tx, 'combo_tx_cycle_mode'))
        rx = WidgetConfigDialog(db, fixed_behavior='rx', tx_packets=[p])
        self.assertEqual([rx.combo_message.itemData(i) for i in range(rx.combo_message.count())], [None, 1, 2])
        tx.close()
        rx.close()

    def test_packet_save_restore_and_batch_rebind(self):
        p, q = packet(), packet('q', 0x456, 0)
        panel = self.panel([p, q], [tool(p, 'a'), tool(p, 'b', 32)])
        panel.selected_widget_ids = {'a', 'b'}
        panel.properties.refresh(force=True)
        props = panel.properties
        self.assertNotIn('tx_cycle_ms', props.fields)
        self.assertNotIn('is_fd', props.fields)
        props.checks['packet_id'].setChecked(True)
        props.fields['packet_id'].setCurrentIndex(props.fields['packet_id'].findData('q'))
        props.apply_checked()
        self.assertTrue(all(c['binding']['packet_id'] == 'q' for c in panel.widgets_config))
        saved = copy.deepcopy(panel._panel_data())
        panel._load_panel_data(saved)
        self.assertEqual(panel.tx_packets, [p, q])
        self.assertTrue(all(c['binding']['packet_id'] == 'q' for c in panel.widgets_config))

    def test_unregistered_legacy_tool_blocks_run(self):
        panel = self.panel([], [tool(packet())])
        with patch('src.user_panel_v2.window.QMessageBox.warning') as warning:
            panel.set_mode('run')
            warning.assert_called_once()
        self.assertNotEqual(panel.mode, 'run')
        self.assertFalse(self.sent)

    def test_run_reentry_preserves_selected_toggle_and_starts_periodic(self):
        p = packet(cycle=10)
        a, b = tool(p, 'a', kind='toggle'), tool(p, 'b', kind='toggle')
        a['binding']['tx_on_value'] = 15
        b['binding']['tx_on_value'] = 25
        panel = self.panel([p], [a, b])
        panel.set_mode('run')
        panel.widget_controls['a'].setChecked(True)
        panel.set_mode('standard')
        self.sent.clear()
        panel.set_mode('run')
        QTest.qWait(30)
        self.assertTrue(self.sent)
        self.assertTrue(all(m.data[3] == 15 for m in self.sent))

    def test_packet_edit_rebinds_tools_and_history_restores_registry(self):
        from src.user_panel_v2.packets import validate_tool
        p = packet()
        panel = self.panel([p], [tool(p)])
        panel.tx_packets[0].update(id=0x456, is_fd=True, is_brs=True, cycle=50)
        validate_tool(panel.tx_packets, panel.widgets_config[0])
        panel.rebuild_grid()
        b = panel.widgets_config[0]['binding']
        self.assertEqual((b['can_id'], b['is_fd'], b['brs']), (0x456, True, True))
        panel.undo_edit()
        self.assertEqual(panel.tx_packets[0]['id'], 0x123)
        self.assertEqual(panel.widgets_config[0]['binding']['can_id'], 0x123)
        panel.redo_edit()
        self.assertEqual(panel.tx_packets[0]['cycle'], 50)
