import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtWidgets import QApplication, QTableWidgetItem
from PyQt5.QtTest import QTest
from src.log_viewer import LogViewerWindow
from src.can_threads import LogParserThread


class LogFilterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_extended_filter_send_and_original_export(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source.trc'
            header = b';$FILEVERSION=2.1\r\n; original header\r\n'
            rows = [b' 10 0.000 DT 1 0001 Rx - 1 AB\r\n',
                    b' 20 1.000 DT 1 001ABCDE Rx - 1 CD\r\n',
                    b' 30 2.000 DT 1 0002 Rx - 1 EF\r\n',
                    b' 40 3.000 DT 1 001ABCDE Rx - 1 12\r\n']
            source.write_bytes(header + b''.join(rows))
            results = []
            parser = LogParserThread(str(source), {})
            parser.finished_signal.connect(lambda *args: results.append(args[2]))
            parser.run()
            self.assertEqual(len(results[0]), 4)
            sent = []
            main = SimpleNamespace(buses={1: SimpleNamespace(send=sent.append)},
                                   bus_capabilities={1: {'is_fd': True}},
                                   record_tx_activity=lambda *a: None,
                                   statusBar=lambda: SimpleNamespace(showMessage=lambda *a: None))
            with patch.object(LogViewerWindow, 'start_parsing'):
                view = LogViewerWindow(str(source), {}, main)
            view.raw_log_data = results[0]
            view.log_table.setRowCount(4)
            for row, entry in enumerate(view.raw_log_data):
                for col in range(7):
                    view.log_table.setItem(row, col, QTableWidgetItem(str(row)))
                view.log_table.item(row, 4).setText(f"{entry['can_id']:X}")
            view.edit_filter_low.setText('0x001ABCDE')
            view.edit_filter_high.setText('0x001ABCDE')
            view.btn_filter.setChecked(True)
            self.assertEqual(len(view.get_visible_log_data()), 2)
            target = Path(folder) / 'filtered.trc'
            self.assertEqual(view.export_filtered_log(str(target)), 2)
            self.assertEqual(target.read_bytes(), header + rows[1].replace(b' 20 ', b' 1 ', 1) + rows[3].replace(b' 40 ', b' 2 ', 1))
            self.assertEqual(source.read_bytes(), header + b''.join(rows))
            view.start_sending()
            QTest.qWait(30)
            self.assertEqual([m.arbitration_id for m in sent], [0x1ABCDE, 0x1ABCDE])
            self.assertEqual([bytes(m.data) for m in sent], [b'\xCD', b'\x12'])
            self.assertTrue(all(m.is_extended_id for m in sent))
            view.stop_sending()
            view.deleteLater()
