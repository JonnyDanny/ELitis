"""Tests for elitis.core.data_io."""
import pytest
import json
from pathlib import Path

from elitis.core import data_io
from elitis.core.models import Project, ThumbnailItem, FIELD_DEFAULTS


# ---------------------------------------------------------------------------
# save_project / load_project round-trip
# ---------------------------------------------------------------------------

class TestSaveLoad:
    def test_roundtrip_basic(self, tmp_path):
        p = Project.new("myproject", "Egest/myproject")
        p.add_item("Alpha")
        p.add_item("Beta")
        dest = tmp_path / "myproject.json"
        data_io.save_project(p, dest)

        loaded = data_io.load_project(dest)
        assert loaded.name == "myproject"
        assert len(loaded.content_items) == 2
        assert loaded.content_items[0].label == "Alpha"
        assert loaded.content_items[1].label == "Beta"

    def test_roundtrip_preserves_image_path(self, tmp_path):
        p = Project.new("x", "out")
        item = p.add_item("X")
        item.image_path = "/some/image.png"
        dest = tmp_path / "x.json"
        data_io.save_project(p, dest)

        loaded = data_io.load_project(dest)
        assert loaded.content_items[0].image_path == "/some/image.png"

    def test_roundtrip_preserves_sf_override(self, tmp_path):
        p = Project.new("x", "out")
        item = p.add_item("X")
        item.settings.set_value("font_size", 44, use_default=False)
        dest = tmp_path / "x.json"
        data_io.save_project(p, dest)

        loaded = data_io.load_project(dest)
        sf = loaded.content_items[0].settings.get("font_size")
        assert sf.value == 44
        assert sf.use_default is False

    def test_roundtrip_preserves_sf_use_default(self, tmp_path):
        p = Project.new("x", "out")
        item = p.add_item("X")
        item.settings.get("font_size").use_default = True
        dest = tmp_path / "x.json"
        data_io.save_project(p, dest)

        loaded = data_io.load_project(dest)
        assert loaded.content_items[0].settings.get("font_size").use_default is True

    def test_roundtrip_color_tuple(self, tmp_path):
        p = Project.new("x", "out")
        p.defaults.settings.get("text_color").value = (200, 100, 50)
        p.defaults.settings.get("text_color").use_default = False
        dest = tmp_path / "x.json"
        data_io.save_project(p, dest)

        loaded = data_io.load_project(dest)
        assert loaded.defaults.settings.get("text_color").value == (200, 100, 50)

    def test_roundtrip_unicode_label(self, tmp_path):
        p = Project.new("x", "out")
        p.add_item("こんにちは 世界 🌍")
        dest = tmp_path / "x.json"
        data_io.save_project(p, dest)

        loaded = data_io.load_project(dest)
        assert loaded.content_items[0].label == "こんにちは 世界 🌍"

    def test_creates_parent_dirs(self, tmp_path):
        p = Project.new("x", "out")
        dest = tmp_path / "deep" / "nested" / "x.json"
        data_io.save_project(p, dest)
        assert dest.exists()

    def test_load_missing_defaults_inserts_one(self, tmp_path):
        """A file with no is_default item at index 0 gets a fresh defaults item prepended."""
        raw = {
            "version": "0.2.0.pre",
            "name": "broken",
            "output_dir": "out",
            "created_at": "",
            "modified_at": "",
            "items": [
                {"id": "abc", "label": "Only item", "image_path": None,
                 "is_default": False, "settings": {}},
            ],
        }
        dest = tmp_path / "broken.json"
        dest.write_text(json.dumps(raw), encoding="utf-8")

        loaded = data_io.load_project(dest)
        assert loaded.items[0].is_default
        assert loaded.content_items[0].label == "Only item"

    def test_backward_compat_use_phantom_key(self, tmp_path):
        """Pre-0.2 files use 'use_phantom' instead of 'use_default'."""
        raw = {
            "version": "0.1",
            "name": "old",
            "output_dir": "out",
            "created_at": "",
            "modified_at": "",
            "items": [
                {"id": "__defaults__", "label": "", "image_path": None,
                 "is_default": True,
                 "settings": {"font_size": {"value": 50, "use_phantom": False}}},
            ],
        }
        dest = tmp_path / "old.json"
        dest.write_text(json.dumps(raw), encoding="utf-8")

        loaded = data_io.load_project(dest)
        sf = loaded.defaults.settings.get("font_size")
        assert sf.value == 50
        assert sf.use_default is False

    def test_backward_compat_is_phantom_key(self, tmp_path):
        raw = {
            "version": "0.1",
            "name": "old",
            "output_dir": "out",
            "created_at": "",
            "modified_at": "",
            "items": [
                {"id": "__defaults__", "label": "", "image_path": None,
                 "is_phantom": True, "settings": {}},
            ],
        }
        dest = tmp_path / "old.json"
        dest.write_text(json.dumps(raw), encoding="utf-8")
        loaded = data_io.load_project(dest)
        assert loaded.defaults.is_default is True


# ---------------------------------------------------------------------------
# save_version
# ---------------------------------------------------------------------------

class TestSaveVersion:
    def test_returns_version_string(self, tmp_path):
        p = Project.new("x", "out")
        dest = tmp_path / "x.json"
        data_io.save_project(p, dest)
        assert data_io.save_version(dest) == data_io.SAVE_VERSION

    def test_returns_01_for_unversioned(self, tmp_path):
        dest = tmp_path / "old.json"
        dest.write_text('{"name": "x"}', encoding="utf-8")
        assert data_io.save_version(dest) == "0.1"

    def test_returns_unknown_for_corrupt(self, tmp_path):
        dest = tmp_path / "bad.json"
        dest.write_bytes(b"\xff\xfe bad data")
        assert data_io.save_version(dest) == "unknown"

    def test_returns_unknown_for_missing(self, tmp_path):
        assert data_io.save_version(tmp_path / "missing.json") == "unknown"


# ---------------------------------------------------------------------------
# import_labels — plain text
# ---------------------------------------------------------------------------

class TestImportLabelsTxt:
    def _write(self, tmp_path, content: str, name="labels.txt") -> Path:
        p = tmp_path / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_basic_one_per_line(self, tmp_path):
        f = self._write(tmp_path, "Alpha\nBeta\nGamma\n")
        assert data_io.import_labels(f) == ["Alpha", "Beta", "Gamma"]

    def test_strips_whitespace(self, tmp_path):
        f = self._write(tmp_path, "  Alpha  \n  Beta  ")
        assert data_io.import_labels(f) == ["Alpha", "Beta"]

    def test_skips_blank_lines(self, tmp_path):
        f = self._write(tmp_path, "Alpha\n\n\nBeta\n\n")
        assert data_io.import_labels(f) == ["Alpha", "Beta"]

    def test_empty_file(self, tmp_path):
        f = self._write(tmp_path, "")
        assert data_io.import_labels(f) == []

    def test_only_whitespace(self, tmp_path):
        f = self._write(tmp_path, "   \n  \t  \n")
        assert data_io.import_labels(f) == []

    def test_unicode_labels(self, tmp_path):
        f = self._write(tmp_path, "こんにちは\nمرحبا\nHello")
        labels = data_io.import_labels(f)
        assert labels == ["こんにちは", "مرحبا", "Hello"]

    def test_single_label_no_newline(self, tmp_path):
        f = self._write(tmp_path, "OnlyOne")
        assert data_io.import_labels(f) == ["OnlyOne"]


# ---------------------------------------------------------------------------
# import_labels — CSV
# ---------------------------------------------------------------------------

class TestImportLabelsCsv:
    def _write(self, tmp_path, content: str, name="data.csv") -> Path:
        p = tmp_path / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_basic_first_column(self, tmp_path):
        f = self._write(tmp_path, "Alpha,1\nBeta,2\nGamma,3\n")
        assert data_io.import_labels(f) == ["Alpha", "Beta", "Gamma"]

    def test_explicit_column_1(self, tmp_path):
        f = self._write(tmp_path, "ignore,Alpha\nignore,Beta\n")
        assert data_io.import_labels(f, column=1) == ["Alpha", "Beta"]

    def test_header_auto_detected_and_skipped(self, tmp_path):
        f = self._write(tmp_path, "title,score\nAlpha,10\nBeta,20\n")
        labels = data_io.import_labels(f)
        assert labels == ["Alpha", "Beta"]

    def test_header_false_includes_header_row(self, tmp_path):
        f = self._write(tmp_path, "title,score\nAlpha,10\n")
        labels = data_io.import_labels(f, has_header=False)
        assert "title" in labels

    def test_header_true_skips_first_row(self, tmp_path):
        f = self._write(tmp_path, "whatever,score\nAlpha,10\n")
        labels = data_io.import_labels(f, has_header=True)
        assert labels == ["Alpha"]

    def test_empty_csv(self, tmp_path):
        f = self._write(tmp_path, "")
        assert data_io.import_labels(f) == []

    def test_column_out_of_bounds_skipped(self, tmp_path):
        f = self._write(tmp_path, "Alpha\nBeta\n")
        assert data_io.import_labels(f, column=5) == []

    def test_skips_empty_cells(self, tmp_path):
        f = self._write(tmp_path, "Alpha\n\nBeta\n")
        labels = data_io.import_labels(f)
        assert "" not in labels
        assert "Alpha" in labels
        assert "Beta" in labels

    def test_tsv_extension(self, tmp_path):
        f = self._write(tmp_path, "Alpha\tignore\nBeta\tignore\n", name="data.tsv")
        assert data_io.import_labels(f) == ["Alpha", "Beta"]


# ---------------------------------------------------------------------------
# project_from_labels
# ---------------------------------------------------------------------------

class TestProjectFromLabels:
    def test_creates_project_with_labels(self, tmp_path):
        p, saved = data_io.project_from_labels(
            ["A", "B", "C"], "test", "Egest/test", tmp_path
        )
        assert [i.label for i in p.content_items] == ["A", "B", "C"]

    def test_saves_to_disk(self, tmp_path):
        _, saved = data_io.project_from_labels(
            ["X"], "myproj", "out", tmp_path
        )
        assert saved.exists()

    def test_avoids_clobber(self, tmp_path):
        # Save first copy
        _, p1 = data_io.project_from_labels(["A"], "same", "out", tmp_path)
        # Save second copy — must not overwrite first
        _, p2 = data_io.project_from_labels(["B"], "same", "out", tmp_path)
        assert p1 != p2
        assert p1.exists() and p2.exists()

    def test_empty_labels_creates_empty_project(self, tmp_path):
        p, _ = data_io.project_from_labels([], "empty", "out", tmp_path)
        assert p.content_items == []
