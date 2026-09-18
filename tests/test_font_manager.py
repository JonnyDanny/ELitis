"""Tests for elitis.core.font_manager."""
import pytest
from pathlib import Path
from PIL import ImageFont

from elitis.core.font_manager import FontManager


class TestFontManagerScan:
    def test_no_fonts_dir_is_ok(self, tmp_path):
        fm = FontManager(tmp_path / "NonExistent")
        assert fm.available == []

    def test_empty_fonts_dir(self, tmp_path):
        fonts = tmp_path / "Fonts"
        fonts.mkdir()
        fm = FontManager(fonts)
        assert fm.available == []

    def test_discovers_ttf(self, tmp_path):
        fonts = tmp_path / "Fonts"
        fonts.mkdir()
        (fonts / "Fake.ttf").write_bytes(b"")  # empty — just needs to exist for scan
        fm = FontManager(fonts)
        assert "fake" in fm.available

    def test_discovers_otf(self, tmp_path):
        fonts = tmp_path / "Fonts"
        fonts.mkdir()
        (fonts / "Mono.otf").write_bytes(b"")
        fm = FontManager(fonts)
        assert "mono" in fm.available

    def test_ignores_non_font_extensions(self, tmp_path):
        fonts = tmp_path / "Fonts"
        fonts.mkdir()
        for name in ("README.txt", "image.png", "data.json"):
            (fonts / name).write_bytes(b"")
        fm = FontManager(fonts)
        assert fm.available == []

    def test_scans_subdirectories(self, tmp_path):
        fonts = tmp_path / "Fonts"
        sub = fonts / "Sub"
        sub.mkdir(parents=True)
        (sub / "Deep.ttf").write_bytes(b"")
        fm = FontManager(fonts)
        assert "deep" in fm.available

    def test_stem_is_lowercase(self, tmp_path):
        fonts = tmp_path / "Fonts"
        fonts.mkdir()
        (fonts / "MyFont.ttf").write_bytes(b"")
        fm = FontManager(fonts)
        assert "myfont" in fm.available
        assert "MyFont" not in fm.available

    def test_available_is_sorted(self, tmp_path):
        fonts = tmp_path / "Fonts"
        fonts.mkdir()
        for name in ("Zebra.ttf", "Alpha.ttf", "Mango.ttf"):
            (fonts / name).write_bytes(b"")
        fm = FontManager(fonts)
        assert fm.available == sorted(fm.available)

    def test_rescan_updates_after_new_file(self, tmp_path):
        fonts = tmp_path / "Fonts"
        fonts.mkdir()
        fm = FontManager(fonts)
        assert fm.available == []
        (fonts / "New.ttf").write_bytes(b"")
        fm.scan()
        assert "new" in fm.available

    def test_path_for_case_insensitive(self, tmp_path):
        fonts = tmp_path / "Fonts"
        fonts.mkdir()
        (fonts / "MyFont.ttf").write_bytes(b"")
        fm = FontManager(fonts)
        assert fm.path_for("myfont") is not None
        assert fm.path_for("MYFONT") is not None
        assert fm.path_for("MyFont") is not None

    def test_path_for_unknown_returns_none(self, tmp_path):
        fm = FontManager(tmp_path / "Empty")
        assert fm.path_for("doesnotexist") is None


class TestFontManagerGetFont:
    def test_unknown_font_returns_default(self, font_manager):
        """An unknown font name falls back to PIL's built-in — no crash."""
        font = font_manager.get_pil_font("nonexistent_xyz", 32)
        assert font is not None

    def test_real_font_returns_freetype(self, font_manager_with_font):
        fonts = font_manager_with_font.available
        font = font_manager_with_font.get_pil_font(fonts[0], 32)
        assert isinstance(font, ImageFont.FreeTypeFont)

    def test_default_font_different_sizes(self, font_manager):
        f1 = font_manager.get_pil_font("none", 20)
        f2 = font_manager.get_pil_font("none", 40)
        assert f1 is not f2   # different sizes → different objects

    def test_same_name_size_cached(self, font_manager):
        f1 = font_manager.get_pil_font("none", 30)
        f2 = font_manager.get_pil_font("none", 30)
        assert f1 is f2   # LRU cache should return the same object

    def test_default_pil_font(self, font_manager):
        font = font_manager.default_pil_font(24)
        assert font is not None
