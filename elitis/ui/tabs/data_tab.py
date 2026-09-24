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
        self._state.commit_label(items[row].id, new_label)

    def _on_cell_double_clicked(self, row: int, col: int):
        if col != _COL_IMAGE:
            return
        items = self._state.project.content_items
        if row >= len(items):
            return
        item = items[row]

        # If this is a different item, the navigation is a side-effect of wanting to
        # change an image — guard the user if the current item has unrendered changes.
        current_content_row = self._state.current_index - 1
        if row != current_content_row:
            cur = self._state.current_item
            # Defaults dirty: ALL inheriting items are stale — qualitatively different
            # from a single item being dirty, so guard on both but with distinct text.
            cur_is_dirty = (
                cur.is_default and self._state.defaults_dirty
            ) or (
                not cur.is_default and not self._state.is_clean(cur.id)
            )
            if cur_is_dirty:
                name = "Default template" if cur.is_default else (cur.label or f"Item {current_content_row + 1}")
                guard = self._navigation_guard(name, is_default=cur.is_default)
                if guard == "cancel":
                    return
                if guard == "preview":
                    self._state.request_preview()
                    return
                # "continue" — fall through and navigate

            self._state.go_to(row + 1)

        # Confirm before overwriting an existing assignment
        if item.image_path:
            existing_name = Path(item.image_path).name
            reply = QMessageBox.question(
                self, "Replace image?",
                f'"{item.label or f"Item {row + 1}"}" already has:\n  {existing_name}\n\nReplace it?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        path, _ = QFileDialog.getOpenFileName(
            self, "Choose image",
            str(self._state.ingest_dir),
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.tiff *.gif);;All files (*)"
        )
        if not path:
            return

        committed = self._state.ingest_file(Path(path))
        self._state.commit_image(item.id, str(committed))
        self._table.blockSignals(True)
        self._table.setItem(row, _COL_IMAGE, _readonly_item(Path(path).name))
        self._table.blockSignals(False)

    def _navigation_guard(self, label: str, *, is_default: bool = False) -> str:
        """
        Ask what to do when navigating away from a dirty item as a side-effect.
        Returns 'cancel', 'preview', or 'continue'.

        is_default=True uses stronger wording because defaults changes propagate
        to every item that inherits a default — not just one item left unrendered.
        """
        msg = QMessageBox(self)
        if is_default:
            msg.setWindowTitle("Default template has unsaved changes")
            msg.setText(
                "The default template has been modified.\n\n"
                "These changes propagate to every item using default values — "
                "switching now means no item will have a rendered preview of the new defaults."
            )
        else:
            msg.setWindowTitle("Changes not yet previewed")
            msg.setText(
                f'"{label}" has changes that haven\'t been previewed.\n\n'
                "Switching now will leave this item without an up-to-date render until you return."
            )
        msg.setInformativeText(
            "Generate preview — stay here, render the current state, cancel the switch.\n"
            "Continue — switch anyway (changes are kept but not rendered).\n"
            "Cancel — do nothing."
        )
        btn_cancel   = msg.addButton("Cancel",           QMessageBox.ButtonRole.RejectRole)
        btn_preview  = msg.addButton("Generate preview", QMessageBox.ButtonRole.AcceptRole)
        btn_continue = msg.addButton("Continue anyway",  QMessageBox.ButtonRole.DestructiveRole)
        msg.setDefaultButton(btn_cancel)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked == btn_preview:
            return "preview"
        if clicked == btn_continue:
            return "continue"
        return "cancel"

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
        self._state.insert_item(at_row, "")
        self._state.go_to(at_row + 1)
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
        self._state.remove_item(item.id)
        count = len(self._state.project.content_items)
        new_idx = min(row + 1, max(1, count))
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
        self._state.move_item(row, delta)
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
        existing = {i.label: i for i in self._state.project.content_items}
        new_content = [existing[lbl] if lbl in existing else ThumbnailItem.new_item(lbl)
                       for lbl in labels]
        self._state.replace_items(new_content)
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
