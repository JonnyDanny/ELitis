"""
Shared fixtures for ELItis tests.

All tests run against the pure-Python core (models, renderer, data_io, font_manager)
with no Qt dependency.  PySide6 is never imported here.
"""
import pytest
from pathlib import Path
from PIL import Image

from elitis.core.models import Project, ThumbnailItem
from elitis.core.font_manager import FontManager


@pytest.fixture
def empty_project() -> Project:
    """A fresh project with only the defaults item and no content items."""
    return Project.new("test", "Egest/test")


@pytest.fixture
def small_project(empty_project) -> Project:
    """A project with three content items, no images."""
    for label in ["Alpha", "Beta", "Gamma"]:
        empty_project.add_item(label)
    return empty_project


@pytest.fixture
def font_manager(tmp_path) -> FontManager:
    """FontManager pointed at an empty temp directory — always uses PIL's default font."""
    fonts_dir = tmp_path / "Fonts"
    fonts_dir.mkdir()
    return FontManager(fonts_dir)


@pytest.fixture
def font_manager_with_font(tmp_path) -> FontManager:
    """
    FontManager with the project's real Fredoka font available.

    Skips the test if the font file is not present (e.g. a fresh checkout that
    hasn't fetched assets yet).
    """
    fonts_root = Path(__file__).parent.parent / "Fonts"
    if not any(fonts_root.rglob("*.ttf")):
        pytest.skip("No .ttf fonts found in Fonts/ directory")
    return FontManager(fonts_root)


@pytest.fixture
def tiny_rgba_image() -> Image.Image:
    """16×16 solid red RGBA image."""
    img = Image.new("RGBA", (16, 16), (255, 0, 0, 255))
    return img


@pytest.fixture
def tiny_image_file(tmp_path, tiny_rgba_image) -> Path:
    """16×16 red PNG saved to a temp file."""
    p = tmp_path / "red.png"
    tiny_rgba_image.save(str(p))
    return p
