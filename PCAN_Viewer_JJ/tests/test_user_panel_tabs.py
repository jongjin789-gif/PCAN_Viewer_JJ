import copy
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtWidgets import QApplication
from src.user_panel_v2.window import UserPanelWindow


class PanelTabsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def panel(self, widgets):
        panel = UserPanelWindow(SimpleNamespace(), {})
        self.addCleanup(panel.close)
        panel._load_panel_data(dict(version=5, widgets=copy.deepcopy(widgets)))
        return panel

    def test_named_tabs_child_routing_and_roundtrip(self):
        widgets = [dict(id='tabs', widget_type='tab_container', tabs=['Status', 'Motor', 'IMU']),
                   dict(id='imu', widget_type='label', parent_id='tabs', tab_index=2),
                   dict(id='default', widget_type='label', parent_id='tabs'),
                   dict(id='clamped', widget_type='label', parent_id='tabs', tab_index=99)]
        panel = self.panel(widgets)
        restored = self.panel(panel._panel_data()['widgets'])
        for instance in (panel, restored):
            tabs = instance.widget_controls['tabs']
            self.assertEqual([tabs.tabText(i) for i in range(tabs.count())], ['Status', 'Motor', 'IMU'])
            self.assertIs(instance.widget_frames['imu'].parentWidget(), tabs.widget(2))
            self.assertIs(instance.widget_frames['default'].parentWidget(), tabs.widget(0))
            self.assertIs(instance.widget_frames['clamped'].parentWidget(), tabs.widget(2))

    def test_legacy_tabs_keep_default_names_and_first_tab(self):
        panel = self.panel([dict(id='tabs', widget_type='tab_container'),
                            dict(id='child', widget_type='label', parent_id='tabs')])
        tabs = panel.widget_controls['tabs']
        self.assertEqual([tabs.tabText(i) for i in range(tabs.count())], ['Tab 1', 'Tab 2'])
        self.assertIs(panel.widget_frames['child'].parentWidget(), tabs.widget(0))
