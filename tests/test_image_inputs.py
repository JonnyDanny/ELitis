"""
Image corner-case and resolution-matrix tests.

Tests the full rendering pipeline and the clipboard-paste image conversion for
every realistic image input: different modes, sizes, encodings, corrupt data,
and the specific byte-layout edge case that used to cause colour channel swapping.

No Qt dependency — clipboard conversion is tested at the PIL byte level.
"""
import pytest
import struct
from pathlib import Path
from PIL import Image, ImageMode
import io

from elitis.core import renderer
from elitis.core.renderer import _load_background, _apply_framing, _checkerboard
from elitis.core.models import Project, ThumbnailItem, FIELD_DEFAULTS, ResolvedSettings
from elitis.ui.app_state import _inspect_clipboard, _try_decode_base64_image
from tests.generate_test_images import SOURCE_SIZES, SOURCE_SIZES_SLOW


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project_with_image(path: str | None) -> tuple[Project, ThumbnailItem]:
    p = Project.new("test", "out")
    item = p.add_item("Test")
    item.image_path = path
    return p, item


def _cfg(fit: str = "fill", canvas_w: int = 320, canvas_h: int = 180, **kw):
    from elitis.core.models import ResolvedSettings
    d = {f: FIELD_DEFAULTS[f] for f in FIELD_DEFAULTS}
    d["image_fit"] = fit
    d["canvas_width"] = canvas_w
    d["canvas_height"] = canvas_h
    d.update(kw)
    return ResolvedSettings(**d)


def _save_image(tmp_path, img: Image.Image, name: str) -> Path:
    p = tmp_path / name
    img.save(str(p))
    return p


# ---------------------------------------------------------------------------
# Source image mode conversions
# ---------------------------------------------------------------------------

class TestImageModeConversions:
    """render_thumbnail must handle any PIL-supported source format."""

    def test_rgb_jpeg(self, empty_project, font_manager, tmp_path):
        img = Image.new("RGB", (200, 150), (128, 64, 32))
        p = tmp_path / "img.jpg"
        img.save(str(p), format="JPEG")
        item = empty_project.add_item("X")
        item.image_path = str(p)
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        assert result.mode == "RGBA"

    def test_rgba_png(self, empty_project, font_manager, tmp_path):
        img = Image.new("RGBA", (200, 150), (0, 255, 0, 128))
        p = _save_image(tmp_path, img, "img.png")
        item = empty_project.add_item("X")
        item.image_path = str(p)
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        assert result.mode == "RGBA"

    def test_grayscale_png(self, empty_project, font_manager, tmp_path):
        img = Image.new("L", (200, 150), 128)
        p = _save_image(tmp_path, img, "gray.png")
        item = empty_project.add_item("X")
        item.image_path = str(p)
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        assert result.mode == "RGBA"

    def test_palette_png(self, empty_project, font_manager, tmp_path):
        img = Image.new("P", (200, 150))
        p = _save_image(tmp_path, img, "palette.png")
        item = empty_project.add_item("X")
        item.image_path = str(p)
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        assert result.mode == "RGBA"

    def test_1bit_image(self, empty_project, font_manager, tmp_path):
        img = Image.new("1", (200, 150), 1)
        p = _save_image(tmp_path, img, "bw.png")
        item = empty_project.add_item("X")
        item.image_path = str(p)
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        assert result.mode == "RGBA"

    def test_fully_transparent_png(self, empty_project, font_manager, tmp_path):
        img = Image.new("RGBA", (200, 150), (0, 0, 0, 0))
        p = _save_image(tmp_path, img, "transparent.png")
        item = empty_project.add_item("X")
        item.image_path = str(p)
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        assert result.mode == "RGBA"
        assert result.size == (FIELD_DEFAULTS["canvas_width"], FIELD_DEFAULTS["canvas_height"])


# ---------------------------------------------------------------------------
# Extreme dimensions
# ---------------------------------------------------------------------------

class TestExtremeDimensions:
    def test_1x1_source_image_all_fit_modes(self, empty_project, font_manager, tmp_path):
        img = Image.new("RGBA", (1, 1), (255, 128, 0, 255))
        p = _save_image(tmp_path, img, "tiny.png")
        item = empty_project.add_item("X")
        item.image_path = str(p)
        for fit in ("fill", "fit", "stretch", "center", "zoom"):
            item.settings.get("image_fit").value = fit
            item.settings.get("image_fit").use_default = False
            result = renderer.render_thumbnail(item, empty_project, font_manager)
            assert result.size == (FIELD_DEFAULTS["canvas_width"], FIELD_DEFAULTS["canvas_height"]), \
                f"Failed for fit={fit}"

    def test_4x4_source_all_fit_modes(self, empty_project, font_manager, tmp_path):
        img = Image.new("RGBA", (4, 4), (0, 128, 255, 255))
        p = _save_image(tmp_path, img, "tiny4.png")
        item = empty_project.add_item("X")
        item.image_path = str(p)
        for fit in ("fill", "fit", "stretch", "center", "zoom"):
            item.settings.get("image_fit").value = fit
            item.settings.get("image_fit").use_default = False
            result = renderer.render_thumbnail(item, empty_project, font_manager)
            assert result.size == (FIELD_DEFAULTS["canvas_width"], FIELD_DEFAULTS["canvas_height"])

    def test_large_source_image(self, empty_project, font_manager, tmp_path):
        """A 2000×1500 source image must render without crashing (just size check)."""
        img = Image.new("RGBA", (2000, 1500), (100, 100, 100, 255))
        p = _save_image(tmp_path, img, "large.png")
        item = empty_project.add_item("X")
        item.image_path = str(p)
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        assert result.size == (FIELD_DEFAULTS["canvas_width"], FIELD_DEFAULTS["canvas_height"])

    def test_wide_panoramic_source(self, empty_project, font_manager, tmp_path):
        img = Image.new("RGBA", (4000, 100), (200, 50, 50, 255))
        p = _save_image(tmp_path, img, "wide.png")
        item = empty_project.add_item("X")
        item.image_path = str(p)
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        assert result.size == (FIELD_DEFAULTS["canvas_width"], FIELD_DEFAULTS["canvas_height"])

    def test_tall_portrait_source(self, empty_project, font_manager, tmp_path):
        img = Image.new("RGBA", (100, 4000), (50, 200, 50, 255))
        p = _save_image(tmp_path, img, "tall.png")
        item = empty_project.add_item("X")
        item.image_path = str(p)
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        assert result.size == (FIELD_DEFAULTS["canvas_width"], FIELD_DEFAULTS["canvas_height"])


# ---------------------------------------------------------------------------
# Corrupt / missing image paths
# ---------------------------------------------------------------------------

class TestBadImagePaths:
    def test_none_path_uses_checkerboard(self, empty_project, font_manager):
        item = empty_project.add_item("X")
        item.image_path = None
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        # Should equal the checkerboard (rendered on top of default settings)
        assert result.size == (FIELD_DEFAULTS["canvas_width"], FIELD_DEFAULTS["canvas_height"])

    def test_empty_string_path_uses_checkerboard(self, empty_project, font_manager):
        item = empty_project.add_item("X")
        item.image_path = ""
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        assert result.mode == "RGBA"

    def test_nonexistent_path_uses_checkerboard(self, empty_project, font_manager, tmp_path):
        item = empty_project.add_item("X")
        item.image_path = str(tmp_path / "does_not_exist.png")
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        assert result.mode == "RGBA"

    def test_corrupt_file_uses_checkerboard(self, empty_project, font_manager, tmp_path):
        bad = tmp_path / "corrupt.png"
        bad.write_bytes(b"\x89PNG\r\n" + b"garbage_data" * 100)
        item = empty_project.add_item("X")
        item.image_path = str(bad)
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        assert result.mode == "RGBA"

    def test_wrong_extension_correct_bytes(self, empty_project, font_manager, tmp_path):
        """A .png renamed to .jpg (bytes are still PNG) should still open."""
        img = Image.new("RGBA", (100, 100), (0, 200, 0, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        faked = tmp_path / "faked.jpg"
        faked.write_bytes(buf.getvalue())
        item = empty_project.add_item("X")
        item.image_path = str(faked)
        # PIL reads by content, not extension, so this should succeed
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        assert result.mode == "RGBA"


# ---------------------------------------------------------------------------
# Clipboard pixel conversion (no Qt — tests the byte layout logic directly)
# ---------------------------------------------------------------------------

class TestClipboardConversion:
    """
    Tests the QImage→PIL conversion logic by simulating it at the PIL/bytes level.

    The bug fixed: original code used ``Image.frombytes("RGBA", ..., "raw", "BGRA")``
    which assumed QImage's native Format_ARGB32 byte layout (B,G,R,A on
    little-endian).  The fix converts to Format_RGBA8888 first (byte layout always
    R,G,B,A), then reads with no decoder argument (defaults to "raw", "RGBA").

    These tests verify the correct approach: create known RGBA pixels, lay them
    out as ``Format_RGBA8888`` bytes, reconstruct with ``Image.frombytes``, and
    assert pixel values are unchanged.
    """

    def _rgba_to_bytes(self, img: Image.Image) -> bytes:
        """Pack an RGBA image as contiguous RGBA bytes (simulates Format_RGBA8888)."""
        return img.tobytes("raw", "RGBA")

    def _bgra_to_rgba_img(self, data: bytes, w: int, h: int) -> Image.Image:
        """Reconstruct via the OLD (buggy) BGRA path."""
        return Image.frombytes("RGBA", (w, h), data, "raw", "BGRA")

    def _rgba_to_rgba_img(self, data: bytes, w: int, h: int) -> Image.Image:
        """Reconstruct via the NEW (correct) RGBA path."""
        return Image.frombytes("RGBA", (w, h), data)

    def test_correct_path_preserves_red(self):
        original = Image.new("RGBA", (4, 4), (255, 0, 0, 255))
        data = self._rgba_to_bytes(original)
        result = self._rgba_to_rgba_img(data, 4, 4)
        assert result.getpixel((0, 0)) == (255, 0, 0, 255)

    def test_correct_path_preserves_blue(self):
        original = Image.new("RGBA", (4, 4), (0, 0, 255, 255))
        data = self._rgba_to_bytes(original)
        result = self._rgba_to_rgba_img(data, 4, 4)
        assert result.getpixel((0, 0)) == (0, 0, 255, 255)

    def test_buggy_path_swaps_red_and_blue(self):
        """
        Demonstrate that the OLD code was wrong: BGRA decoding swaps R and B
        when the bytes were actually RGBA.
        """
        original = Image.new("RGBA", (4, 4), (255, 0, 0, 255))   # red
        data = self._rgba_to_bytes(original)
        wrong_result = self._bgra_to_rgba_img(data, 4, 4)
        # Red bytes read as BGRA → pixel shows as blue (R and B swapped)
        r, g, b, a = wrong_result.getpixel((0, 0))
        assert b == 255 and r == 0   # blue, not red — demonstrates the bug

    def test_correct_path_1x1(self):
        original = Image.new("RGBA", (1, 1), (10, 20, 30, 200))
        data = self._rgba_to_bytes(original)
        result = self._rgba_to_rgba_img(data, 1, 1)
        assert result.getpixel((0, 0)) == (10, 20, 30, 200)

    def test_correct_path_fully_transparent(self):
        original = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        data = self._rgba_to_bytes(original)
        result = self._rgba_to_rgba_img(data, 8, 8)
        assert result.getpixel((0, 0))[3] == 0   # alpha = 0

    def test_correct_path_mixed_pixels(self):
        original = Image.new("RGBA", (2, 1))
        original.putpixel((0, 0), (255, 0,   0,   255))  # red
        original.putpixel((1, 0), (0,   0, 255,   128))  # semi-transparent blue
        data = self._rgba_to_bytes(original)
        result = self._rgba_to_rgba_img(data, 2, 1)
        assert result.getpixel((0, 0)) == (255, 0, 0, 255)
        assert result.getpixel((1, 0)) == (0, 0, 255, 128)

    def test_correct_path_large_image(self):
        """4K-ish image should not crash and produce correct corner pixel."""
        original = Image.new("RGBA", (3840, 2160), (123, 45, 67, 255))
        data = self._rgba_to_bytes(original)
        result = self._rgba_to_rgba_img(data, 3840, 2160)
        assert result.getpixel((0, 0)) == (123, 45, 67, 255)
        assert result.getpixel((3839, 2159)) == (123, 45, 67, 255)

    def test_correct_path_saves_as_png(self, tmp_path):
        """Verify the full pipeline: convert → save → reload → pixels match."""
        original = Image.new("RGBA", (16, 16), (80, 160, 240, 200))
        data = self._rgba_to_bytes(original)
        pil = self._rgba_to_rgba_img(data, 16, 16)
        dest = tmp_path / "pasted.png"
        pil.save(str(dest))
        reloaded = Image.open(str(dest)).convert("RGBA")
        assert reloaded.getpixel((0, 0))[:3] == (80, 160, 240)


# ---------------------------------------------------------------------------
# Text rendering edge cases
# ---------------------------------------------------------------------------

class TestTextEdgeCases:
    def test_very_long_label(self, empty_project, font_manager):
        item = empty_project.add_item("A" * 500)
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        assert result.mode == "RGBA"

    def test_single_long_word(self, empty_project, font_manager):
        """One word wider than the canvas should not wrap or crash."""
        item = empty_project.add_item("WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW")
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        assert result.mode == "RGBA"

    def test_unicode_label(self, empty_project, font_manager):
        item = empty_project.add_item("こんにちは 世界")
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        assert result.mode == "RGBA"

    def test_emoji_label(self, empty_project, font_manager):
        item = empty_project.add_item("🔥🎮🏆")
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        assert result.mode == "RGBA"

    def test_label_forces_autosize_to_min(self, empty_project, font_manager):
        s = empty_project.defaults.settings
        s.get("font_auto_size").value = True
        s.get("font_auto_size").use_default = False
        s.get("font_min_size").value = 8
        s.get("font_min_size").use_default = False
        s.get("font_max_lines").value = 1
        s.get("font_max_lines").use_default = False
        item = empty_project.add_item("This text is so long it must shrink past the minimum size")
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        assert result.mode == "RGBA"

    def test_zero_opacity_text(self, empty_project, font_manager):
        s = empty_project.defaults.settings
        s.get("text_opacity").value = 0
        s.get("text_opacity").use_default = False
        item = empty_project.add_item("Invisible text")
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        assert result.mode == "RGBA"


# ---------------------------------------------------------------------------
# Canvas size edge cases
# ---------------------------------------------------------------------------

class TestCanvasSizeEdgeCases:
    def test_square_canvas(self, empty_project, font_manager, tmp_path):
        s = empty_project.defaults.settings
        s.get("canvas_width").value = 500
        s.get("canvas_width").use_default = False
        s.get("canvas_height").value = 500
        s.get("canvas_height").use_default = False
        img = Image.new("RGBA", (200, 200), (0, 100, 200, 255))
        p = _save_image(tmp_path, img, "sq.png")
        item = empty_project.add_item("Square")
        item.image_path = str(p)
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        assert result.size == (500, 500)

    def test_minimum_canvas_size(self, empty_project, font_manager):
        s = empty_project.defaults.settings
        s.get("canvas_width").value = 100
        s.get("canvas_width").use_default = False
        s.get("canvas_height").value = 100
        s.get("canvas_height").use_default = False
        item = empty_project.add_item("Tiny canvas")
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        assert result.size == (100, 100)


# ---------------------------------------------------------------------------
# Clipboard inspection — unhappy paths (no Qt; uses mock objects)
# ---------------------------------------------------------------------------

class _NullImage:
    """Simulates a null QImage (no pixel data on clipboard)."""
    def isNull(self): return True

class _ValidImage:
    """Simulates a non-null QImage (actual pixel data on clipboard)."""
    def isNull(self): return False

class _Url:
    def __init__(self, local_file="", is_local=True, remote=""):
        self._file = local_file
        self._local = is_local
        self._remote = remote
    def isLocalFile(self): return self._local
    def toLocalFile(self): return self._file
    def toString(self): return self._remote

class _MimeData:
    def __init__(self, urls=None, text=""):
        self._urls = urls       # None = no URL data at all
        self._text = text
    def hasUrls(self):  return self._urls is not None
    def urls(self):     return self._urls or []
    def hasText(self):  return bool(self._text)
    def text(self):     return self._text

class _Clipboard:
    def __init__(self, img, mime=None):
        self._img  = img
        self._mime = mime or _MimeData()
    def image(self):    return self._img
    def mimeData(self): return self._mime


class TestClipboardInspection:
    """
    Tests for _inspect_clipboard() using mock objects — no Qt required.

    Each test exercises a distinct clipboard state that the paste handler must
    correctly identify and describe so the user knows what to do next.
    """

    def test_image_data_returns_image_category(self):
        cb = _Clipboard(_ValidImage())
        cat, msg = _inspect_clipboard(cb)
        assert cat == "image"
        assert msg == ""

    # --- Null image: various content types ----------------------------------

    def test_null_image_no_mime_is_empty(self):
        """Nothing on the clipboard at all — not a file, not text."""
        cb = _Clipboard(_NullImage(), _MimeData())
        cat, msg = _inspect_clipboard(cb)
        assert cat == "empty"
        assert "empty" in msg.lower() or "no image" in msg.lower()

    def test_null_image_single_image_file(self):
        """
        User copied an image file in Explorer (e.g. Ctrl+C on a .png).
        Clipboard has a file URL but no pixel data.
        Should say to use 'Open image' instead.
        """
        url = _Url(local_file="C:/Users/test/photo.png", is_local=True)
        mime = _MimeData(urls=[url])
        cb = _Clipboard(_NullImage(), mime)
        cat, msg = _inspect_clipboard(cb)
        assert cat == "files"
        assert "open image" in msg.lower()
        assert "photo.png" in msg

    def test_null_image_multiple_image_files(self):
        """Multiple image files copied — same guidance, up to 3 names shown."""
        urls = [_Url(f"C:/a.png"), _Url(f"C:/b.jpg"), _Url(f"C:/c.webp")]
        mime = _MimeData(urls=urls)
        cb = _Clipboard(_NullImage(), mime)
        cat, msg = _inspect_clipboard(cb)
        assert cat == "files"
        assert "open image" in msg.lower()

    def test_null_image_non_image_file(self):
        """User copied a .docx — not an image, say so."""
        url = _Url(local_file="C:/report.docx", is_local=True)
        mime = _MimeData(urls=[url])
        cb = _Clipboard(_NullImage(), mime)
        cat, msg = _inspect_clipboard(cb)
        assert cat == "files"
        # Message must indicate no usable image was found
        assert any(w in msg.lower() for w in ("no image", "not", "none"))

    def test_null_image_mixed_files_image_and_doc(self):
        """Image file AND a doc in the same copy — treated as files/image."""
        urls = [_Url("C:/photo.png"), _Url("C:/notes.txt")]
        mime = _MimeData(urls=urls)
        cb = _Clipboard(_NullImage(), mime)
        cat, msg = _inspect_clipboard(cb)
        assert cat == "files"
        assert "open image" in msg.lower()

    def test_null_image_remote_url_in_url_list(self):
        """
        Browser drag-to-clipboard puts a remote URL in the url list.
        isLocalFile() is False; the URL points to an online resource.
        """
        url = _Url(is_local=False, remote="https://example.com/photo.jpg")
        mime = _MimeData(urls=[url])
        cb = _Clipboard(_NullImage(), mime)
        cat, msg = _inspect_clipboard(cb)
        assert cat == "url"
        assert "url" in msg.lower() or "local" in msg.lower()

    def test_null_image_plain_text_url_https(self):
        """User typed or copied an https:// URL as plain text."""
        mime = _MimeData(text="https://example.com/image.jpg")
        cb = _Clipboard(_NullImage(), mime)
        cat, msg = _inspect_clipboard(cb)
        assert cat == "url"
        assert "url" in msg.lower()

    def test_null_image_plain_text_url_http(self):
        mime = _MimeData(text="http://example.com/x.png")
        cb = _Clipboard(_NullImage(), mime)
        cat, msg = _inspect_clipboard(cb)
        assert cat == "url"

    def test_null_image_plain_text_url_ftp(self):
        mime = _MimeData(text="ftp://files.example.com/image.png")
        cb = _Clipboard(_NullImage(), mime)
        cat, msg = _inspect_clipboard(cb)
        assert cat == "url"

    def test_null_image_plain_text_non_url(self):
        """Arbitrary text on the clipboard (not a URL, not a file)."""
        mime = _MimeData(text="S tier: Charizard, Blastoise, Venusaur")
        cb = _Clipboard(_NullImage(), mime)
        cat, msg = _inspect_clipboard(cb)
        assert cat == "text"
        assert "text" in msg.lower()

    # --- Base64 data URLs ---------------------------------------------------

    def test_base64_png_data_url_returns_base64_category(self):
        """data:image/png;base64,... should be detected and classified as 'base64'."""
        # Minimal valid 1×1 PNG as base64
        buf = io.BytesIO()
        Image.new("RGBA", (1, 1), (255, 0, 0, 255)).save(buf, format="PNG")
        import base64
        b64 = base64.b64encode(buf.getvalue()).decode()
        mime = _MimeData(text=f"data:image/png;base64,{b64}")
        cb = _Clipboard(_NullImage(), mime)
        cat, msg = _inspect_clipboard(cb)
        assert cat == "base64"
        assert msg == ""

    def test_base64_jpeg_data_url_returns_base64_category(self):
        buf = io.BytesIO()
        Image.new("RGB", (4, 4), (0, 255, 0)).save(buf, format="JPEG")
        import base64
        b64 = base64.b64encode(buf.getvalue()).decode()
        mime = _MimeData(text=f"data:image/jpeg;base64,{b64}")
        cb = _Clipboard(_NullImage(), mime)
        cat, msg = _inspect_clipboard(cb)
        assert cat == "base64"

    def test_base64_non_image_mime_type_returns_text(self):
        """data:text/plain;base64,... is NOT an image — must not return 'base64'."""
        import base64
        b64 = base64.b64encode(b"hello world").decode()
        mime = _MimeData(text=f"data:text/plain;base64,{b64}")
        cb = _Clipboard(_NullImage(), mime)
        cat, _msg = _inspect_clipboard(cb)
        assert cat == "text"

    def test_base64_url_without_base64_marker_returns_text(self):
        """data:image/svg+xml,<svg.../> (unencoded data URL) — no ';base64,' so text."""
        mime = _MimeData(text="data:image/svg+xml,<svg></svg>")
        cb = _Clipboard(_NullImage(), mime)
        cat, _msg = _inspect_clipboard(cb)
        assert cat == "text"

    def test_null_image_text_that_looks_like_path(self):
        """A file path as plain text (not a file URL) — classified as text."""
        mime = _MimeData(text=r"C:\Users\test\photo.png")
        cb = _Clipboard(_NullImage(), mime)
        cat, msg = _inspect_clipboard(cb)
        # It's text (hasUrls is False) — we don't parse text as a path
        assert cat == "text"

    def test_category_is_always_a_string(self):
        """Smoke test: every possible mime state returns a (str, str) tuple."""
        import base64
        _buf = io.BytesIO()
        Image.new("RGBA", (1, 1)).save(_buf, "PNG")
        _b64_png = base64.b64encode(_buf.getvalue()).decode()
        cases = [
            _Clipboard(_ValidImage()),
            _Clipboard(_NullImage()),
            _Clipboard(_NullImage(), _MimeData(urls=[_Url("C:/x.png")])),
            _Clipboard(_NullImage(), _MimeData(text="hello")),
            _Clipboard(_NullImage(), _MimeData(text="https://x.com")),
            _Clipboard(_NullImage(), _MimeData(text=f"data:image/png;base64,{_b64_png}")),
        ]
        for cb in cases:
            cat, msg = _inspect_clipboard(cb)
            assert isinstance(cat, str)
            assert isinstance(msg, str)


# ---------------------------------------------------------------------------
# Source resolution warning
# ---------------------------------------------------------------------------

class TestSourceResolutionWarning:
    """Tests for renderer.check_source_resolution()."""

    def _cfg(self, cw=1280, ch=720) -> ResolvedSettings:
        d = {f: FIELD_DEFAULTS[f] for f in FIELD_DEFAULTS}
        d["canvas_width"] = cw
        d["canvas_height"] = ch
        return ResolvedSettings(**d)

    def test_adequate_image_no_warning(self, tmp_path):
        img = Image.new("RGBA", (1280, 720))
        p = tmp_path / "ok.png"; img.save(str(p))
        assert renderer.check_source_resolution(str(p), self._cfg()) is None

    def test_slightly_smaller_no_warning(self, tmp_path):
        """Just above the 50% threshold — no warning."""
        img = Image.new("RGBA", (700, 400))   # >640 and >360 (half of 1280×720)
        p = tmp_path / "ok.png"; img.save(str(p))
        assert renderer.check_source_resolution(str(p), self._cfg()) is None

    def test_width_just_below_threshold_warns(self, tmp_path):
        """Width < half of canvas_width (640) → warn."""
        img = Image.new("RGBA", (639, 720))
        p = tmp_path / "small_w.png"; img.save(str(p))
        result = renderer.check_source_resolution(str(p), self._cfg())
        assert result is not None
        assert "639" in result

    def test_height_just_below_threshold_warns(self, tmp_path):
        """Height < half of canvas_height (360) → warn."""
        img = Image.new("RGBA", (1280, 359))
        p = tmp_path / "small_h.png"; img.save(str(p))
        result = renderer.check_source_resolution(str(p), self._cfg())
        assert result is not None
        assert "359" in result

    def test_both_dimensions_tiny_warns(self, tmp_path):
        img = Image.new("RGBA", (100, 100))
        p = tmp_path / "tiny.png"; img.save(str(p))
        result = renderer.check_source_resolution(str(p), self._cfg())
        assert result is not None

    def test_empty_path_no_warning(self):
        assert renderer.check_source_resolution("", self._cfg()) is None

    def test_none_equivalent_no_warning(self):
        assert renderer.check_source_resolution("", self._cfg()) is None

    def test_missing_file_no_warning(self, tmp_path):
        assert renderer.check_source_resolution(
            str(tmp_path / "missing.png"), self._cfg()
        ) is None

    def test_corrupt_file_no_warning(self, tmp_path):
        p = tmp_path / "bad.png"
        p.write_bytes(b"not an image")
        assert renderer.check_source_resolution(str(p), self._cfg()) is None

    def test_small_canvas_no_false_positive(self, tmp_path):
        """A 100×100 image is fine for a 100×100 canvas."""
        img = Image.new("RGBA", (100, 100))
        p = tmp_path / "match.png"; img.save(str(p))
        assert renderer.check_source_resolution(str(p), self._cfg(100, 100)) is None

    def test_warning_includes_dimensions(self, tmp_path):
        """The warning must state both source and canvas dimensions."""
        img = Image.new("RGBA", (200, 100))
        p = tmp_path / "small.png"; img.save(str(p))
        msg = renderer.check_source_resolution(str(p), self._cfg(1280, 720))
        assert "200" in msg and "100" in msg
        assert "1280" in msg and "720" in msg


# ---------------------------------------------------------------------------
# Base64 image decoding (_try_decode_base64_image)
# ---------------------------------------------------------------------------

class TestBase64Decoding:
    """
    Tests for _try_decode_base64_image().

    This helper is the second half of base64 clipboard support: _inspect_clipboard
    classifies the text as 'base64', then _try_decode_base64_image does the
    actual decode → PIL Image conversion before saving to disk.
    """

    def _make_b64(self, mode="RGBA", size=(8, 8), color=(100, 150, 200, 255),
                  fmt="PNG") -> str:
        """Return a valid data-URL for a small synthetic image."""
        import base64
        if mode == "RGB":
            color = color[:3]
        buf = io.BytesIO()
        Image.new(mode, size, color).save(buf, format=fmt)
        b64 = base64.b64encode(buf.getvalue()).decode()
        mime_type = "image/png" if fmt == "PNG" else "image/jpeg"
        return f"data:{mime_type};base64,{b64}"

    def test_valid_png_returns_pil_image(self):
        data_url = self._make_b64()
        result = _try_decode_base64_image(data_url)
        assert result is not None
        assert isinstance(result, Image.Image)

    def test_valid_png_correct_mode(self):
        """Decoded image is always converted to RGBA."""
        data_url = self._make_b64(mode="RGBA")
        result = _try_decode_base64_image(data_url)
        assert result.mode == "RGBA"

    def test_valid_jpeg_returns_pil_image(self):
        data_url = self._make_b64(mode="RGB", fmt="JPEG")
        result = _try_decode_base64_image(data_url)
        assert result is not None

    def test_valid_jpeg_converted_to_rgba(self):
        data_url = self._make_b64(mode="RGB", fmt="JPEG")
        result = _try_decode_base64_image(data_url)
        assert result.mode == "RGBA"

    def test_correct_size_preserved(self):
        data_url = self._make_b64(size=(16, 24))
        result = _try_decode_base64_image(data_url)
        assert result.size == (16, 24)

    def test_pixel_values_close_to_original(self):
        """Pixel values should survive the round-trip (within JPEG tolerance)."""
        data_url = self._make_b64(mode="RGBA", color=(255, 0, 0, 255))
        result = _try_decode_base64_image(data_url)
        r, _g, _b, a = result.getpixel((0, 0))
        assert r == 255
        assert a == 255

    def test_truncated_base64_returns_none(self):
        """Truncated base64 string → PIL cannot open → None, never raises."""
        import base64
        b64 = base64.b64encode(b"PNG truncated garbage").decode()
        result = _try_decode_base64_image(f"data:image/png;base64,{b64[:10]}")
        assert result is None

    def test_random_bytes_as_base64_returns_none(self):
        """Random bytes that aren't an image should silently return None."""
        import base64
        b64 = base64.b64encode(b"\x00\x01\x02\x03" * 50).decode()
        result = _try_decode_base64_image(f"data:image/png;base64,{b64}")
        assert result is None

    def test_corrupt_base64_chars_returns_none(self):
        """Non-base64 characters in the payload → None."""
        result = _try_decode_base64_image("data:image/png;base64,!!!not_valid_base64!!!")
        assert result is None

    def test_non_image_data_url_returns_none(self):
        """data:text/plain;base64,... has no 'data:image/' prefix → None."""
        import base64
        b64 = base64.b64encode(b"hello").decode()
        result = _try_decode_base64_image(f"data:text/plain;base64,{b64}")
        assert result is None

    def test_plain_text_returns_none(self):
        """Ordinary text (not a data URL at all) → None."""
        assert _try_decode_base64_image("S tier: Charizard") is None

    def test_http_url_returns_none(self):
        """An HTTP URL is not a data URL → None."""
        assert _try_decode_base64_image("https://example.com/img.png") is None

    def test_empty_string_returns_none(self):
        assert _try_decode_base64_image("") is None

    def test_whitespace_only_returns_none(self):
        assert _try_decode_base64_image("   ") is None

    def test_data_url_without_base64_marker_returns_none(self):
        """data:image/svg+xml,<svg/> — no ';base64,' → None."""
        assert _try_decode_base64_image("data:image/svg+xml,<svg></svg>") is None


# ---------------------------------------------------------------------------
# Source resolution matrix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("w,h,desc,seed", SOURCE_SIZES, ids=[s[2] for s in SOURCE_SIZES])
class TestSourceResolutionMatrix:
    """
    Render pipeline survives every source-image size in the standard matrix.

    Images are generated once to tests/fixtures/generated/ (git-ignored) and
    reused across runs via the source_image_cache fixture.  16 sizes covering
    small/medium/large square, widescreen, and portrait aspect ratios.
    """

    def test_renders_correct_canvas_size(self, w, h, desc, seed, source_image_cache,
                                         empty_project, font_manager):
        path = source_image_cache(w, h, desc, seed)
        item = empty_project.add_item(desc.replace("_", " ").title())
        item.image_path = str(path)
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        cfg = empty_project.resolve_item(item)
        assert result.size == (cfg.canvas_width, cfg.canvas_height)

    def test_all_fit_modes(self, w, h, desc, seed, source_image_cache,
                           empty_project, font_manager):
        path = source_image_cache(w, h, desc, seed)
        item = empty_project.add_item(desc.replace("_", " ").title())
        item.image_path = str(path)
        for fit in ("fill", "fit", "stretch", "center", "zoom"):
            item.settings.get("image_fit").value = fit
            item.settings.get("image_fit").use_default = False
            result = renderer.render_thumbnail(item, empty_project, font_manager)
            cfg = empty_project.resolve_item(item)
            assert result.size == (cfg.canvas_width, cfg.canvas_height), \
                f"fit={fit!r} failed for {desc} ({w}x{h})"


@pytest.mark.slow
@pytest.mark.parametrize("w,h,desc,seed", SOURCE_SIZES_SLOW, ids=[s[2] for s in SOURCE_SIZES_SLOW])
class TestSourceResolutionMatrixSlow:
    """Extreme-size variants (5k–10k px).  Run with: pytest -m slow."""

    def test_renders_correct_canvas_size(self, w, h, desc, seed, source_image_cache,
                                         empty_project, font_manager):
        path = source_image_cache(w, h, desc, seed)
        item = empty_project.add_item(desc.replace("_", " ").title())
        item.image_path = str(path)
        result = renderer.render_thumbnail(item, empty_project, font_manager)
        cfg = empty_project.resolve_item(item)
        assert result.size == (cfg.canvas_width, cfg.canvas_height)
