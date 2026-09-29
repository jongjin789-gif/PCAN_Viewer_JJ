import copy
import os
import unittest
from types import SimpleNamespace
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtCore import Qt, QPoint, QPointF
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest
from src.user_panel_v2.window import UserPanelWindow


class ToolCopyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def panel(self, configs):
        panel = UserPanelWindow(SimpleNamespace(), {})
        panel._load_panel_data(dict(widgets=configs, grid=dict(rows=20, cols=20)))
        panel.show()
        panel.activateWindow()
        self.app.processEvents()
        self.addCleanup(panel.close)
        return panel

    def cfg(self, ident, row=1, col=1, parent=None, kind='shape_rect'):
        return dict(id=ident, title=ident, behavior='none', widget_type=kind, row=row, col=col,
                    row_span=3, col_span=4, parent_id=parent,
                    binding=dict(sequence_steps=[dict(kind='DEL', delay_ms=25)]))

    def test_keyboard_multi_copy_and_independent_settings_undo(self):
        panel = self.panel([self.cfg('a'), self.cfg('b', 5, 6)])
        panel.selected_widget_ids = {'a', 'b'}
        panel.selected_widget_id = 'a'
        original = copy.deepcopy(panel.widgets_config)
        panel.canvas.setFocus()
        QTest.keyClick(panel.canvas, Qt.Key_C, Qt.ControlModifier)
        QTest.keyClick(panel.canvas, Qt.Key_V, Qt.ControlModifier)
        self.assertEqual(len(panel.widgets_config), 4)
        clones = panel.selected_configs()
        self.assertEqual(len(clones), 2)
        self.assertTrue(all(c['id'] not in {'a', 'b'} for c in clones))
        self.assertEqual(panel.widgets_config[:2], original)
        self.assertEqual((clones[1]['row'] - clones[0]['row'], clones[1]['col'] - clones[0]['col']), (4, 5))
        panel.undo_edit()
        self.assertEqual(len(panel.widgets_config), 2)
        panel.redo_edit()
        self.assertEqual(len(panel.widgets_config), 4)
        panel.widgets_config[2]['binding']['sequence_steps'][0]['delay_ms'] = 99
        self.assertEqual(panel.widgets_config[0]['binding']['sequence_steps'][0]['delay_ms'], 25)

    def test_group_clones_descendants_once_and_maps_parents(self):
        panel = self.panel([self.cfg('group', kind='group_box'), self.cfg('child', 0, 0, 'group')])
        panel.selected_widget_ids = {'group', 'child'}
        panel.selected_widget_id = 'group'
        panel.copy_selected_tools()
        panel.paste_tools()
        self.assertEqual(len(panel.widgets_config), 4)
        group, child = panel.widgets_config[2:]
        self.assertEqual(child['parent_id'], group['id'])
        self.assertEqual((child['row'], child['col']), (0, 0))
        self.assertEqual(panel.widgets_config[1]['parent_id'], 'group')

    def test_ctrl_drag_copies_selection_without_moving_originals(self):
        panel = self.panel([self.cfg('a'), self.cfg('b', 5, 6)])
        panel.selected_widget_ids = {'a', 'b'}
        panel.selected_widget_id = 'a'
        original = copy.deepcopy(panel.widgets_config)
        frame = panel.widget_frames['a']
        start = QPoint(20, 20)
        end = start + QPoint(64, 64)
        for kind, pos, button, buttons in [
            (QMouseEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton),
            (QMouseEvent.MouseMove, end, Qt.NoButton, Qt.LeftButton),
            (QMouseEvent.MouseButtonRelease, end, Qt.LeftButton, Qt.NoButton),
        ]:
            event = QMouseEvent(kind, QPointF(pos), QPointF(frame.mapToGlobal(pos)), button, buttons, Qt.ControlModifier)
            QApplication.sendEvent(frame, event)
        self.assertEqual(len(panel.widgets_config), 4)
        self.assertEqual(panel.widgets_config[:2], original)
        self.assertEqual(len(panel.selected_configs()), 2)
        self.assertGreater(panel.widgets_config[2]['row'], original[0]['row'])

    def test_copy_blocked_outside_edit_and_list_shortcuts(self):
        panel = self.panel([self.cfg('a')])
        panel.list_tools.setFocus()
        QTest.keyClick(panel.list_tools, Qt.Key_C, Qt.ControlModifier)
        QTest.keyClick(panel.list_tools, Qt.Key_V, Qt.ControlModifier)
        self.assertEqual(len(panel.widgets_config), 2)
        panel.set_mode('standard')
        panel.paste_tools()
        self.assertEqual(len(panel.widgets_config), 2)

    def test_drag_moves_selection_together_and_undoes_once(self):
        panel = self.panel([self.cfg('a'), self.cfg('b', 5, 6)])
        panel.selected_widget_ids = {'a', 'b'}
        panel.selected_widget_id = 'a'
        original = copy.deepcopy(panel.widgets_config)
        frame = panel.widget_frames['a']
        start = QPoint(20, 20)
        end = start + QPoint(64, 64)
        for kind, pos, button, buttons in [
            (QMouseEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton),
            (QMouseEvent.MouseMove, end, Qt.NoButton, Qt.LeftButton),
            (QMouseEvent.MouseButtonRelease, end, Qt.LeftButton, Qt.NoButton),
        ]:
            event = QMouseEvent(kind, QPointF(pos), QPointF(frame.mapToGlobal(pos)),
                                button, buttons, Qt.NoModifier)
            QApplication.sendEvent(frame, event)
        a, b = panel.widgets_config
        self.assertEqual(len(panel.selected_configs()), 2)
        self.assertGreater(a['row'], original[0]['row'])
        self.assertEqual((b['row'] - a['row'], b['col'] - a['col']), (4, 5))
        panel.undo_edit()
        self.assertEqual(panel.widgets_config, original)
        panel.redo_edit()
        self.assertGreater(panel.widgets_config[0]['row'], original[0]['row'])

    def test_multi_nudge_boundary_and_selected_group_child(self):
        panel = self.panel([self.cfg('a'), self.cfg('b', 5, 6),
                            self.cfg('child', 0, 0, 'a')])
        panel.selected_widget_ids = {'a', 'b', 'child'}
        panel.selected_widget_id = 'a'
        panel.nudge_selected(-10, -10)
        self.assertEqual([(c['row'], c['col']) for c in panel.widgets_config],
                         [(0, 0), (4, 5), (0, 0)])
        panel.nudge_selected(1, 1)
        self.assertEqual([(c['row'], c['col']) for c in panel.widgets_config],
                         [(1, 1), (5, 6), (0, 0)])

    def test_copied_tx_can_bind_other_bus_without_changing_source(self):
        from src.user_panel_v2.packets import bind_packet
        p = dict(packet_id='p', bus=1, id=0x123, length=8, data=[0]*8,
                 cycle=10, is_fd=False, is_brs=False)
        q = dict(p, packet_id='q', bus=2)
        cfg = self.cfg('a', kind='spinbox')
        cfg.update(behavior='tx')
        cfg['binding'] = dict(start_bit=0, bit_length=8)
        bind_packet(cfg['binding'], p)
        panel = self.panel([])
        panel._load_panel_data(dict(widgets=[cfg], tx_packets=[p, q]))
        panel.copy_selected_tools()
        panel.paste_tools()
        editor = panel.properties.editor
        editor.combo_bus.setCurrentText('2')
        editor.accept()
        original, cloned = panel.widgets_config
        self.assertEqual(original['binding']['packet_id'], 'p')
        self.assertEqual(cloned['binding']['packet_id'], 'q')
        self.assertEqual(cloned['binding']['bus'], 2)
