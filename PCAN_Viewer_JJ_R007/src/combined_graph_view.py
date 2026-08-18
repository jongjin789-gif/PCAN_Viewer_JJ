import sys
import os
import datetime
import re
from PyQt5.QtWidgets import *
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor
import pyqtgraph as pg
from src.utils import get_resource_path

class CombinedGraphView(QWidget):
    """동기화된 여러 그래프를 하나의 창에 모아서 보여주는 뷰어"""
    def __init__(self, ordered_graphs, parent_window):
        super().__init__()
        self.graphs = ordered_graphs
        self.parent_window = parent_window
        self.original_parents = {} # 그래프 컨테이너의 원래 부모 위젯을 저장
        self.proxies = [] # 마우스 이동 시그널 프록시를 저장하여 연결 해제에 사용
        self.parent_is_closing = False # 부모 창이 닫히고 있는지 여부를 나타내는 플래그

        self.setWindowTitle("Combined Synchronized View")
        self.setWindowIcon(QIcon(get_resource_path(os.path.join("icon", "graph.png"))))
        self.resize(1200, 800)

        self.init_ui()
        self.reparent_graphs()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        # --- 상단 컨트롤 패널 ---
        top_ctrl_layout = QHBoxLayout()
        
        self.btn_reset_zoom = QPushButton("Reset Zoom")
        self.chk_crosshair = QCheckBox("Show Crosshair")
        self.chk_crosshair.setChecked(True)
        self.btn_clear_tags = QPushButton("Clear All Tags")
        self.btn_screenshot = QPushButton("Screenshot")

        top_ctrl_layout.addWidget(self.btn_reset_zoom)
        top_ctrl_layout.addStretch()
        top_ctrl_layout.addWidget(self.chk_crosshair)
        top_ctrl_layout.addWidget(self.btn_clear_tags)
        top_ctrl_layout.addWidget(self.btn_screenshot)
        main_layout.addLayout(top_ctrl_layout)

        # --- 그래프들을 담을 스크롤 영역 ---
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setSpacing(0)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_area.setWidget(self.scroll_content)
        main_layout.addWidget(scroll_area)

        # --- 이벤트 연결 ---
        self.btn_reset_zoom.clicked.connect(self.do_reset_zoom)
        self.chk_crosshair.toggled.connect(self.do_toggle_crosshair)
        self.btn_clear_tags.clicked.connect(self.do_clear_tags)
        self.btn_screenshot.clicked.connect(self.do_screenshot)

    def reparent_graphs(self):
        """원본 그래프 창에서 그래프 위젯을 가져와 통합 뷰에 재배치합니다."""
        for graph in self.graphs:
            self.original_parents[graph] = graph.graph_container.parent()
            graph.hide() # 원본 창 숨기기
            
            graph.graph_container.setParent(self.scroll_content)
            self.scroll_layout.addWidget(graph.graph_container)
            graph.plot_widget.setLabel('bottom', '') # X축 "Time" 레이블 생략

            # Add flag and reference for context-aware event handling
            graph.is_in_combined_view = True
            graph.combined_view_ref = self

        if not self.graphs:
            return

        # --- 내부 그래프 간 X축 및 마우스 이동 동기화 설정 ---
        # 1. X축 연결 (줌/이동 동기화)
        master_vb = self.graphs[0].plot_widget.getViewBox()
        for graph in self.graphs[1:]:
            graph.plot_widget.getViewBox().setXLink(master_vb)

        # 2. 마우스 이동 연결 (십자선 동기화)
        for graph in self.graphs:
            proxy = pg.SignalProxy(graph.plot_widget.scene().sigMouseMoved, rateLimit=60, slot=self.on_mouse_moved)
            self.proxies.append(proxy)

    def on_mouse_moved(self, evt):
        """통합 뷰 내의 한 그래프에서 마우스가 움직이면 모든 그래프에 전파합니다."""
        pos = evt[0]
        source_graph = None
        # 마우스가 현재 어느 그래프 위에 있는지 찾습니다.
        for g in self.graphs:
            if g.graph_container.underMouse():
                source_graph = g
                break
        
        if source_graph:
            mouse_point = source_graph.plot_widget.plotItem.vb.mapSceneToView(pos)
            target_x = mouse_point.x()
            
            for g in self.graphs:
                g.process_hover(target_x)
        else:
            for g in self.graphs:
                g.vLine.setVisible(False)
                g.hLine.setVisible(False)

    def do_reset_zoom(self):
        for graph in self.graphs:
            graph.plot_widget.autoRange()

    def do_toggle_crosshair(self, checked):
        for graph in self.graphs:
            if graph.chk_crosshair.isChecked() != checked:
                 graph.chk_crosshair.setChecked(checked)

    def do_clear_tags(self):
        for graph in self.graphs:
            graph.clear_all_tags()

    def do_screenshot(self):
        pixmaps = []
        for graph in self.graphs:
            # 범례와 플롯의 원래 상태 저장
            legend_state = {
                'min_w': graph.legend_widget.minimumWidth(), 'max_w': graph.legend_widget.maximumWidth(),
                'min_h': graph.legend_widget.minimumHeight(), 'max_h': graph.legend_widget.maximumHeight(),
                'v_policy': graph.legend_widget.verticalScrollBarPolicy(), 'h_policy': graph.legend_widget.horizontalScrollBarPolicy(),
                'elide_mode': graph.legend_widget.textElideMode(),
                'size_policy_h': graph.legend_widget.sizePolicy().horizontalPolicy(),
                'size_policy_v': graph.legend_widget.sizePolicy().verticalPolicy(),
                'fixed_width': graph.legend_widget.width(), # Store current fixed width (should be 200)
            }
            plot_state = {
                'min_h': graph.plot_widget.minimumHeight(), 'max_h': graph.plot_widget.maximumHeight(),
                'size_policy_h': graph.plot_widget.sizePolicy().horizontalPolicy(),
                'size_policy_v': graph.plot_widget.sizePolicy().verticalPolicy(),
                'current_height': graph.plot_widget.height(), # Store current height of plot
            }

            # 스크린샷을 위해 범례 위젯 임시 수정 (스크롤바 제거 및 전체 내용 표시)
            graph.legend_widget.setMinimumSize(0, 0)
            graph.legend_widget.setMaximumSize(16777215, 16777215)
            graph.legend_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            graph.legend_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            graph.legend_widget.setTextElideMode(Qt.ElideNone)
            graph.legend_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred) # Allow sizeHint to be accurate

            # 레이아웃 업데이트를 강제하여 sizeHint가 정확한 값을 반환하도록 함
            ideal_size = graph.legend_widget.sizeHint()
            
            # 범례의 이상적인 높이와 현재 플롯의 높이 중 더 큰 값으로 두 위젯의 높이를 맞춤
            target_height = max(plot_state['current_height'], ideal_size.height())

            graph.legend_widget.setFixedSize(ideal_size.width(), target_height) # 너비는 이상적인 너비, 높이는 맞춘 높이
            graph.plot_widget.setFixedHeight(target_height) # 플롯 위젯 높이도 맞춤
            
            # QApplication.processEvents()를 호출하여 레이아웃 변경이 화면에 반영되도록 함
            # 특히 Combined View에서는 여러 그래프가 동시에 변경되므로 중요
            QApplication.processEvents()
            QApplication.processEvents() # 한 번 더 호출하여 안정성 확보

            # 선택 해제 및 GUI 업데이트 후 스크린샷 캡처
            saved_selection = graph.legend_widget.selectedItems()
            graph.legend_widget.clearSelection()
            QApplication.processEvents()
            pixmaps.append(graph.graph_container.grab())

            # 원래 상태로 완벽하게 복원
            for item in saved_selection:
                item.setSelected(True)
            
            graph.legend_widget.setMinimumSize(legend_state['min_w'], legend_state['min_h'])
            graph.legend_widget.setMaximumSize(legend_state['max_w'], legend_state['max_h'])
            graph.legend_widget.setVerticalScrollBarPolicy(legend_state['v_policy'])
            graph.legend_widget.setHorizontalScrollBarPolicy(legend_state['h_policy'])
            graph.legend_widget.setTextElideMode(legend_state['elide_mode'])
            graph.legend_widget.setSizePolicy(legend_state['size_policy_h'], legend_state['size_policy_v'])
            graph.legend_widget.setFixedWidth(legend_state['fixed_width']) # Restore fixed width

            # Restore plot widget's original size policy and remove fixed height constraint
            graph.plot_widget.setSizePolicy(plot_state['size_policy_h'], plot_state['size_policy_v'])
            graph.plot_widget.setMinimumHeight(0)
            graph.plot_widget.setMaximumHeight(16777215)
        
        if not pixmaps: return

        total_width = max(p.width() for p in pixmaps)
        total_height = sum(p.height() for p in pixmaps)

        combined_pixmap = QPixmap(total_width, total_height)
        combined_pixmap.fill(QColor("black"))
        
        painter = QPainter(combined_pixmap)
        y_offset = 0
        for p in pixmaps:
            painter.drawPixmap(0, y_offset, p)
            y_offset += p.height()
        painter.end()

        if getattr(sys, 'frozen', False): base_dir = os.path.dirname(sys.executable)
        else: base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        screenshot_dir = os.path.join(base_dir, "Screenshot")
        os.makedirs(screenshot_dir, exist_ok=True)

        now = datetime.datetime.now()
        time_str = now.strftime('%y%m%d_%H%M%S') + f"{now.microsecond // 100000}"
        
        raw_title = self.graphs[0]._current_title.strip() if self.graphs else ""
        safe_title = re.sub(r'[\\/*?:"<>|]', "_", raw_title).strip(" _") or "Combined"
            
        filename = f"COMBINED_{time_str}_{safe_title}.png"
        filepath = os.path.join(screenshot_dir, filename)

        try:
            combined_pixmap.save(filepath, "PNG")
            QMessageBox.information(self, "Screenshot Saved", f"스크린샷이 성공적으로 저장되었습니다:\n{filepath}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"스크린샷 저장 중 오류 발생:\n{str(e)}")

    def closeEvent(self, event):
        """창이 닫힐 때 그래프 위젯들을 원래 창으로 복원하고 동기화를 해제합니다."""
        # 부모 창(메인/로그뷰어)이 닫히는 과정에서 이 창이 닫히는 것이라면,
        # 개별 그래프 창으로 복원하는 로직을 건너뛰고 그냥 닫히도록 합니다.
        if self.parent_is_closing:
            if self.parent_window:
                self.parent_window.combined_view_window = None
            event.accept()
            return

        # 1. 마우스 이동 시그널 프록시 연결 해제
        for proxy in self.proxies:
            proxy.disconnect()
        self.proxies.clear()

        # 2. X축 연결 해제 및 위젯 복원
        for graph in self.graphs:
            # X축 동기화 해제
            graph.plot_widget.getViewBox().setXLink(None)
            
            graph.plot_widget.setLabel('bottom', 'Time') # X축 "Time" 레이블 복원
            # Reset flag and reference
            graph.is_in_combined_view = False
            graph.combined_view_ref = None

            # 원래 부모로 위젯 복원
            original_parent = self.original_parents.get(graph)
            if original_parent:
                graph.graph_container.setParent(original_parent)
                graph.layout().addWidget(graph.graph_container, stretch=1)
                # 원래 창으로 돌아갈 때, 전체 데이터가 보이도록 뷰를 자동으로 리셋합니다.
                graph.plot_widget.autoRange()
                graph.show()
        
        if self.parent_window:
            self.parent_window.combined_view_window = None
            
        event.accept()