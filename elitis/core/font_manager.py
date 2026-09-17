"""
Loads .ttf/.otf fonts from a project-local Fonts/ directory.

Responsibilities:
  - Scan the directory on init (and on explicit refresh)
  - Register fonts with Qt for UI use
  - Provide cached PIL ImageFont objects for rendering
  - Fall back to PIL's built-in default when a name is not found
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
from functools import lru_cache

from PIL import ImageFont


_FONT_EXTS = {".ttf", ".otf"}


class FontManager:
    def __init__(self, fonts_dir: Path):
        self._dir = fonts_dir
        self._paths: dict[str, Path] = {}   # lower-stem → path
        self._qt_registered = False
        self.scan()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def scan(self):
        self._paths.clear()
        if not self._dir.exists():
            return
        for p in self._dir.rglob("*"):
            if p.is_file() and p.suffix.lower() in _FONT_EXTS:
                self._paths[p.stem.lower()] = p

    def register_with_qt(self):
        """Register all fonts with Qt's font database (call once after QApplication exists)."""
        if self._qt_registered:
            return
        try:
            from PySide6.QtGui import QFontDatabase
            for path in self._paths.values():
                QFontDatabase.addApplicationFont(str(path))
            self._qt_registered = True
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    @property
    def available(self) -> list[str]:
        """Sorted list of font stem names (lowercase)."""
        return sorted(self._paths)

    def path_for(self, name: str) -> Optional[Path]:
        return self._paths.get(name.lower())

    def get_pil_font(self, name: str, size: int) -> ImageFont.FreeTypeFont:
        """Return a cached PIL font. Falls back to the built-in default."""
        return _cached_font(str(self._paths.get(name.lower(), "")), size)

    def default_pil_font(self, size: int) -> ImageFont.ImageFont:
        return ImageFont.load_default(size=size)


@lru_cache(maxsize=256)
def _cached_font(path_str: str, size: int):
    """LRU-cached font loader — avoids re-parsing font files on every render."""
    if path_str:
        try:
            return ImageFont.truetype(path_str, size)
        except Exception:
            pass
    return ImageFont.load_default(size=size)
