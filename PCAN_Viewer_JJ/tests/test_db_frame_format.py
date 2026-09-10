import os
import unittest
from pathlib import Path
from unittest.mock import mock_open, patch
from types import SimpleNamespace
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtWidgets import QApplication
from src.db_frame_format import load_sym_with_fd, message_is_fd
from src.tx_panel import TxPacketDialog
from src.main_window import UniversalCANMonitor


class FrameFormatTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_eight_byte_sym_formats(self):
        for frame_type, expected in [('FDStandard', True), ('FD CAN', True), ('FDExtended', True), ('Standard', False)]:
            content = f'FormatVersion=6.0\n{{SEND}}\n[Test]\nID=123h\nType={frame_type}\nLen=8\n'
            msg = load_sym_with_fd(content).messages[0]
            self.assertEqual(msg.is_fd, expected)
            self.assertEqual(msg.is_extended_frame, frame_type == 'FDExtended')
            dialog = TxPacketDialog({1: {msg.frame_id: msg}})
            dialog.combo_symbol.setCurrentIndex(1)
            self.assertEqual(dialog.combo_type.currentText(), 'FD' if expected else 'Classic')
            self.assertEqual(dialog.check_brs.isEnabled(), expected)
            self.assertEqual(dialog.combo_length.currentText(), '8')
            self.assertEqual(dialog.get_packet_data()['is_fd'], expected)
            dialog.close()

    def test_dbc_frame_format_aliases(self):
        for label in ('FDStandard', 'FD CAN', 'StandardCAN_FD'):
            attr = SimpleNamespace(value=1, definition=SimpleNamespace(choices=['StandardCAN', label]))
            msg = SimpleNamespace(is_fd=False, length=8, dbc=SimpleNamespace(attributes={'VFrameFormat': attr}))
            self.assertTrue(message_is_fd(msg))

    def test_user_sym_title_brs_and_signal_metadata(self):
        content = Path(__file__).with_name('fd_rwa.sym').read_text(encoding='utf-8')
        for version, loader in [('6.0', UniversalCANMonitor._load_sym_v6), ('5.0', UniversalCANMonitor._load_sym_v5)]:
            source = content.replace('FormatVersion=6.0', f'FormatVersion={version}')
            with patch('builtins.open', mock_open(read_data=source)):
                db = loader(None, 'example.sym')
            self.assertEqual([(m.frame_id, m.length, m.is_fd) for m in db.messages],
                             [(0x147, 32, True), (0x71D, 64, True), (0x163, 32, True), (0x715, 64, True)])
            sig = db.get_message_by_name('ADC_3').get_signal_by_name('ADC_PinionAgCmd')
            # SYM Motorola start 64 maps to cantools' sawtooth MSB position 71.
            self.assertEqual((sig.start, sig.length, sig.scale, sig.offset), (71, 16, 0.0625, -780))
            self.assertEqual(sig.byte_order, 'big_endian')
