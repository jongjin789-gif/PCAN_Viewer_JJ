import sys
from PyQt5.QtWidgets import *
from PyQt5.QtCore import Qt, QSize, QMimeData, pyqtSignal
from PyQt5.QtGui import QColor, QPixmap, QPainter, QPen, QIcon, QDrag

# 그래프에 사용될 추천 색상 팔레트
RECOMMENDED_COLORS = [
    QColor(255, 85, 85),   # Bright Red
    QColor(85, 255, 85),   # Bright Green
    QColor(85, 170, 255),  # Light Blue
    QColor(255, 255, 85),  # Bright Yellow
    QColor(255, 170, 0),   # Orange
    QColor(255, 85, 255),  # Bright Magenta
    QColor(85, 255, 255),  # Bright Cyan
    QColor(170, 170, 255), # Soft Blue
    QColor(255, 170, 170), # Soft Pink
    QColor(170, 255, 170), # Soft Green
    QColor(221, 221, 221), # Light Gray
    QColor(170, 0, 0),     # Dark Red
    QColor(0, 170, 0),     # Dark Green
    QColor(0, 0, 170),     # Dark Blue
    QColor(170, 85, 0),    # Brown
    QColor(128, 128, 128), # Gray
]

# Placeholder for existing FormulaDialog to avoid breaking imports
# The actual implementation is not provided in the context.
class FormulaDialog(QDialog):
    def __init__(self, formulas, legend_items, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Formula Editor")
        # This is a placeholder implementation.
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("FormulaDialog implementation is not available in the provided context."))
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)
        self.formulas = formulas

    def get_formulas(self):
        return self.formulas

# New implementation for LabelEditorDialog and its helpers

class ColorButton(QPushButton):
    """A button that displays a color and opens a color dialog on click."""
    def __init__(self, color=Qt.black, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self.clicked.connect(self.change_color)
        self.set_color(self._color)

    def color(self):
        return self._color

    def set_color(self, color):
        self._color = QColor(color)
        pixmap = QPixmap(16, 16)
        pixmap.fill(self._color)
        self.setIcon(QIcon(pixmap))

    def change_color(self):
        # 추천 색상이 포함된 커스텀 컬러 다이얼로그 사용
        dialog = QColorDialog(self._color, self)
        dialog.setWindowTitle("Select Color")
        
        # 추천 색상을 커스텀 색상 슬롯에 추가
        for i, color in enumerate(RECOMMENDED_COLORS):
            if i < 16: # QColorDialog는 최대 16개의 커스텀 색상을 지원
                dialog.setCustomColor(i, color)

        if dialog.exec_():
            color = dialog.selectedColor()
            if color.isValid():
                self.set_color(color)

class LineStyleComboBox(QComboBox):
    """A combobox to select line styles with visual representation."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.populate_items()

    def populate_items(self):
        styles = {
            'Solid': Qt.SolidLine,
            'Dash': Qt.DashLine,
            'Dot': Qt.DotLine,
            'DashDot': Qt.DashDotLine,
            'DashDotDot': Qt.DashDotDotLine,
        }
        
        for name, style in styles.items():
            pixmap = QPixmap(60, 20)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            pen = QPen(Qt.black, 2)
            pen.setStyle(style)
            painter.setPen(pen)
            painter.drawLine(5, 10, 55, 10)
            painter.end()
            self.addItem(QIcon(pixmap), name, style)
        self.setIconSize(QSize(60, 20))

    def selected_style(self):
        return self.currentData()

    def set_selected_style(self, style):
        index = self.findData(style)
        if index != -1:
            self.setCurrentIndex(index)

class DraggableTableWidget(QTableWidget):
    """
    A QTableWidget subclass that supports drag-and-drop row reordering
    and emits a signal when rows are moved.
    """
    rowsMoved = pyqtSignal(int, int) # old_row_index, new_row_index

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection) # Only single row drag-drop for simplicity
        self.drag_start_position = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start_position = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton) or self.drag_start_position is None:
            return
        if (event.pos() - self.drag_start_position).manhattanLength() < QApplication.startDragDistance():
            return
        
        if not self.selectedItems():
            return

        drag = QDrag(self)
        mime_data = QMimeData()
        
        row_index = self.currentRow()
        mime_data.setText(str(row_index))
        drag.setMimeData(mime_data)
        
        # 드래그 작업 중 마우스 커서를 '이동' 모양(사방 화살표)으로 변경
        QApplication.setOverrideCursor(Qt.SizeAllCursor)
        drag.exec_(Qt.MoveAction)
        QApplication.restoreOverrideCursor()

        self.drag_start_position = None # Reset after drag operation

    def dragEnterEvent(self, event):
        """Accepts drag events if they contain text (our row index)."""
        if event.source() == self and event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        """Ensures the cursor indicates a move is possible."""
        if event.source() == self and event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.source() == self and event.dropAction() == Qt.MoveAction:
            source_row = int(event.mimeData().text())
            target_row = self.drop_on_row(event)
            
            if source_row != target_row and target_row != -1: # -1 indicates invalid drop target
                self.rowsMoved.emit(source_row, target_row)
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            super().dropEvent(event)

    def drop_on_row(self, event):
        """Helper to find the row index where the drop occurred."""
        index = self.indexAt(event.pos())
        if not index.isValid():
            # If dropping outside, append to the end
            return self.rowCount()
        
        # Determine if dropping above or below the current row
        rect = self.visualRect(index)
        if event.pos().y() - rect.top() < rect.height() / 2:
            return index.row()
        else:
            return index.row() + 1

class LabelEditorDialog(QDialog):
    def __init__(self, current_title, signals_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Labels and Styles")
        self.setMinimumSize(600, 400)
        
        self.signals_data = signals_data # List of dicts: [{'orig_name', 'disp_name', 'color', 'style'}]

        layout = QVBoxLayout(self)
        
        # Title editor
        form_layout = QFormLayout()
        self.title_edit = QLineEdit(current_title)
        form_layout.addRow("Graph Title:", self.title_edit)
        layout.addLayout(form_layout)

        # Table for signal properties
        self.table = DraggableTableWidget() # Use our custom table widget
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Original Name", "Display Name", "Color", "Line Style"])
        self.table.rowsMoved.connect(self.on_rows_moved) # Connect our custom signal
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        self.populate_table()
        # 초기화 시점에 컨텐츠에 맞게 조정된 열 너비를 고정하여, 드래그 앤 드롭으로 리스트를 다시 그릴 때 너비가 변하는 것을 방지
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)

        layout.addWidget(self.table)

        # OK/Cancel buttons
        btn_layout = QHBoxLayout()
        self.btn_ok = QPushButton("OK")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

    def on_rows_moved(self, old_row, new_row):
        """
        Slot to handle row reordering after a drag-and-drop operation.
        Updates the internal signals_data and repopulates the table.
        """
        # Adjust new_row if moving an item from an earlier position to a later position
        # because pop() reduces the list size, shifting subsequent elements.
        if old_row < new_row:
            new_row -= 1
        
        item_to_move = self.signals_data.pop(old_row)
        self.signals_data.insert(new_row, item_to_move)
        
        self.populate_table() # Repopulate to reflect the new order and correctly place cell widgets
        self.table.selectRow(new_row) # Restore selection to the moved row

    def populate_table(self):
        self.table.clearContents() # Clear existing content but keep headers
        self.table.setRowCount(len(self.signals_data))
        for row, data in enumerate(self.signals_data):
            # Original Name
            orig_name_item = QTableWidgetItem(data['orig_name'])
            orig_name_item.setFlags(orig_name_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, orig_name_item)

            # Display Name
            disp_name_item = QTableWidgetItem(data['disp_name'])
            self.table.setItem(row, 1, disp_name_item)

            # Color
            color_btn = ColorButton(QColor(*data['color']))
            self.table.setCellWidget(row, 2, color_btn)

            # Line Style
            style_combo = LineStyleComboBox()
            style_combo.set_selected_style(data['style'])
            self.table.setCellWidget(row, 3, style_combo)

    def get_values(self):
        new_title = self.title_edit.text()
        new_signals_data = []
        for row in range(self.table.rowCount()):
            orig_name = self.table.item(row, 0).text()
            disp_name = self.table.item(row, 1).text()
            color_btn = self.table.cellWidget(row, 2)
            color = color_btn.color().getRgb()[:3] # (r, g, b)
            style_combo = self.table.cellWidget(row, 3)
            style = style_combo.selected_style()
            
            new_signals_data.append({
                'orig_name': orig_name,
                'disp_name': disp_name,
                'color': color,
                'style': style
            })
        return new_title, new_signals_data