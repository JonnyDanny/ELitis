"""
BaseAppState — shared session state for both the Qt desktop app and the
Colab notebook frontend.

Owns the live Project, FontManager, and directory paths.  All model
mutations go through the write-boundary methods here so dirty tracking
stays consistent regardless of which frontend is driving.

Subclasses override the _on_* hook methods to react to state changes in
whatever way their event system requires (Qt signals, ipywidgets observers,
or a plain print()).
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from elitis.core.models import Project, ThumbnailItem
from elitis.core.font_manager import FontManager
from elitis.core import data_io, renderer


class BaseAppState:

    def __init__(
        self,
        projects_dir: Path,
        egest_dir: Path,
        fonts_dir: Path,
        **kwargs,
    ):
        super().__init__(**kwargs)   # forwards parent= to QObject in the MRO chain
        self.projects_dir = projects_dir
        self.egest_dir    = egest_dir

        self._font_manager  = FontManager(fonts_dir)
        self._project       = Project.new("untitled", str(egest_dir))
        self._current_index = 1
        self._project_path: Optional[Path] = None
        self._clean_ids: set[str] = set()
        self._defaults_dirty = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def font_manager(self) -> FontManager:
        return self._font_manager

    @property
    def project(self) -> Project:
        return self._project

    @property
    def current_index(self) -> int:
        return self._current_index

    @property
    def current_item(self) -> ThumbnailItem:
        items = self._project.items
        idx = max(0, min(self._current_index, len(items) - 1))
        return items[idx]

    @property
    def defaults(self) -> ThumbnailItem:
        return self._project.defaults

    @property
    def defaults_dirty(self) -> bool:
        return self._defaults_dirty

    def item_count(self) -> int:
        return len(self._project.items)

    def content_count(self) -> int:
        return len(self._project.content_items)

    # ------------------------------------------------------------------
    # Hooks — override in subclasses to wire up event systems
    # ------------------------------------------------------------------

    def _on_changed(self, item: ThumbnailItem) -> None:
        """Called after any setting mutation on *item*."""

    def _on_navigation_changed(self, index: int) -> None:
        """Called after the current item index changes."""

    def _on_project_replaced(self) -> None:
        """Called after the project is swapped or its item list restructured."""

    def _on_items_status_changed(self) -> None:
        """Called after clean/dirty export status changes on any item."""

    def _on_status_message(self, msg: str) -> None:
        """Called to surface a status message (progress, warnings, errors)."""

    def _on_warnings(self, warnings: list) -> None:
        """Called after render_all() with the full list of RenderWarnings.
        Qt: updates warnings panel. Colab: displays inline table. CLI: stderr."""

    # ------------------------------------------------------------------
    # Internal reaction — dirty tracking + hook dispatch
    # ------------------------------------------------------------------

    def _react(self, item: ThumbnailItem) -> None:
        if item.is_default:
            self._defaults_dirty = True
        else:
            self._clean_ids.discard(item.id)
        self._on_changed(item)

    def _autosave(self) -> None:
        """Save to the current project path if one is known, silently."""
        if self._project_path:
            try:
                data_io.save_project(self._project, self._project_path)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def go_to(self, index: int) -> None:
        count = self.item_count()
        index = max(0, min(index, count - 1))
        if index != self._current_index:
            self._current_index = index
            self._on_navigation_changed(index)

    def go_next(self) -> None:
        self.go_to(self._current_index + 1)

    def go_prev(self) -> None:
        self.go_to(self._current_index - 1)

    def go_to_defaults(self) -> None:
        self.go_to(0)

    # ------------------------------------------------------------------
    # Write boundary — all model mutations go through these methods
    # ------------------------------------------------------------------

    def commit_field(
        self,
        field_name: str,
        value,
        use_default: bool = False,
        item: ThumbnailItem | None = None,
    ) -> None:
        target = item or self.current_item
        sf = target.settings.get(field_name)
        sf.value = value
        sf.use_default = use_default
        self._react(target)

    def commit_crop(self, x: float, y: float, w: float, h: float) -> None:
        item = self.current_item
        for field, val in (('crop_x', x), ('crop_y', y), ('crop_w', w), ('crop_h', h)):
            sf = item.settings.get(field)
            sf.value = round(val, 4)
            sf.use_default = False
        self._react(item)

    def commit_label(self, item_id: str, label: str) -> None:
        item = self._project.find_item(item_id)
        if item:
            item.label = label
            self._react(item)
            self._autosave()

    def commit_image(self, item_id: str, path: str | None) -> None:
        item = self._project.find_item(item_id)
        if item:
            item.image_path = path
            self._react(item)
            self._autosave()

    def set_image_for_current(self, path: str) -> None:
        self.commit_image(self.current_item.id, path)

    def insert_item(self, at_content_index: int, label: str = "") -> ThumbnailItem:
        item = ThumbnailItem.new_item(label)
        self._project.items.insert(at_content_index + 1, item)
        self._on_project_replaced()
        return item

    def remove_item(self, item_id: str) -> None:
        self._project.remove_item(item_id)
        self._clean_ids.discard(item_id)
        self._on_project_replaced()

    def move_item(self, content_row: int, delta: int) -> None:
        items = self._project.items
        pi, pi2 = content_row + 1, content_row + delta + 1
        if 1 <= pi < len(items) and 1 <= pi2 < len(items):
            items[pi], items[pi2] = items[pi2], items[pi]
            self._on_project_replaced()

    def replace_items(self, new_content: list) -> None:
        self._project.items = [self._project.defaults] + new_content
        self._on_project_replaced()

    # ------------------------------------------------------------------
    # Export status tracking
    # ------------------------------------------------------------------

    def is_clean(self, item_id: str) -> bool:
        return item_id in self._clean_ids

    def mark_rendered(self, item_id: str) -> None:
        self._clean_ids.add(item_id)
        self._on_items_status_changed()

    def mark_all_rendered(self) -> None:
        self._clean_ids = {i.id for i in self._project.content_items}
        self._on_items_status_changed()

    # ------------------------------------------------------------------
    # Project IO
    # ------------------------------------------------------------------

    def new_project(self, name: str = "untitled") -> None:
        self._project = Project.new(name, str(self.egest_dir))
        self._project_path = None
        self._current_index = 0
        self._clean_ids.clear()
        self._defaults_dirty = False
        self._on_project_replaced()
        self._on_navigation_changed(0)

    def save_project(self) -> Path:
        if self._project_path is None:
            safe = self._project.name.replace(" ", "_")
            self._project_path = self.projects_dir / f"{safe}.json"
        data_io.save_project(self._project, self._project_path)
        self._on_status_message(f"Saved: {self._project_path.name}")
        return self._project_path

    def save_project_as(self, path: Path) -> None:
        self._project_path = path
        data_io.save_project(self._project, path)
        self._on_status_message(f"Saved: {path.name}")

    def load_project(self, path: Path) -> None:
        self._project = data_io.load_project(path)
        self._project_path = path
        self._current_index = min(1, len(self._project.items) - 1)
        self._clean_ids.clear()
        self._defaults_dirty = False
        self._font_manager.scan()
        self._on_project_replaced()
        self._on_navigation_changed(self._current_index)

    def import_labels(self, source_path: Path, column: int = 0) -> int:
        labels = data_io.import_labels(source_path, column)
        for lbl in labels:
            self._project.add_item(lbl)
        if labels:
            self._on_project_replaced()
            self.go_to(1)
        return len(labels)

    def export_batch(self, fmt: str = "PNG") -> list[Path]:
        out_dir = Path(self._project.output_dir)
        if not out_dir.is_absolute():
            out_dir = self.egest_dir / self._project.name

        def _progress(done, total, path):
            self._on_status_message(f"Saved {done}/{total}: {path.name}")

        saved, warnings = renderer.render_all(
            self._project, self._font_manager, out_dir,
            fmt=fmt, on_progress=_progress,
        )
        self.mark_all_rendered()
        self._on_warnings(warnings)
        self._autosave()
        return saved, warnings
