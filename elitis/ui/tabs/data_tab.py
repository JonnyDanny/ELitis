"""
Data Tab — table editor for all item labels, plus CSV/TXT import and project save/load.

Each row shows one content item: # | Label (editable) | Image | render status.
Clicking a row navigates to that item. Double-clicking the Image cell opens a file
dialog to assign an image. Double-clicking the Label cell (or pressing F2) edits it
inline.
"""
from __future__ import annotations
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog,
    QLineEdit, QAbstractItemView, QMenu, QMessageBox,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QAction

from elitis.ui.app_state import AppState
from elitis.core import data_io
from elitis.core.models import ThumbnailItem

_COL_NUM    = 0
_COL_LABEL  = 1
_COL_IMAGE  = 2
_COL_STATUS = 3

_GREEN = QColor("#3cb371")
_AMBER = QColor("#e0a030")
_DIM   = QColor("#888899")


def _status_item(clean: bool) -> QTableWidgetItem:
    cell = QTableWidgetItem("✓" if clean else "~")
    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    cell.setForeground(_GREEN if clean else _AMBER)
    cell.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    return cell


def _readonly_item(text: str, dim: bool = False) -> QTableWidgetItem:
    cell = QTableWidgetItem(text)
    cell.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    if dim:
        cell.setForeground(_DIM)
    return cell


class DataTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self._state = state
        self._updating = False
        self._build_ui()
        self._connect_signals()
        self._rebuild_table()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Project name row
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Project name:"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("untitled")
        name_row.addWidget(self._name_edit)
        layout.addLayout(name_row)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["#", "Label", "Image", "✓"])
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(_COL_LABEL, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(_COL_NUM,    QHeaderView.ResizeMode.Fixed)
        h.setSectionResizeMode(_COL_IMAGE,  QHeaderView.ResizeMode.Fixed)
        h.setSectionResizeMode(_COL_STATUS, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(_COL_NUM,    40)
        self._table.setColumnWidth(_COL_IMAGE, 160)
        self._table.setColumnWidth(_COL_STATUS, 36)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked |
            QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.setAlternatingRowColors(True)
        layout.addWidget(self._table, stretch=1)

        # Item count
        self._lbl_count = QLabel("0 items")
        self._lbl_count.setObjectName("dim")
        layout.addWidget(self._lbl_count)

        # Toolbar: add / delete / reorder  +  import
        row1 = QHBoxLayout()
        self._btn_add    = QPushButton("+ Add item")
        self._btn_delete = QPushButton("Delete")
        self._btn_up     = QPushButton("▲")
        self._btn_down   = QPushButton("▼")
        self._btn_up.setFixedWidth(32)
        self._btn_down.setFixedWidth(32)
        for b in (self._btn_add, self._btn_delete, self._btn_up, self._btn_down):
            row1.addWidget(b)
        row1.addStretch()
        self._btn_import = QPushButton("Import CSV/TXT…")
        row1.addWidget(self._btn_import)
        layout.addLayout(row1)

        # Footer: project management
        row2 = QHBoxLayout()
        self._btn_new    = QPushButton("New project")
        self._btn_load   = QPushButton("Load project…")
        self._btn_save   = QPushButton("Save project")
        self._btn_saveas = QPushButton("Save as…")
        for b in (self._btn_new, self._btn_load, self._btn_save, self._btn_saveas):
            row2.addWidget(b)
        layout.addLayout(row2)

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self):
        s = self._state
        s.project_replaced.connect(self._rebuild_table)
        s.current_changed.connect(self._sync_selection)
        s.items_status_changed.connect(self._refresh_status_column)

        self._table.itemChanged.connect(self._on_item_changed)
        self._table.currentCellChanged.connect(self._on_row_selected)
        self._table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self._table.customContextMenuRequested.connect(self._show_context_menu)

        self._name_edit.textChanged.connect(self._on_name_changed)

        self._btn_add.clicked.connect(self._add_item)
        self._btn_delete.clicked.connect(self._delete_item)
        self._btn_up.clicked.connect(self._move_up)
        self._btn_down.clicked.connect(self._move_down)
        self._btn_import.clicked.connect(self._import)
        self._btn_new.clicked.connect(lambda: self._state.new_project(
            self._name_edit.text().strip() or "untitled"))
        self._btn_load.clicked.connect(self._load)
        self._btn_save.clicked.connect(self._state.save_project)
        self._btn_saveas.clicked.connect(self._save_as)

    # ------------------------------------------------------------------
    # Table population
    # ------------------------------------------------------------------

    def _rebuild_table(self):
        self._updating = True
        project = self._state.project
        items = project.content_items

        self._table.blockSignals(True)
        self._table.setRowCount(len(items))
        for row, item in enumerate(items):
            self._set_row(row, item)
        self._table.blockSignals(False)

        self._name_edit.blockSignals(True)
        self._name_edit.setText(project.name)
        self._name_edit.blockSignals(False)

        self._lbl_count.setText(f"{len(items)} items")
        self._updating = False
        self._sync_selection(self._state.current_index)

    def _set_row(self, row: int, item: ThumbnailItem):
        """Populate all four cells for a given row."""
        # # column
        num_cell = _readonly_item(str(row + 1))
        num_cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setItem(row, _COL_NUM, num_cell)

        # Label column (editable)
        label_cell = QTableWidgetItem(item.label)
        label_cell.setFlags(
            Qt.ItemFlag.ItemIsEnabled |
            Qt.ItemFlag.ItemIsSelectable |
            Qt.ItemFlag.ItemIsEditable
        )
        self._table.setItem(row, _COL_LABEL, label_cell)

        # Image column
        img_name = Path(item.image_path).name if item.image_path else "—"
        self._table.setItem(row, _COL_IMAGE, _readonly_item(img_name, dim=not item.image_path))

        # Status column
        self._table.setItem(row, _COL_STATUS, _status_item(self._state.is_clean(item.id)))

    def _refresh_status_column(self):
        """Refresh only the status column (fast, no full rebuild)."""
        self._table.blockSignals(True)
        items = self._state.project.content_items
        for row, item in enumerate(items):
            if row < self._table.rowCount():
                self._table.setItem(row, _COL_STATUS, _status_item(self._state.is_clean(item.id)))
        self._table.blockSignals(False)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _sync_selection(self, index: int):
        if self._updating:
            return
        table_row = index - 1
        if 0 <= table_row < self._table.rowCount():
            self._updating = True
            self._table.selectRow(table_row)
            self._updating = False

    def _on_row_selected(self, current_row: int, _cc, _pr, _pc):
        if self._updating or current_row < 0:
            return
        self._state.go_to(current_row + 1)

    def _on_item_changed(self, cell: QTableWidgetItem):
        if self._updating or cell.column() != _COL_LABEL:
            return
        row = cell.row()
        items = self._state.project.content_items
        if row >= len(items):
            return
        new_label = cell.text()
        items[row].label = new_label
        self._state.notify_settings_changed()

    def _on_cell_double_clicked(self, row: int, col: int):
        if col != _COL_IMAGE:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose image",
            str(self._state.ingest_dir),
            "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All files (*)"
        )
        if not path:
            return
        items = self._state.project.content_items
        if row < len(items):
            items[row].image_path = path
            self._table.blockSignals(True)
            img_name = Path(path).name
            self._table.setItem(row, _COL_IMAGE, _readonly_item(img_name))
            self._table.blockSignals(False)
            if self._state.current_index - 1 == row:
                self._state.notify_settings_changed()
            else:
                self._state._clean_ids.discard(items[row].id)
                self._state.items_status_changed.emit()

    def _on_name_changed(self, text: str):
        self._state.project.name = text or "untitled"

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _show_context_menu(self, pos):
        row = self._table.rowAt(pos.y())
        menu = QMenu(self)
        act_add_above = menu.addAction("Insert above")
        act_add_below = menu.addAction("Insert below")
        menu.addSeparator()
        act_del = menu.addAction("Delete row")
        menu.addSeparator()
        act_up   = menu.addAction("Move up")
        act_down = menu.addAction("Move down")

        if row < 0:
            for a in (act_del, act_up, act_down, act_add_above):
                a.setEnabled(False)

        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if action == act_add_above:
            self._insert_item(row)
        elif action == act_add_below:
            self._insert_item(row + 1)
        elif action == act_del:
            self._delete_item_at(row)
        elif action == act_up:
            self._move_row(row, -1)
        elif action == act_down:
            self._move_row(row, +1)

    # ------------------------------------------------------------------
    # Item operations
    # ------------------------------------------------------------------

    def _add_item(self):
        row = self._table.currentRow()
        self._insert_item(row + 1 if row >= 0 else len(self._state.project.content_items))

    def _insert_item(self, at_row: int):
        project = self._state.project
        new_item = ThumbnailItem.new_item("")
        # Insert into project.items at position at_row + 1 (skip phantom at [0])
        insert_pos = at_row + 1
        project.items.insert(insert_pos, new_item)
        self._state.project_replaced.emit()
        # Navigate to the new item and start editing its label
        new_content_index = at_row + 1  # 1-based item index
        self._state.go_to(new_content_index)
        self._table.editItem(self._table.item(at_row, _COL_LABEL))

    def _delete_item(self):
        row = self._table.currentRow()
        if row >= 0:
            self._delete_item_at(row)

    def _delete_item_at(self, row: int):
        items = self._state.project.content_items
        if row >= len(items):
            return
        item = items[row]
        self._state.project.remove_item(item.id)
        self._state._clean_ids.discard(item.id)
        count = len(self._state.project.content_items)
        new_idx = min(row + 1, max(1, count))
        self._state.project_replaced.emit()
        self._state.go_to(new_idx)

    def _move_up(self):
        self._move_row(self._table.currentRow(), -1)

    def _move_down(self):
        self._move_row(self._table.currentRow(), +1)

    def _move_row(self, row: int, delta: int):
        items = self._state.project.content_items
        new_row = row + delta
        if new_row < 0 or new_row >= len(items):
            return
        # items[0] is phantom; content starts at index 1
        pi  = row     + 1
        pi2 = new_row + 1
        lst = self._state.project.items
        lst[pi], lst[pi2] = lst[pi2], lst[pi]
        self._state.project_replaced.emit()
        self._state.go_to(new_row + 1)

    # ------------------------------------------------------------------
    # Import / save / load
    # ------------------------------------------------------------------

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import labels", str(self._state.projects_dir),
            "Text files (*.csv *.txt *.tsv);;All files (*)"
        )
        if not path:
            return
        labels = data_io.import_labels(Path(path))
        if not labels:
            QMessageBox.warning(self, "Import", "No labels found in the file.")
            return
        project = self._state.project
        existing = {i.label: i for i in project.content_items}
        new_items = [project.phantom]
        for lbl in labels:
            new_items.append(existing[lbl] if lbl in existing else ThumbnailItem.new_item(lbl))
        project.items = new_items
        self._state.project_replaced.emit()
        self._state.status_message.emit(
            f"Imported {len(labels)} labels from {Path(path).name}"
        )

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load project", str(self._state.projects_dir),
            "ELItis project (*.json);;All files (*)"
        )
        if path:
            self._state.load_project(Path(path))

    def _save_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save project as", str(self._state.projects_dir),
            "ELItis project (*.json)"
        )
        if path:
            self._state.save_project_as(Path(path))
