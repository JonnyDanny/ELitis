"""
Data model for ELItis.

Every visual setting is wrapped in a SettingField (SF). When use_phantom=True the
rendering engine substitutes the phantom item's value instead of this item's own.
The phantom item (items[0]) always has use_phantom=False on every field — it IS the
source of defaults.
"""
from __future__ import annotations
from dataclasses import dataclass, field, fields as dc_fields
from typing import Any, Optional
from datetime import datetime
import uuid


# ---------------------------------------------------------------------------
# SettingField
# ---------------------------------------------------------------------------

@dataclass
class SF:
    """A setting value with an optional "use phantom" flag."""
    value: Any
    use_phantom: bool = True

    def resolve(self, phantom_value: Any) -> Any:
        return phantom_value if self.use_phantom else self.value


# ---------------------------------------------------------------------------
# Default values used when creating the phantom item
# ---------------------------------------------------------------------------

PHANTOM_DEFAULTS: dict[str, Any] = {
    # Canvas
    "canvas_width": 1280,
    "canvas_height": 720,
    # Image framing
    "image_fit": "fill",    # fill | fit | stretch | center
    "crop_x": 0.0,          # normalized 0-1
    "crop_y": 0.0,
    "crop_w": 1.0,
    "crop_h": 1.0,
    # Text position
    "text_x": 0.5,          # normalized; anchor is horizontal center
    "text_y": 0.82,         # normalized; anchor is vertical center of text block
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
    return SF(value=PHANTOM_DEFAULTS[key], use_phantom=True)


@dataclass
class ItemSettings:
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
        return getattr(self, name)

    def set_value(self, name: str, value: Any, use_phantom: bool | None = None):
        sf: SF = getattr(self, name)
        sf.value = value
        if use_phantom is not None:
            sf.use_phantom = use_phantom

    def field_names(self) -> list[str]:
        return [f.name for f in dc_fields(self)]


# ---------------------------------------------------------------------------
# ResolvedSettings — flat dict, no SF wrappers; result of phantom resolution
# ---------------------------------------------------------------------------

@dataclass
class ResolvedSettings:
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


def resolve(item: ItemSettings, phantom: ItemSettings) -> ResolvedSettings:
    """Build a ResolvedSettings by substituting phantom values where use_phantom=True."""
    kwargs = {}
    for f in dc_fields(item):
        item_sf: SF = getattr(item, f.name)
        phantom_sf: SF = getattr(phantom, f.name)
        kwargs[f.name] = phantom_sf.value if item_sf.use_phantom else item_sf.value
    return ResolvedSettings(**kwargs)


# ---------------------------------------------------------------------------
# ThumbnailItem
# ---------------------------------------------------------------------------

@dataclass
class ThumbnailItem:
    id: str
    label: str
    image_path: Optional[str]       # None = inherit phantom image
    settings: ItemSettings
    is_phantom: bool = False

    @classmethod
    def make_phantom(cls) -> ThumbnailItem:
        s = ItemSettings()
        for f in dc_fields(s):
            getattr(s, f.name).use_phantom = False
        return cls(id="__phantom__", label="", image_path=None, settings=s, is_phantom=True)

    @classmethod
    def new_item(cls, label: str, item_id: str | None = None) -> ThumbnailItem:
        return cls(
            id=item_id or uuid.uuid4().hex[:8],
            label=label,
            image_path=None,
            settings=ItemSettings(),
        )

    def effective_image(self, phantom: ThumbnailItem) -> Optional[str]:
        """Return this item's image path, or the phantom's if not set."""
        return self.image_path or phantom.image_path


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------

@dataclass
class Project:
    name: str
    items: list          # list[ThumbnailItem]; items[0] is always the phantom
    output_dir: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    modified_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @classmethod
    def new(cls, name: str, output_dir: str) -> Project:
        return cls(name=name, items=[ThumbnailItem.make_phantom()], output_dir=output_dir)

    @property
    def phantom(self) -> ThumbnailItem:
        return self.items[0]

    @property
    def content_items(self) -> list:
        return self.items[1:]

    def add_item(self, label: str) -> ThumbnailItem:
        item = ThumbnailItem.new_item(label)
        self.items.append(item)
        return item

    def remove_item(self, item_id: str):
        self.items = [i for i in self.items if i.id != item_id or i.is_phantom]

    def touch(self):
        self.modified_at = datetime.now().isoformat()

    def resolve_item(self, item: ThumbnailItem) -> ResolvedSettings:
        if item.is_phantom:
            return resolve(item.settings, item.settings)
        return resolve(item.settings, self.phantom.settings)
