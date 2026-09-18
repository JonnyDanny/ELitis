"""
Loads .ttf/.otf fonts from a project-local Fonts/ directory.

Responsibilities
----------------
- Scan the directory on init (and on explicit refresh via ``scan()``).
- Register fonts with Qt's font database for UI use (widgets, labels).
- Provide cached PIL ImageFont objects for the rendering pipeline.
- Fall back to PIL's built-in bitmap font when a requested name is not found.

The Qt registration and PIL font loading are independent: a font only needs to
be in ``_paths`` to be usable for rendering; Qt registration is only needed if
you want Qt widgets to also display the font.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
from functools import lru_cache

from PIL import ImageFont


_FONT_EXTS = {".ttf", ".otf"}


class FontManager:
    """
    Discovers and caches fonts from a directory tree.

    The internal ``_paths`` dict maps lowercase font *stem* names to Path objects.
    For example, a file ``Fonts/Fredoka/Fredoka-Bold.ttf`` is registered under the
    key ``"fredoka-bold"``.  Lookups are always case-insensitive.
    """

    def __init__(self, fonts_dir: Path):
        self._dir = fonts_dir
        self._paths: dict[str, Path] = {}   # lowercase stem → Path
        self._qt_registered = False
        self.scan()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def scan(self):
        """
        (Re)scan the fonts directory and rebuild the internal path map.

        Walks the directory recursively so fonts in subdirectories are found.
        Safe to call even if the directory does not exist yet.
        """
        self._paths.clear()
        if not self._dir.exists():
            return
        for p in self._dir.rglob("*"):
            if p.is_file() and p.suffix.lower() in _FONT_EXTS:
                self._paths[p.stem.lower()] = p

    def register_with_qt(self):
        """
        Register all discovered fonts with Qt's font database.

        Must be called after ``QApplication`` exists.  Idempotent — subsequent calls
        are no-ops.  Silently skipped when PySide6 is not importable (e.g. in tests).
        """
        if self._qt_registered:
            return
        try:
            from PySide6.QtGui import QFontDatabase
            for path in self._paths.values():
                QFontDatabase.addApplicationFont(str(path))
            self._qt_registered = True
        except Exception:
            pass   # PySide6 unavailable (e.g. during headless testing)

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    @property
    def available(self) -> list[str]:
        """Sorted list of discovered font stem names (all lowercase)."""
        return sorted(self._paths)

    def path_for(self, name: str) -> Optional[Path]:
        """Return the file path for *name* (case-insensitive), or None if not found."""
        return self._paths.get(name.lower())

    def get_pil_font(self, name: str, size: int) -> ImageFont.FreeTypeFont:
        """
        Return a PIL font for rendering.

        Results are LRU-cached on (path, size) to avoid re-parsing font files on
        every render call.  Falls back to PIL's built-in bitmap font when *name* is
        not in the font directory; this ensures rendering never fails due to a missing
        font, at the cost of a less polished look.
        """
        return _cached_font(str(self._paths.get(name.lower(), "")), size)

    def default_pil_font(self, size: int) -> ImageFont.ImageFont:
        """Return PIL's built-in bitmap font at *size* (no file required)."""
        return ImageFont.load_default(size=size)


@lru_cache(maxsize=256)
def _cached_font(path_str: str, size: int):
    """
    Module-level LRU-cached loader shared across all FontManager instances.

    Keyed on the absolute path string and size so the same physical font file at
    different sizes occupies separate cache slots.  Falls back to the built-in
    bitmap font when *path_str* is empty or the file cannot be opened.
    """
    if path_str:
        try:
            return ImageFont.truetype(path_str, size)
        except Exception:
            pass   # corrupt file or unsupported format — use default below
    return ImageFont.load_default(size=size)
