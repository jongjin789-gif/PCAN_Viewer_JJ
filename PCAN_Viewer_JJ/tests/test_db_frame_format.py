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
from src.main_window import UniversalCANMonitor, _signal_display_decimals
from cantools.database.can import Signal
from cantools.database.conversion import BaseConversion


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

    def test_uppercase_sym_offset_keeps_negative_scale_and_enum_labels(self):
        content = '''FormatVersion=6.0
Title="Offset compatibility"
{ENUMS}
Enum=State(0="/O: unchanged", 1="ON")
{SENDRECEIVE}
[Example]
ID=02Ah
Type=FDStandard
Len=48
Var=Accel unsigned 312,16 /u:g /f:0.001 /O:-32.767 // /O: comment
Var=State unsigned 0,1 /e:State
Var=Positive unsigned 16,8 /o:2.5
'''
        for version, loader in [('6.0', UniversalCANMonitor._load_sym_v6),
                                ('5.0', UniversalCANMonitor._load_sym_v5)]:
            with self.subTest(version=version), patch('builtins.open', mock_open(
                    read_data=content.replace('FormatVersion=6.0', f'FormatVersion={version}'))):
                db = loader(None, 'offset.sym')
            msg = db.get_message_by_frame_id(0x2A)
            signal = msg.get_signal_by_name('Accel')
            self.assertTrue(msg.is_fd)
            self.assertEqual(msg.length, 48)
            self.assertEqual((signal.start, signal.length, signal.scale, signal.offset),
                             (312, 16, 0.001, -32.767))
            self.assertEqual(msg.get_signal_by_name('Positive').offset, 2.5)
            self.assertEqual(str(msg.get_signal_by_name('State').choices[0]), '/O: unchanged')
            payload = bytearray(48)
            payload[39:41] = (32767).to_bytes(2, 'little')
            self.assertAlmostEqual(msg.decode(payload, decode_choices=False)['Accel'], 0)

    def test_signal_display_precision_covers_dbc_factor_and_offset(self):
        signal = Signal("Angle", 71, 16, byte_order="big_endian",
                        conversion=BaseConversion.factory(scale=0.0625, offset=-780.125))
        self.assertEqual(_signal_display_decimals(signal), 4)

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
