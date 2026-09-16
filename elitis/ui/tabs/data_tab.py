"""
Data Tab — multi-line editor for all item labels, CSV/TXT import, project save/load.
"""
from __future__ import annotations
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QPlainTextEdit,
    QLabel, QFileDialog, QLineEdit, QMessageBox,
)
from PySide6.QtCore import Qt

from elitis.ui.app_state import AppState
from elitis.core import data_io
from elitis.core.models import ThumbnailItem


class DataTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self._state = state
        self._build_ui()
        self._connect_signals()
        self._load_from_project()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Project name
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Project name:"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("untitled")
        name_row.addWidget(self._name_edit)
        layout.addLayout(name_row)

        # Info label
        self._lbl_info = QLabel("One label per line. Blank lines are ignored.")
        self._lbl_info.setObjectName("dim")
        layout.addWidget(self._lbl_info)

        # Text editor
        self._editor = QPlainTextEdit()
        self._editor.setPlaceholderText("Item 1\nItem 2\nItem 3\n...")
        layout.addWidget(self._editor, stretch=1)

        # Status
        self._lbl_count = QLabel("0 items")
        self._lbl_count.setObjectName("dim")
        layout.addWidget(self._lbl_count)

        # Button row 1: import / apply
        row1 = QHBoxLayout()
        self._btn_import = QPushButton("Import CSV/TXT…")
        self._btn_apply  = QPushButton("Apply to project")
        self._btn_apply.setObjectName("accent")
        row1.addWidget(self._btn_import)
        row1.addStretch()
        row1.addWidget(self._btn_apply)
        layout.addLayout(row1)

        # Button row 2: save / load
        row2 = QHBoxLayout()
        self._btn_new    = QPushButton("New project")
        self._btn_load   = QPushButton("Load project…")
        self._btn_save   = QPushButton("Save project")
        self._btn_saveas = QPushButton("Save as…")
        for b in (self._btn_new, self._btn_load, self._btn_save, self._btn_saveas):
            row2.addWidget(b)
        layout.addLayout(row2)

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def _connect_signals(self):
        self._state.project_replaced.connect(self._load_from_project)
        self._state.current_changed.connect(self._highlight_current)

        self._editor.textChanged.connect(self._on_text_changed)
        self._name_edit.textChanged.connect(self._on_name_changed)

        self._btn_import.clicked.connect(self._import)
        self._btn_apply.clicked.connect(self._apply)
        self._btn_new.clicked.connect(self._new_project)
        self._btn_load.clicked.connect(self._load)
        self._btn_save.clicked.connect(self._state.save_project)
        self._btn_saveas.clicked.connect(self._save_as)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _load_from_project(self):
        self._editor.blockSignals(True)
        self._name_edit.blockSignals(True)
        self._name_edit.setText(self._state.project.name)
        labels = [i.label for i in self._state.project.content_items]
        self._editor.setPlainText("\n".join(labels))
        self._update_count()
        self._editor.blockSignals(False)
        self._name_edit.blockSignals(False)

    def _highlight_current(self, index: int):
        if index == 0:
            return
        block = self._editor.document().findBlockByLineNumber(index - 1)
        cursor = self._editor.textCursor()
        cursor.setPosition(block.position())
        cursor.select(cursor.SelectionType.LineUnderCursor)
        self._editor.setTextCursor(cursor)

    def _on_text_changed(self):
        self._update_count()

    def _on_name_changed(self, text: str):
        self._state.project.name = text or "untitled"

    def _update_count(self):
        lines = [l for l in self._editor.toPlainText().splitlines() if l.strip()]
        self._lbl_count.setText(f"{len(lines)} items")

    def _apply(self):
        lines = [l.strip() for l in self._editor.toPlainText().splitlines() if l.strip()]
        project = self._state.project
        existing = {i.label: i for i in project.content_items}

        # Preserve items that still appear; add new ones for new labels
        new_items = [project.phantom]
        for label in lines:
            if label in existing:
                new_items.append(existing[label])
            else:
                new_items.append(ThumbnailItem.new_item(label))

        project.items = new_items
        self._state.project_replaced.emit()
        self._state.status_message.emit(f"Applied {len(lines)} items")

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
        # Show in editor; user confirms with Apply
        self._editor.setPlainText("\n".join(labels))
        self._state.status_message.emit(
            f"Loaded {len(labels)} labels from {Path(path).name} — click Apply to use them"
        )

    def _new_project(self):
        name = self._name_edit.text().strip() or "untitled"
        self._state.new_project(name)

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
