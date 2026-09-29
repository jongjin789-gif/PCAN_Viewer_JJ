import copy
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtWidgets import QApplication, QSlider
from src.user_panel_v2.window import UserPanelWindow


class PanelPagesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def panel(self, data):
        panel = UserPanelWindow(SimpleNamespace(), {})
        self.addCleanup(panel.close)
        panel._load_panel_data(copy.deepcopy(data))
        panel.show()
        return panel

    def cfg(self, ident, **extra):
        return dict(id=ident, title=ident, widget_type='slider', behavior='none',
                    row=0, col=0, row_span=3, col_span=5, binding={}, **extra)

    def add_page(self, panel, name):
        with patch('src.user_panel_v2.window.QInputDialog.getText', return_value=(name, True)):
            panel.add_page()

    def test_legacy_add_rename_save_load(self):
        panel = self.panel(dict(version=4, widgets=[self.cfg('old')]))
        self.assertEqual(len(panel.pages), 1)
        self.assertEqual(panel.widgets_config[0]['page_id'], 'default')
        self.add_page(panel, '진단 테스트')
        self.assertTrue(panel.widget_frames['old'].isHidden())
        self.assertEqual(panel.list_tools.count(), 0)
        new = self.cfg('new')
        panel._normalize_config(new)
        panel._upsert_widget_config(new)
        panel.rebuild_grid()
        self.assertEqual(new['page_id'], panel.pages[1]['id'])
        with patch('src.user_panel_v2.window.QInputDialog.getText', return_value=('CAN Bus 2', True)):
            panel.rename_page(1)
        restored = self.panel(json.loads(json.dumps(panel._panel_data())))
        self.assertEqual(restored.page_tabs.tabText(1), 'CAN Bus 2')
        self.assertEqual(restored.page_tabs.currentIndex(), 1)
        self.assertTrue(restored.widget_frames['old'].isHidden())
        self.assertFalse(restored.widget_frames['new'].isHidden())
        restored.page_tabs.setCurrentIndex(0)
        self.assertFalse(restored.widget_frames['old'].isHidden())
        self.assertTrue(restored.widget_frames['new'].isHidden())

    def test_switch_keeps_runtime_and_values(self):
        panel = self.panel(dict(widgets=[self.cfg('s')]))
        self.add_page(panel, 'Second')
        panel.set_mode('run')
        ctrl = panel.widget_controls['s']
        slider = ctrl.findChild(QSlider)
        slider.setValue(37)
        with patch.object(panel, 'stop_panel_commands') as stop:
            panel.page_tabs.setCurrentIndex(0)
            panel.page_tabs.setCurrentIndex(1)
            stop.assert_not_called()
        self.assertIs(ctrl, panel.widget_controls['s'])
        self.assertEqual(slider.value(), 37)
        self.assertFalse(panel.btn_add_page.isEnabled())

    def test_copy_between_pages_and_undo(self):
        panel = self.panel(dict(widgets=[self.cfg('s')]))
        panel.selected_widget_id = 's'
        panel.selected_widget_ids = {'s'}
        panel.copy_selected_tools()
        self.add_page(panel, 'Second')
        panel.paste_tools()
        clone = panel.selected_configs()[0]
        self.assertEqual(clone['page_id'], panel.pages[1]['id'])
        self.assertTrue(panel.widget_frames['s'].isHidden())
        panel.undo_edit()
        self.assertEqual(len(panel.widgets_config), 1)
        panel.undo_edit()
        self.assertEqual(len(panel.pages), 1)
        panel.redo_edit()
        self.assertEqual(len(panel.pages), 2)

    def test_nested_legacy_and_properties_keep_page(self):
        group = self.cfg('g')
        group['widget_type'] = 'group_box'
        panel = self.panel(dict(widgets=[group, self.cfg('child', parent_id='g')]))
        self.add_page(panel, 'Other')
        self.assertEqual(panel._group_parent_candidates(), [])
        self.assertTrue(panel.widget_frames['child'].isHidden())
        panel.page_tabs.setCurrentIndex(0)
        edited = self.cfg('child', parent_id='g')
        panel._normalize_config(edited)
        self.assertEqual(edited['page_id'], 'default')
        self.assertFalse(panel.widget_frames['child'].isHidden())
