import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication, QLabel, QPushButton, QSlider
from src.user_panel_v2.window import UserPanelWindow
from src.user_panel_v2.config_dialog import WidgetConfigDialog


class SliderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_precision_initial_and_home(self):
        panel = UserPanelWindow(SimpleNamespace(), {})
        sent = []
        panel._emit_tx = lambda cfg, value: sent.append(value)
        for resolution, expected in ((1, "5"), (0.1, "5.0"), (0.01, "5.00")):
            cfg = dict(widget_type="slider", behavior="tx", binding=dict(
                min=0, max=10, tx_resolution=resolution, tx_initial_value=5))
            ctrl, _ = panel._create_runtime_widget(cfg)
            slider = ctrl.findChild(QSlider)
            label = ctrl.findChild(QLabel, "value_label")
            home = ctrl.findChild(QPushButton, "slider_home")
            self.assertEqual(label.text(), expected)
            sent.clear()
            slider.setValue(slider.maximum())
            home.click()
            self.assertEqual(sent, [10, 5])
            self.assertEqual(label.text(), expected)
            ctrl.resize(240, 64)
            ctrl.show()
            self.app.processEvents()
            self.assertGreaterEqual(home.width(), home.sizeHint().width())
            self.assertLess(home.geometry().right(), slider.geometry().left())
            self.assertEqual(ctrl.layout().getItemPosition(ctrl.layout().indexOf(home)), (0, 0, 2, 1))
            ctrl.deleteLater()
        panel.db_messages = {1: {1: SimpleNamespace(get_signal_by_name=lambda name: SimpleNamespace(is_float=False))}}
        self.assertEqual(panel._format_slider_value(dict(bus=1, can_id=1, signal_name="Count", tx_resolution=0.1), 5), "5")
        panel.deleteLater()

    def test_initial_value_round_trip(self):
        dialog = WidgetConfigDialog({}, fixed_behavior="tx")
        dialog.combo_widget_type.setCurrentText("slider")
        dialog.spin_slider_initial.setValue(12.345678)
        cfg = dialog.get_config()
        restored = WidgetConfigDialog({}, preset=cfg)
        self.assertEqual(restored.get_config()["binding"]["tx_initial_value"], 12.345678)
        dialog.deleteLater()
        restored.deleteLater()
