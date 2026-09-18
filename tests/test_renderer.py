"""
Tests for elitis.core.renderer.

All tests exercise the rendering pipeline with no Qt dependency.
"""
import pytest
from pathlib import Path
from PIL import Image

from elitis.core import renderer
from elitis.core.models import Project, ThumbnailItem, FIELD_DEFAULTS, ItemSettings
from elitis.core.renderer import (
    _apply_framing, _composite_box, _wrap_text, _fit_text,
    _apply_transform, _fit_to_preview, _safe_filename, _checkerboard,
    _load_background,
)


# ---------------------------------------------------------------------------
# render_thumbnail — integration
# ---------------------------------------------------------------------------

class TestRenderThumbnail:
    def test_no_image_returns_checkerboard_size(self, empty_project, font_manager):
        item = empty_project.add_item("Test")
        img = renderer.render_thumbnail(item, empty_project, font_manager)
        cfg = empty_project.resolve_item(item)
        assert img.size == (cfg.canvas_width, cfg.canvas_height)

    def test_with_image_returns_correct_size(self, empty_project, font_manager, tiny_image_file):
        item = empty_project.add_item("Test")
        item.image_path = str(tiny_image_file)
        img = renderer.render_thumbnail(item, empty_project, font_manager)
        cfg = empty_project.resolve_item(item)
        assert img.size == (cfg.canvas_width, cfg.canvas_height)

    def test_corrupt_image_falls_back_to_checkerboard(self, empty_project, font_manager, tmp_path):
        corrupt = tmp_path / "bad.png"
        corrupt.write_bytes(b"not an image")
        item = empty_project.add_item("Test")
        item.image_path = str(corrupt)
        img = renderer.render_thumbnail(item, empty_project, font_manager)
        cfg = empty_project.resolve_item(item)
        assert img.size == (cfg.canvas_width, cfg.canvas_height)

    def test_missing_image_falls_back_to_checkerboard(self, empty_project, font_manager, tmp_path):
        item = empty_project.add_item("Test")
        item.image_path = str(tmp_path / "missing.png")
        img = renderer.render_thumbnail(item, empty_project, font_manager)
        assert img.size == (FIELD_DEFAULTS["canvas_width"], FIELD_DEFAULTS["canvas_height"])

    def test_empty_label_skips_text_layer(self, empty_project, font_manager):
        item = empty_project.add_item("")
        img = renderer.render_thumbnail(item, empty_project, font_manager)
        assert img is not None

    def test_preview_size_scales_down(self, empty_project, font_manager):
        item = empty_project.add_item("X")
        img = renderer.render_thumbnail(item, empty_project, font_manager, preview_size=(320, 180))
        assert img.width <= 320
        assert img.height <= 180

    def test_preview_size_never_upscales(self, empty_project, font_manager):
        """A preview_size larger than the canvas must not upscale."""
        item = empty_project.add_item("X")
        cfg = empty_project.resolve_item(item)
        big = (cfg.canvas_width * 4, cfg.canvas_height * 4)
        img = renderer.render_thumbnail(item, empty_project, font_manager, preview_size=big)
        assert img.width <= cfg.canvas_width
        assert img.height <= cfg.canvas_height

    def test_result_is_rgba(self, empty_project, font_manager):
        item = empty_project.add_item("X")
        img = renderer.render_thumbnail(item, empty_project, font_manager)
        assert img.mode == "RGBA"

    def test_outline_enabled(self, empty_project, font_manager):
        empty_project.defaults.settings.get("outline_enabled").value = True
        empty_project.defaults.settings.get("outline_enabled").use_default = False
        item = empty_project.add_item("Hello")
        img = renderer.render_thumbnail(item, empty_project, font_manager)
        assert img.size == (FIELD_DEFAULTS["canvas_width"], FIELD_DEFAULTS["canvas_height"])

    def test_shadow_enabled(self, empty_project, font_manager):
        s = empty_project.defaults.settings
        s.get("shadow_enabled").value = True
        s.get("shadow_enabled").use_default = False
        item = empty_project.add_item("Shadow")
        img = renderer.render_thumbnail(item, empty_project, font_manager)
        assert img.mode == "RGBA"

    def test_shadow_with_blur(self, empty_project, font_manager):
        s = empty_project.defaults.settings
        s.get("shadow_enabled").value = True
        s.get("shadow_enabled").use_default = False
        s.get("shadow_blur").value = 8
        s.get("shadow_blur").use_default = False
        item = empty_project.add_item("Blurred shadow")
        img = renderer.render_thumbnail(item, empty_project, font_manager)
        assert img.mode == "RGBA"

    def test_box_disabled(self, empty_project, font_manager):
        s = empty_project.defaults.settings
        s.get("box_enabled").value = False
        s.get("box_enabled").use_default = False
        item = empty_project.add_item("No box")
        img = renderer.render_thumbnail(item, empty_project, font_manager)
        assert img.size == (FIELD_DEFAULTS["canvas_width"], FIELD_DEFAULTS["canvas_height"])

    def test_text_transform_upper(self, empty_project, font_manager):
        s = empty_project.defaults.settings
        s.get("text_transform").value = "upper"
        s.get("text_transform").use_default = False
        item = empty_project.add_item("hello")
        # Should not crash even with transform applied
        img = renderer.render_thumbnail(item, empty_project, font_manager)
        assert img.mode == "RGBA"


# ---------------------------------------------------------------------------
# render_all
# ---------------------------------------------------------------------------

class TestRenderAll:
    def test_saves_files(self, small_project, font_manager, tmp_path):
        paths = renderer.render_all(small_project, font_manager, tmp_path)
        assert len(paths) == 3
        for p in paths:
            assert p.exists()

    def test_progress_callback(self, small_project, font_manager, tmp_path):
        calls = []
        renderer.render_all(small_project, font_manager, tmp_path,
                            on_progress=lambda d, t, p: calls.append((d, t)))
        assert len(calls) == 3
        assert calls[-1] == (3, 3)

    def test_jpeg_output(self, small_project, font_manager, tmp_path):
        paths = renderer.render_all(small_project, font_manager, tmp_path, fmt="JPEG")
        for p in paths:
            assert p.suffix == ".jpg"

    def test_creates_output_dir(self, small_project, font_manager, tmp_path):
        out = tmp_path / "new" / "subdir"
        renderer.render_all(small_project, font_manager, out)
        assert out.exists()

    def test_returns_empty_for_no_items(self, empty_project, font_manager, tmp_path):
        paths = renderer.render_all(empty_project, font_manager, tmp_path)
        assert paths == []


# ---------------------------------------------------------------------------
# _apply_framing — all modes produce correct output size
# ---------------------------------------------------------------------------

class TestApplyFraming:
    def _cfg(self, fit: str, **overrides):
        from elitis.core.models import ResolvedSettings
        defaults = {f: FIELD_DEFAULTS[f] for f in FIELD_DEFAULTS}
        defaults["image_fit"] = fit
        defaults.update(overrides)
        return ResolvedSettings(**defaults)

    def _landscape(self):
        return Image.new("RGBA", (400, 300))

    def _portrait(self):
        return Image.new("RGBA", (300, 600))

    def _square(self):
        return Image.new("RGBA", (200, 200))

    def _output_size(self, cfg):
        return (cfg.canvas_width, cfg.canvas_height)

    @pytest.mark.parametrize("fit", ["fill", "fit", "stretch", "center", "zoom"])
    def test_output_size_landscape(self, fit):
        cfg = self._cfg(fit)
        result = _apply_framing(self._landscape(), cfg)
        assert result.size == self._output_size(cfg)

    @pytest.mark.parametrize("fit", ["fill", "fit", "stretch", "center", "zoom"])
    def test_output_size_portrait(self, fit):
        cfg = self._cfg(fit)
        result = _apply_framing(self._portrait(), cfg)
        assert result.size == self._output_size(cfg)

    @pytest.mark.parametrize("fit", ["fill", "fit", "stretch", "center", "zoom"])
    def test_output_size_square(self, fit):
        cfg = self._cfg(fit)
        result = _apply_framing(self._square(), cfg)
        assert result.size == self._output_size(cfg)

    @pytest.mark.parametrize("fit", ["fill", "fit", "stretch", "center", "zoom"])
    def test_output_size_tiny_1x1(self, fit):
        cfg = self._cfg(fit)
        tiny = Image.new("RGBA", (1, 1), (255, 0, 0, 255))
        result = _apply_framing(tiny, cfg)
        assert result.size == self._output_size(cfg)

    def test_fill_with_crop_still_correct_size(self):
        cfg = self._cfg("fill", crop_x=0.1, crop_y=0.1, crop_w=0.8, crop_h=0.8)
        result = _apply_framing(self._landscape(), cfg)
        assert result.size == (cfg.canvas_width, cfg.canvas_height)

    def test_zoom_with_crop_still_correct_size(self):
        cfg = self._cfg("zoom", crop_x=0.2, crop_y=0.2, crop_w=0.5, crop_h=0.5)
        result = _apply_framing(self._landscape(), cfg)
        assert result.size == (cfg.canvas_width, cfg.canvas_height)


# ---------------------------------------------------------------------------
# _composite_box
# ---------------------------------------------------------------------------

class TestCompositeBox:
    def _cfg(self, **overrides):
        from elitis.core.models import ResolvedSettings
        d = {f: FIELD_DEFAULTS[f] for f in FIELD_DEFAULTS}
        d.update(overrides)
        return ResolvedSettings(**d)

    def test_disabled_returns_same_image(self):
        cfg = self._cfg(box_enabled=False)
        img = Image.new("RGBA", (100, 100), (50, 100, 150, 255))
        result = _composite_box(img, cfg)
        assert result.tobytes() == img.tobytes()

    def test_enabled_modifies_image(self):
        cfg = self._cfg(box_enabled=True, box_position="bottom",
                        box_height=0.5, box_opacity=255, box_color=(255, 0, 0))
        img = Image.new("RGBA", (100, 100), (0, 0, 0, 255))
        result = _composite_box(img, cfg)
        # Bottom half should now be red
        px = result.getpixel((50, 99))
        assert px[0] == 255  # red channel

    def test_box_position_top(self):
        cfg = self._cfg(box_enabled=True, box_position="top",
                        box_height=0.5, box_opacity=255, box_color=(0, 255, 0))
        img = Image.new("RGBA", (100, 100), (0, 0, 0, 255))
        result = _composite_box(img, cfg)
        px_top = result.getpixel((50, 1))
        assert px_top[1] == 255  # green

    def test_box_position_full(self):
        cfg = self._cfg(box_enabled=True, box_position="full",
                        box_height=1.0, box_opacity=128, box_color=(255, 255, 255))
        img = Image.new("RGBA", (100, 100), (0, 0, 0, 255))
        result = _composite_box(img, cfg)
        assert result.size == img.size


# ---------------------------------------------------------------------------
# _wrap_text
# ---------------------------------------------------------------------------

class TestWrapText:
    def _font(self, size=20):
        from elitis.core.font_manager import FontManager
        from pathlib import Path
        # Use a font manager with no fonts — always returns the default font
        fm = FontManager(Path("/nonexistent"))
        return fm.get_pil_font("none", size)

    def test_short_text_single_line(self):
        font = self._font()
        lines = _wrap_text("Hi", font, 1000)
        assert len(lines) == 1
        assert lines[0] == "Hi"

    def test_empty_string_returns_one_empty_line(self):
        font = self._font()
        lines = _wrap_text("", font, 1000)
        assert lines == [""]

    def test_long_text_wraps(self):
        font = self._font(20)
        long = "This is a very long piece of text that should definitely wrap"
        lines = _wrap_text(long, font, 100)
        assert len(lines) > 1

    def test_single_long_word_stays_on_one_line(self):
        """A word wider than max_width is placed on its own line — no char splitting."""
        font = self._font(40)
        lines = _wrap_text("Supercalifragilistic", font, 10)
        assert len(lines) == 1


# ---------------------------------------------------------------------------
# _apply_transform
# ---------------------------------------------------------------------------

class TestApplyTransform:
    def test_none(self):       assert _apply_transform("Hello World", "none")  == "Hello World"
    def test_upper(self):      assert _apply_transform("Hello World", "upper") == "HELLO WORLD"
    def test_lower(self):      assert _apply_transform("Hello World", "lower") == "hello world"
    def test_title(self):      assert _apply_transform("hello world", "title") == "Hello World"
    def test_unknown(self):    assert _apply_transform("Hello", "bogus") == "Hello"


# ---------------------------------------------------------------------------
# _safe_filename
# ---------------------------------------------------------------------------

class TestSafeFilename:
    def test_alphanumeric_unchanged(self):
        assert _safe_filename("Hello123") == "Hello123"

    def test_special_chars_replaced(self):
        result = _safe_filename("A/B\\C:D*E?F")
        assert "/" not in result
        assert "\\" not in result
        assert ":" not in result

    def test_spaces_kept(self):
        assert " " in _safe_filename("hello world")

    def test_hyphens_kept(self):
        assert "-" in _safe_filename("hello-world")

    def test_underscore_kept(self):
        assert "_" in _safe_filename("hello_world")

    def test_truncates_at_max_len(self):
        result = _safe_filename("a" * 100)
        assert len(result) <= 60

    def test_custom_max_len(self):
        result = _safe_filename("a" * 100, max_len=10)
        assert len(result) <= 10

    def test_empty_string_returns_item(self):
        assert _safe_filename("") == "item"

    def test_all_special_chars_returns_underscores(self):
        # Special chars are replaced with _, which is not whitespace, so the
        # result is "___" not "item".  Only a truly empty/whitespace-only
        # input falls back to "item".
        assert _safe_filename("!!!") == "___"

    def test_whitespace_only_returns_item(self):
        assert _safe_filename("   ") == "item"


# ---------------------------------------------------------------------------
# _checkerboard
# ---------------------------------------------------------------------------

class TestCheckerboard:
    def test_correct_size(self):
        img = _checkerboard(320, 180)
        assert img.size == (320, 180)

    def test_is_rgba(self):
        img = _checkerboard(10, 10)
        assert img.mode == "RGBA"

    def test_alternating_colors(self):
        img = _checkerboard(80, 80, sq=40)
        light = img.getpixel((0, 0))
        dark  = img.getpixel((40, 0))
        assert light != dark

    def test_1x1(self):
        img = _checkerboard(1, 1)
        assert img.size == (1, 1)


# ---------------------------------------------------------------------------
# _fit_to_preview
# ---------------------------------------------------------------------------

class TestFitToPreview:
    def test_scales_down_large_image(self):
        img = Image.new("RGBA", (1280, 720))
        result = _fit_to_preview(img, (320, 180))
        assert result.width <= 320
        assert result.height <= 180

    def test_does_not_upscale(self):
        img = Image.new("RGBA", (100, 100))
        result = _fit_to_preview(img, (1000, 1000))
        # thumbnail() never upscales
        assert result.size == (100, 100)

    def test_preserves_aspect_ratio(self):
        img = Image.new("RGBA", (640, 360))
        result = _fit_to_preview(img, (320, 240))
        # 640:360 = 16:9; at 320 wide → 180 tall
        assert result.width == 320
        assert result.height == 180
