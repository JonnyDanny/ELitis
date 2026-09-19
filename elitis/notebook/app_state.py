"""
NotebookAppState — BaseAppState subclass for the Jupyter/Colab frontend.

Overrides the _on_* hooks to print status and display ipywidgets output
instead of emitting Qt signals.  Usable in place of operating directly on
the Project object when you want coordinated dirty tracking and the full
write-boundary across multiple notebook cells.
"""
from __future__ import annotations
from pathlib import Path

from elitis.core.app_state import BaseAppState


class NotebookAppState(BaseAppState):

    def __init__(
        self,
        projects_dir: Path,
        egest_dir: Path,
        fonts_dir: Path,
        *,
        verbose: bool = True,
    ):
        super().__init__(projects_dir, egest_dir, fonts_dir)
        self._verbose = verbose

    # ------------------------------------------------------------------
    # Hook overrides
    # ------------------------------------------------------------------

    def _on_status_message(self, msg: str) -> None:
        if self._verbose:
            print(msg)

    def _on_warnings(self, warnings: list) -> None:
        if not warnings:
            return
        from IPython.display import display
        from elitis.notebook.display import show_warnings
        display(show_warnings(warnings))

    def _on_changed(self, item) -> None:
        pass  # no live preview in notebook; user re-runs Cell 4

    def _on_navigation_changed(self, index: int) -> None:
        pass

    def _on_project_replaced(self) -> None:
        if self._verbose:
            n = len(self._project.content_items)
            print(f"Project updated: {n} item(s)")

    def _on_items_status_changed(self) -> None:
        pass
