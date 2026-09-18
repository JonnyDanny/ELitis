"""Tests for elitis.core.models."""
import pytest
from elitis.core.models import (
    SF, FIELD_DEFAULTS, ItemSettings, ResolvedSettings, ThumbnailItem, Project,
    resolve,
)


# ---------------------------------------------------------------------------
# SF
# ---------------------------------------------------------------------------

class TestSF:
    def test_resolve_uses_default_when_flag_true(self):
        sf = SF(value=10, use_default=True)
        assert sf.resolve(99) == 99

    def test_resolve_uses_own_value_when_flag_false(self):
        sf = SF(value=10, use_default=False)
        assert sf.resolve(99) == 10

    def test_resolve_own_value_zero(self):
        sf = SF(value=0, use_default=False)
        assert sf.resolve(99) == 0

    def test_resolve_default_none(self):
        sf = SF(value="something", use_default=True)
        assert sf.resolve(None) is None

    def test_resolve_bool_false_own(self):
        sf = SF(value=False, use_default=False)
        assert sf.resolve(True) is False

    def test_resolve_tuple_color(self):
        sf = SF(value=(255, 0, 0), use_default=False)
        assert sf.resolve((0, 0, 0)) == (255, 0, 0)


# ---------------------------------------------------------------------------
# ItemSettings
# ---------------------------------------------------------------------------

class TestItemSettings:
    def test_all_fields_have_correct_defaults(self):
        s = ItemSettings()
        for name, default_val in FIELD_DEFAULTS.items():
            sf = s.get(name)
            assert sf.value == default_val, f"{name}: got {sf.value!r}, expected {default_val!r}"

    def test_all_fields_start_with_use_default_true(self):
        s = ItemSettings()
        for name in s.field_names():
            assert s.get(name).use_default is True, f"{name} should start with use_default=True"

    def test_set_value_updates_value(self):
        s = ItemSettings()
        s.set_value("font_size", 42)
        assert s.get("font_size").value == 42

    def test_set_value_updates_flag(self):
        s = ItemSettings()
        s.set_value("font_size", 42, use_default=False)
        assert s.get("font_size").use_default is False

    def test_set_value_none_flag_leaves_flag_unchanged(self):
        s = ItemSettings()
        s.get("font_size").use_default = False
        s.set_value("font_size", 42, use_default=None)
        assert s.get("font_size").use_default is False

    def test_field_names_includes_all_expected(self):
        names = ItemSettings().field_names()
        for key in FIELD_DEFAULTS:
            assert key in names

    def test_get_unknown_raises(self):
        with pytest.raises(AttributeError):
            ItemSettings().get("nonexistent_field")


# ---------------------------------------------------------------------------
# resolve()
# ---------------------------------------------------------------------------

class TestResolve:
    def test_use_default_true_picks_defaults_value(self):
        item = ItemSettings()
        item.get("font_size").use_default = True
        item.get("font_size").value = 10

        defaults = ItemSettings()
        defaults.get("font_size").use_default = False
        defaults.get("font_size").value = 80

        result = resolve(item, defaults)
        assert result.font_size == 80

    def test_use_default_false_picks_item_value(self):
        item = ItemSettings()
        item.get("font_size").use_default = False
        item.get("font_size").value = 42

        defaults = ItemSettings()
        defaults.get("font_size").value = 80

        result = resolve(item, defaults)
        assert result.font_size == 42

    def test_defaults_item_resolves_to_its_own_values(self):
        """The defaults item resolves against itself — all SFs must be False already."""
        defaults_item = ThumbnailItem.make_defaults()
        result = resolve(defaults_item.settings, defaults_item.settings)
        assert result.font_size == FIELD_DEFAULTS["font_size"]

    def test_all_fields_present_in_result(self):
        item = ItemSettings()
        defaults = ItemSettings()
        result = resolve(item, defaults)
        for key in FIELD_DEFAULTS:
            assert hasattr(result, key)


# ---------------------------------------------------------------------------
# ThumbnailItem
# ---------------------------------------------------------------------------

class TestThumbnailItem:
    def test_make_defaults_sets_all_use_default_false(self):
        d = ThumbnailItem.make_defaults()
        for name in d.settings.field_names():
            assert d.settings.get(name).use_default is False, \
                f"defaults item field '{name}' should have use_default=False"

    def test_make_defaults_is_default_flag(self):
        d = ThumbnailItem.make_defaults()
        assert d.is_default is True

    def test_new_item_all_use_default_true(self):
        item = ThumbnailItem.new_item("Test")
        for name in item.settings.field_names():
            assert item.settings.get(name).use_default is True

    def test_new_item_label(self):
        item = ThumbnailItem.new_item("Hello")
        assert item.label == "Hello"

    def test_new_item_explicit_id(self):
        item = ThumbnailItem.new_item("X", item_id="abc123")
        assert item.id == "abc123"

    def test_new_item_auto_id_unique(self):
        ids = {ThumbnailItem.new_item("x").id for _ in range(50)}
        assert len(ids) == 50

    def test_effective_image_own_path(self):
        defaults = ThumbnailItem.make_defaults()
        defaults.image_path = "/default.png"
        item = ThumbnailItem.new_item("x")
        item.image_path = "/own.png"
        assert item.effective_image(defaults) == "/own.png"

    def test_effective_image_falls_back_to_defaults(self):
        defaults = ThumbnailItem.make_defaults()
        defaults.image_path = "/default.png"
        item = ThumbnailItem.new_item("x")
        item.image_path = None
        assert item.effective_image(defaults) == "/default.png"

    def test_effective_image_both_none(self):
        defaults = ThumbnailItem.make_defaults()
        defaults.image_path = None
        item = ThumbnailItem.new_item("x")
        assert item.effective_image(defaults) is None


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------

class TestProject:
    def test_new_has_only_defaults_item(self):
        p = Project.new("test", "out")
        assert len(p.items) == 1
        assert p.items[0].is_default

    def test_content_items_excludes_defaults(self):
        p = Project.new("test", "out")
        p.add_item("A")
        assert len(p.content_items) == 1
        assert p.content_items[0].label == "A"

    def test_add_item_returns_item(self):
        p = Project.new("test", "out")
        item = p.add_item("Alpha")
        assert item.label == "Alpha"
        assert item in p.items

    def test_find_item_found(self):
        p = Project.new("test", "out")
        item = p.add_item("X")
        assert p.find_item(item.id) is item

    def test_find_item_not_found(self):
        p = Project.new("test", "out")
        assert p.find_item("nonexistent") is None

    def test_remove_item_removes_content(self):
        p = Project.new("test", "out")
        item = p.add_item("X")
        p.remove_item(item.id)
        assert p.find_item(item.id) is None

    def test_remove_item_cannot_remove_defaults(self):
        p = Project.new("test", "out")
        defaults_id = p.defaults.id
        p.remove_item(defaults_id)
        assert p.defaults.id == defaults_id

    def test_defaults_property(self):
        p = Project.new("test", "out")
        assert p.defaults is p.items[0]

    def test_touch_updates_modified_at(self):
        p = Project.new("test", "out")
        before = p.modified_at
        import time; time.sleep(0.01)
        p.touch()
        assert p.modified_at > before

    def test_resolve_item_defaults(self):
        p = Project.new("test", "out")
        result = p.resolve_item(p.defaults)
        assert isinstance(result, ResolvedSettings)
        assert result.font_size == FIELD_DEFAULTS["font_size"]

    def test_resolve_item_content_inherits_defaults(self):
        p = Project.new("test", "out")
        p.defaults.settings.get("font_size").value = 120
        item = p.add_item("X")
        result = p.resolve_item(item)
        assert result.font_size == 120

    def test_resolve_item_content_own_override(self):
        p = Project.new("test", "out")
        p.defaults.settings.get("font_size").value = 120
        item = p.add_item("X")
        item.settings.get("font_size").use_default = False
        item.settings.get("font_size").value = 64
        result = p.resolve_item(item)
        assert result.font_size == 64
