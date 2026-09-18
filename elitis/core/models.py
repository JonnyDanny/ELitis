"""
Data model for ELItis.

Every visual setting is wrapped in a SettingField (SF).  When ``use_default=True``
the rendering engine substitutes the *defaults item*'s value instead of this item's
own.  The defaults item (``items[0]``) always has ``use_default=False`` on every
field — it IS the source of defaults and has no parent to inherit from.

Inheritance chain (one level deep)
-----------------------------------
  defaults item  →  any content item with use_default=True on a given field
                 ↘  content item's own value when use_default=False

There is intentionally no multi-level inheritance; the defaults item's fields are
always absolute values.
"""
from __future__ import annotations
from dataclasses import dataclass, field, fields as dc_fields
from typing import Any, Optional
from datetime import datetime
import uuid


# ---------------------------------------------------------------------------
# ImageHash — stored integrity fingerprint for one image file
# ---------------------------------------------------------------------------

@dataclass
class ImageHash:
    """
    Multi-algorithm fingerprint of an image file at assignment time.

    On reload, sha256 is the primary integrity check.  Resolution (width,
    height) is stored as a fast pre-filter — a mismatch without hash change
    is impossible, but resolution-same + hash-fail almost always means a
    benign metadata rewrite rather than content change.

    blake3 is None when the blake3 package is not installed; the other two
    hashes are always present.
    """
    sha256: str
    crc32:  str
    blake3: Optional[str]
    width:  int
    height: int


# ---------------------------------------------------------------------------
# SettingField
# ---------------------------------------------------------------------------

@dataclass
class SF:
    """
    A single visual setting paired with an inheritance flag.

    ``use_default=True``  — at render time, the defaults item's value is used
                            instead of this field's own *value*.
    ``use_default=False`` — this field's own *value* is used directly.

    The *value* is always kept in sync even when ``use_default`` is True, so
    switching back from "use default" to "override" restores the last override
    without losing it.
    """
    value: Any
    use_default: bool = True

    def resolve(self, default_value: Any) -> Any:
        """Return *default_value* when inheriting, otherwise return own *value*."""
        return default_value if self.use_default else self.value


# ---------------------------------------------------------------------------
# Default values for every field — used when creating the defaults item
# ---------------------------------------------------------------------------

FIELD_DEFAULTS: dict[str, Any] = {
    # Canvas
    "canvas_width": 1280,
    "canvas_height": 720,
    # Image framing
    "image_fit": "fill",    # fill | fit | stretch | center | zoom
    "crop_x": 0.0,          # normalised 0-1, top-left corner of the crop rect
    "crop_y": 0.0,
    "crop_w": 1.0,          # normalised width of the crop rect (1.0 = full width)
    "crop_h": 1.0,
    # Text position
    "text_x": 0.5,          # normalised; anchor is horizontal center of text block
    "text_y": 0.82,         # normalised; anchor is vertical center of text block
    # Text appearance
    "text_color": (255, 255, 255),
    "text_opacity": 255,
    "text_transform": "none",   # none | upper | lower | title
    "text_align": "center",     # left | center | right
    # Font
    "font_name": "default",
    "font_size": 80,
    "font_auto_size": True,
    "font_min_size": 28,
    "font_max_lines": 2,
    # Outline
    "outline_enabled": True,
    "outline_color": (0, 0, 0),
    "outline_width": 4,
    # Shadow
    "shadow_enabled": False,
    "shadow_color": (0, 0, 0),
    "shadow_offset_x": 4,
    "shadow_offset_y": 4,
    "shadow_blur": 6,
    # Box overlay behind text
    "box_enabled": True,
    "box_color": (0, 0, 0),
    "box_opacity": 160,
    "box_height": 0.22,     # fraction of canvas height
    "box_padding": 20,
    "box_position": "bottom",   # bottom | top | full
}


# ---------------------------------------------------------------------------
# ItemSettings — one SF per visual property
# ---------------------------------------------------------------------------

def _sf(key: str) -> SF:
    """Create a new SF seeded with the field's default value and use_default=True."""
    return SF(value=FIELD_DEFAULTS[key], use_default=True)


@dataclass
class ItemSettings:
    """
    The complete set of visual settings for one thumbnail item.

    Every field is an SF so individual settings can independently inherit from the
    defaults item or carry their own override value.  New items start with
    ``use_default=True`` on all fields, meaning they visually match the defaults
    item until the user explicitly overrides something.
    """
    # Canvas
    canvas_width:    SF = field(default_factory=lambda: _sf("canvas_width"))
    canvas_height:   SF = field(default_factory=lambda: _sf("canvas_height"))
    # Image framing
    image_fit:       SF = field(default_factory=lambda: _sf("image_fit"))
    crop_x:          SF = field(default_factory=lambda: _sf("crop_x"))
    crop_y:          SF = field(default_factory=lambda: _sf("crop_y"))
    crop_w:          SF = field(default_factory=lambda: _sf("crop_w"))
    crop_h:          SF = field(default_factory=lambda: _sf("crop_h"))
    # Text position
    text_x:          SF = field(default_factory=lambda: _sf("text_x"))
    text_y:          SF = field(default_factory=lambda: _sf("text_y"))
    # Text appearance
    text_color:      SF = field(default_factory=lambda: _sf("text_color"))
    text_opacity:    SF = field(default_factory=lambda: _sf("text_opacity"))
    text_transform:  SF = field(default_factory=lambda: _sf("text_transform"))
    text_align:      SF = field(default_factory=lambda: _sf("text_align"))
    # Font
    font_name:       SF = field(default_factory=lambda: _sf("font_name"))
    font_size:       SF = field(default_factory=lambda: _sf("font_size"))
    font_auto_size:  SF = field(default_factory=lambda: _sf("font_auto_size"))
    font_min_size:   SF = field(default_factory=lambda: _sf("font_min_size"))
    font_max_lines:  SF = field(default_factory=lambda: _sf("font_max_lines"))
    # Outline
    outline_enabled: SF = field(default_factory=lambda: _sf("outline_enabled"))
    outline_color:   SF = field(default_factory=lambda: _sf("outline_color"))
    outline_width:   SF = field(default_factory=lambda: _sf("outline_width"))
    # Shadow
    shadow_enabled:  SF = field(default_factory=lambda: _sf("shadow_enabled"))
    shadow_color:    SF = field(default_factory=lambda: _sf("shadow_color"))
    shadow_offset_x: SF = field(default_factory=lambda: _sf("shadow_offset_x"))
    shadow_offset_y: SF = field(default_factory=lambda: _sf("shadow_offset_y"))
    shadow_blur:     SF = field(default_factory=lambda: _sf("shadow_blur"))
    # Box overlay
    box_enabled:     SF = field(default_factory=lambda: _sf("box_enabled"))
    box_color:       SF = field(default_factory=lambda: _sf("box_color"))
    box_opacity:     SF = field(default_factory=lambda: _sf("box_opacity"))
    box_height:      SF = field(default_factory=lambda: _sf("box_height"))
    box_padding:     SF = field(default_factory=lambda: _sf("box_padding"))
    box_position:    SF = field(default_factory=lambda: _sf("box_position"))

    def get(self, name: str) -> SF:
        """Return the SF for *name*.  Raises AttributeError for unknown names."""
        return getattr(self, name)

    def set_value(self, name: str, value: Any, use_default: bool | None = None):
        """
        Write a new value (and optionally a new use_default flag) into the named SF.

        Passing ``use_default=None`` leaves the flag unchanged, which is useful when
        you only want to update the stored value without changing inheritance status.
        """
        sf: SF = getattr(self, name)
        sf.value = value
        if use_default is not None:
            sf.use_default = use_default

    def field_names(self) -> list[str]:
        """Return every field name in declaration order."""
        return [f.name for f in dc_fields(self)]


# ---------------------------------------------------------------------------
# ResolvedSettings — flat dict, no SF wrappers; result of defaults resolution
# ---------------------------------------------------------------------------

@dataclass
class ResolvedSettings:
    """
    All visual settings for one item after inheritance has been resolved.

    Renderer functions consume this instead of ItemSettings so they never need to
    know whether a value came from the item itself or the defaults item.
    """
    canvas_width: int
    canvas_height: int
    image_fit: str
    crop_x: float
    crop_y: float
    crop_w: float
    crop_h: float
    text_x: float
    text_y: float
    text_color: tuple
    text_opacity: int
    text_transform: str
    text_align: str
    font_name: str
    font_size: int
    font_auto_size: bool
    font_min_size: int
    font_max_lines: int
    outline_enabled: bool
    outline_color: tuple
    outline_width: int
    shadow_enabled: bool
    shadow_color: tuple
    shadow_offset_x: int
    shadow_offset_y: int
    shadow_blur: int
    box_enabled: bool
    box_color: tuple
    box_opacity: int
    box_height: float
    box_padding: int
    box_position: str


def resolve(item: ItemSettings, defaults: ItemSettings) -> ResolvedSettings:
    """
    Build a ResolvedSettings by resolving each SF against the defaults.

    For every field: if ``item.field.use_default`` is True the defaults item's *value*
    is used; otherwise the item's own *value* is used.  The defaults item resolves
    against itself, so all its fields always produce their own values.
    """
    kwargs = {}
    for f in dc_fields(item):
        item_sf: SF    = getattr(item, f.name)
        default_sf: SF = getattr(defaults, f.name)
        kwargs[f.name] = default_sf.value if item_sf.use_default else item_sf.value
    return ResolvedSettings(**kwargs)


# ---------------------------------------------------------------------------
# ThumbnailItem
# ---------------------------------------------------------------------------

@dataclass
class ThumbnailItem:
    """
    One entry in the project: an id, a display label, an optional image path, and
    its per-field settings.

    The defaults item (``is_default=True``) lives at ``project.items[0]`` and acts
    as the template.  Content items (``is_default=False``) inherit any field that has
    ``use_default=True`` from the defaults item.
    """
    id: str
    label: str
    image_path: Optional[str]
    settings: ItemSettings
    is_default: bool = False
    image_hash: Optional[ImageHash] = None
    origin: Optional[str] = None   # CSV filename or project name this item came from

    @classmethod
    def make_defaults(cls) -> ThumbnailItem:
        """
        Create the project's defaults item with ``use_default=False`` on every field.

        The defaults item has no parent to inherit from, so every field must be an
        absolute value — setting ``use_default=False`` on all of them enforces this.
        """
        s = ItemSettings()
        for f in dc_fields(s):
            getattr(s, f.name).use_default = False
        return cls(id="__defaults__", label="", image_path=None, settings=s, is_default=True)

    @classmethod
    def new_item(cls, label: str, item_id: str | None = None) -> ThumbnailItem:
        """
        Create a new content item that inherits everything from the defaults item.

        All SFs start with ``use_default=True`` (the ItemSettings default), so the
        item is visually identical to the defaults item until overrides are applied.
        """
        return cls(
            id=item_id or uuid.uuid4().hex[:8],
            label=label,
            image_path=None,
            settings=ItemSettings(),
        )

    def effective_image(self, defaults: ThumbnailItem) -> Optional[str]:
        """
        Return the image path to render for this item.

        Falls back to the defaults item's path when this item has none, which lets a
        project share one background image across all items without copying the path
        to every item.  Returns None when neither has a path.
        """
        return self.image_path or defaults.image_path


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------

@dataclass
class Project:
    """
    A collection of thumbnail items with shared output settings.

    Invariant: ``items[0]`` is always the defaults item (``is_default=True``).
    ``content_items`` (``items[1:]``) are the renderable thumbnails.
    """
    name: str
    items: list          # list[ThumbnailItem]; items[0] is always the defaults item
    output_dir: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    modified_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @classmethod
    def new(cls, name: str, output_dir: str) -> Project:
        """Create a new empty project with only the defaults item."""
        return cls(name=name, items=[ThumbnailItem.make_defaults()], output_dir=output_dir)

    @property
    def defaults(self) -> ThumbnailItem:
        """The defaults item at index 0."""
        return self.items[0]

    @property
    def content_items(self) -> list:
        """All items except the defaults item — these are the renderable thumbnails."""
        return self.items[1:]

    def add_item(self, label: str) -> ThumbnailItem:
        """Append a new content item and return it."""
        item = ThumbnailItem.new_item(label)
        self.items.append(item)
        return item

    def find_item(self, item_id: str) -> "ThumbnailItem | None":
        """Return the item with the given id, or None if not found."""
        return next((i for i in self.items if i.id == item_id), None)

    def remove_item(self, item_id: str):
        """
        Remove the item with the given id.

        The defaults item is protected — passing its id is a no-op because the filter
        keeps any item that is either a different id or is the defaults item.
        """
        self.items = [i for i in self.items if i.id != item_id or i.is_default]

    def touch(self):
        """Update ``modified_at`` to the current time (call before saving)."""
        self.modified_at = datetime.now().isoformat()

    def resolve_item(self, item: ThumbnailItem) -> ResolvedSettings:
        """
        Resolve *item*'s settings against the project defaults.

        When *item* is the defaults item itself it resolves against its own settings,
        which is a no-op because all its SFs have ``use_default=False``.
        """
        if item.is_default:
            return resolve(item.settings, item.settings)
        return resolve(item.settings, self.defaults.settings)
