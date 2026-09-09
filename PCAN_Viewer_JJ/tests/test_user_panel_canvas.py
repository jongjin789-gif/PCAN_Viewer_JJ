import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QPoint
from PyQt5.QtWidgets import QApplication
from src.user_panel_v2.window import UserPanelWindow


class PanelCanvasTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_resize_grows_tools_but_preserves_minimum_grid_size(self):
        panel = UserPanelWindow(SimpleNamespace(), {})
        panel._load_panel_data({
            "grid": {"rows": 36, "cols": 36},
            "widgets": [{"id": "button", "widget_type": "button", "behavior": "tx",
                         "row": 2, "col": 3, "row_span": 3, "col_span": 5}],
        })
        panel.show()
        self.app.processEvents()
        canvas_size = panel.canvas.size()
        frame_rect = panel.widget_frames["button"].geometry()
        control_size = panel.widget_controls["button"].size()
        for width, height in ((800, 600), (1000, 700)):
            panel.resize(width, height)
            self.app.processEvents()
            self.assertEqual(panel.canvas.size(), canvas_size)
            self.assertEqual(panel.widget_frames["button"].geometry(), frame_rect)
            self.assertEqual(panel.widget_controls["button"].size(), control_size)
        scroll = panel.canvas_scroll
        self.assertGreater(scroll.horizontalScrollBar().maximum(), 0)
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
        scroll.horizontalScrollBar().setValue(100)
        scroll.verticalScrollBar().setValue(100)
        point = QPoint(3 * 32 + 1, 2 * 32 + 1)
        self.assertEqual(panel._cell_from_global_in_parent(None, panel.canvas.mapToGlobal(point)), (2, 3))
        saved = panel._panel_data()
        panel._load_panel_data(saved)
        self.assertEqual(panel.canvas.size(), canvas_size)
        panel.resize(2000, 1700)
        self.app.processEvents()
        self.assertGreater(panel.canvas.width(), canvas_size.width())
        self.assertGreater(panel.canvas.height(), canvas_size.height())
        self.assertEqual(panel.canvas.size(), scroll.viewport().size())
        self.assertGreater(panel.widget_controls["button"].width(), control_size.width())
        self.assertGreater(panel.widget_controls["button"].height(), control_size.height())
        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
        self.assertEqual(scroll.verticalScrollBar().maximum(), 0)
        panel.resize(1000, 700)
        self.app.processEvents()
        self.assertEqual(panel.canvas.size(), canvas_size)
        self.assertEqual(panel.widget_frames["button"].geometry(), frame_rect)
        panel._load_panel_data({"grid": {"rows": 12, "cols": 12}, "widgets": []})
        self.app.processEvents()
        self.assertEqual(panel.canvas.minimumWidth(), 12 * 32)
        self.assertGreaterEqual(panel.canvas.width(), 12 * 32)
        self.assertEqual(panel.canvas_layout.rowMinimumHeight(35), 0)
        panel.close()
        panel.deleteLater()


if __name__ == "__main__":
    unittest.main()
