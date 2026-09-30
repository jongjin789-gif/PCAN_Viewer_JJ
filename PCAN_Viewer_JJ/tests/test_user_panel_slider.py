import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication, QLabel, QPushButton, QSlider, QLineEdit
from cantools.database.conversion import BaseConversion
from cantools.database.can import Message, Signal
from src.user_panel_v2.window import UserPanelWindow
from src.user_panel_v2.config_dialog import WidgetConfigDialog
from src.user_panel_v2.binding import pack_value


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
            entry = ctrl.findChild(QLineEdit, "slider_value_input")
            set_button = ctrl.findChild(QPushButton, "slider_set")
            self.assertLess(entry.geometry().right(), set_button.geometry().left())
            self.assertLess(entry.geometry().center().y(), slider.geometry().center().y())
            self.assertGreater(label.geometry().center().y(), slider.geometry().center().y())
            self.assertGreaterEqual(home.geometry().bottom(), label.geometry().bottom())
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

    def test_tx_slider_displays_the_dbc_decoded_value(self):
        conversion = BaseConversion.factory(scale=0.125, offset=0.1)
        message = Message(0x123, "Scaled", 1, [Signal("Value", 0, 8, conversion=conversion)])
        panel = UserPanelWindow(SimpleNamespace(), {1: {0x123: message}})
        sent_values = []
        panel._emit_tx = lambda cfg, value: sent_values.append(value)
        binding = dict(bus=1, can_id=0x123, dlc=1, signal_name="Value", start_bit=0,
                       bit_length=8, scale=0.125, offset=0.1, signed=False,
                       byte_order="little_endian", min=0, max=1, tx_resolution=0.2,
                       tx_initial_value=0)
        control, _ = panel._create_runtime_widget(dict(
            id="slider", title="Value", widget_type="slider", behavior="tx", binding=binding))
        slider = control.findChild(QSlider, "slider")
        label = control.findChild(QLabel, "value_label")

        slider.setValue(2)

        encoded = pack_value(bytes(1), binding, sent_values[-1])
        decoded = message.decode(encoded, decode_choices=False)["Value"]
        self.assertEqual(float(label.text()), decoded)
        self.assertEqual(sent_values[-1], decoded)
        control.deleteLater()
        panel.deleteLater()

    def test_dbc_scale_and_offset_precision_survive_signal_selection_and_save(self):
        conversion = BaseConversion.factory(scale=0.0625, offset=-780.125)
        signal = Signal("Value", 7, 16, byte_order="big_endian", conversion=conversion)
        message = Message(0x123, "Scaled", 8, [signal])
        dialog = WidgetConfigDialog({1: {0x123: message}}, fixed_behavior="tx")
        dialog.combo_widget_type.setCurrentText("slider")
        dialog.combo_message.setCurrentIndex(dialog.combo_message.findData(0x123))
        dialog.combo_signal.setCurrentIndex(dialog.combo_signal.findData("Value"))

        config = dialog.get_config()

        self.assertEqual(dialog.spin_scale.value(), 0.0625)
        self.assertEqual(dialog.spin_offset.value(), -780.125)
        self.assertEqual(config["binding"]["scale"], 0.0625)
        self.assertEqual(config["binding"]["offset"], -780.125)
        dialog.deleteLater()
