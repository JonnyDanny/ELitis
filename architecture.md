# ELItis — Architecture

## Package structure

```
elitis/
├── __init__.py           __version__ = "0.2.0.pre"
├── main.py               entry point, dir setup, arg parsing, run_gui / run_cli
├── __main__.py           delegates to main()
│
├── core/                 Pure logic — zero Qt imports
│   ├── models.py         SF, ItemSettings, ResolvedSettings, ThumbnailItem, Project
│   ├── renderer.py       render_thumbnail(), render_all()
│   ├── data_io.py        save_project(), load_project(), import_labels()
│   └── font_manager.py   FontManager — discovery, Qt registration, PIL cache
│
├── ui/
│   ├── app_state.py      AppState — single QObject that owns the live Project
│   ├── main_window.py    QMainWindow shell (tab host)
│   ├── theme.py          dark stylesheet
│   ├── tabs/
│   │   ├── preview_tab.py   canvas, filmstrip, nav, export buttons
│   │   ├── framing_tab.py   interactive crop overlay, fit mode, canvas size
│   │   ├── font_tab.py      font list + all style settings
│   │   └── data_tab.py      label table, image paths, CSV import, project IO
│   └── widgets/
│       ├── setting_row.py   SettingRow and subclasses, make_row() factory, RowContext
│       ├── framing_canvas.py  interactive crop/zoom widget
│       ├── canvas_widget.py   live preview display
│       └── color_button.py    inline color picker button
│
└── cli/
    └── runner.py         run_cli_batch(), run_cli_interactive()
```

---

## Data model (`core/models.py`)

### SettingField (SF)

```python
@dataclass
class SF:
    value: Any
    use_default: bool = True   # True = inherit from defaults item
```

Every visual property is wrapped in an SF. When `use_default=True` the renderer
substitutes the corresponding value from the **defaults item** instead.

### ItemSettings

A flat dataclass of 31 SF fields covering canvas size, image framing (5 fit
modes + crop rect), text position/appearance, font, outline, shadow, and box
overlay. `get(name)` returns the SF by field name.

### ThumbnailItem

```
id: str            short uuid hex
label: str         the title stamped on the thumbnail
image_path: str|None
settings: ItemSettings
is_default: bool   True only for items[0]
```

`effective_image(defaults)` returns `image_path or defaults.image_path` — items
inherit the defaults image when their own is None.

### ResolvedSettings

A plain dataclass with the same 31 fields but no SF wrappers — raw values after
the inheritance lookup. `Project.resolve_item(item)` builds one.

### Project

```
name: str
output_dir: str
items: list[ThumbnailItem]   items[0] is always the defaults item
modified_at: str             ISO timestamp
```

`defaults` → `items[0]`, `content_items` → `items[1:]`.

`find_item(id)` → O(n) lookup by id (used by write boundary methods).

---

## Settings inheritance

Every content item starts with `use_default=True` on all 31 fields. The
renderer calls `Project.resolve_item(item)` which iterates all fields and picks
`defaults.value` when `use_default=True`, or `item.value` otherwise. This makes
the defaults item a global template: changing one field there ripples to every
item that hasn't overridden it.

The **Defaults item** (`is_default=True`) always has `use_default=False` on
every field — it has no higher-level source to inherit from.

Per-row override is toggled by the ☁ checkbox in each SettingRow. Enabling an
override for the first time seeds the control with the current default value so
edits feel continuous rather than jumping to an old stale value.

---

## Write boundary (`ui/app_state.py`)

`AppState` is the **only** place that mutates the live model. Tabs read the
model but call AppState methods to write.

### Commit methods

| Method | Writes |
|--------|--------|
| `commit_field(field, value, use_default, item=None)` | one SF on current item (or explicit item) |
| `commit_crop(x, y, w, h)` | four crop SFs in one `_react` call |
| `commit_label(item_id, label)` | `ThumbnailItem.label` |
| `commit_image(item_id, path)` | `ThumbnailItem.image_path` |
| `insert_item(at, label)` | inserts new item, emits `project_replaced` |
| `remove_item(item_id)` | removes item, cleans `_clean_ids`, emits `project_replaced` |
| `move_item(row, delta)` | swaps adjacent items, emits `project_replaced` |
| `replace_items(content_list)` | replaces all content items, emits `project_replaced` |

Every SF-level write ends in `_react(item)`:

```python
def _react(self, item):
    if item.is_default:
        self._defaults_dirty = True
    else:
        self._clean_ids.discard(item.id)
    self.settings_changed.emit()
    self.request_preview()
    self.items_status_changed.emit()
```

`SettingRow` still writes to SF directly (it holds the reference and needs
immediate display feedback), then the tab's `row.changed` connection calls
`notify_settings_changed()` which delegates to `_react(current_item)`.

### Dirty tracking

| State | Meaning |
|-------|---------|
| `_defaults_dirty: bool` | defaults item changed since last load/new |
| `_clean_ids: set[str]` | item ids whose last export is still current |
| `is_clean(id)` | True if item is in `_clean_ids` |
| `mark_rendered(id)` | adds to `_clean_ids` after single export |
| `mark_all_rendered()` | batch export — all content items become clean |

---

## Render pipeline (`core/renderer.py`)

`render_thumbnail(item, project, font_manager, preview_size=None)` is the
single entry point shared by GUI preview and CLI/batch export.

```
resolve_item(item)          → ResolvedSettings (inheritance lookup)
_load_background(...)       → RGBA PIL Image (or checkerboard placeholder)
_apply_framing(img, cfg)    → crop + fit mode applied to output canvas size
_composite_box(img, cfg)    → semi-transparent overlay rectangle
_draw_text(img, label, cfg) → outline → shadow → main text, all on RGBA layer
[_fit_to_preview(img, size)]→ thumbnail for live preview only
```

### Fit modes

| Mode | Behaviour |
|------|-----------|
| `fill` | crop rect is AR-locked to canvas; crop region stretched to fill exactly |
| `zoom` | freehand crop region; scaled to fit within canvas (letterboxed) |
| `fit` | whole image letterboxed to fit canvas |
| `stretch` | whole image stretched to fill canvas |
| `center` | native resolution, centered, edges clipped |

All measurements stored as fractions of the canvas (`box_height: 0.22`, `crop_w:
0.6`, …) so the same project file renders correctly at any output resolution.

### Background render worker

`_RenderTask(QRunnable)` runs `render_thumbnail` on `QThreadPool.globalInstance()`.
On completion it emits `done(QPixmap, item_index)`. `AppState._on_render_done`
checks `index == self._current_index` before forwarding to `preview_ready` —
stale renders from rapid navigation are discarded.

---

## Signals

| Signal | Source | Consumers |
|--------|--------|-----------|
| `current_changed(int)` | `go_to()` | all tabs refresh to new item |
| `settings_changed()` | `_react()` | (reserved; no direct consumer yet) |
| `project_replaced()` | structural writes | table rebuild, filmstrip rebuild |
| `preview_ready(QPixmap)` | render worker | PreviewTab canvas |
| `items_status_changed()` | `_react()`, `mark_*` | DataTab status column |
| `status_message(str)` | various | status bar (4 s timeout) |

---

## Save format (`core/data_io.py`)

```json
{
  "version": "0.2.0.pre",
  "name": "My Project",
  "output_dir": "...",
  "modified_at": "...",
  "items": [
    {
      "id": "__defaults__",
      "label": "",
      "image_path": null,
      "is_default": true,
      "settings": { "canvas_width": {"value": 1280, "use_default": false}, ... }
    },
    {
      "id": "a3f1b2c4",
      "label": "Hollow Knight",
      "image_path": null,
      "is_default": false,
      "settings": { "canvas_width": {"value": 1280, "use_default": true}, ... }
    }
  ]
}
```

Backward compatibility: pre-0.2 files use `"is_phantom"` / `"use_phantom"` key
names. `_item_from_dict` reads `d.get("is_default", d.get("is_phantom", False))`
and `_sf_from_dict` reads `d.get("use_default", d.get("use_phantom", True))`.

---

## Font management (`core/font_manager.py`)

`FontManager.scan()` walks `fonts_dir` with `rglob("*")` so fonts in
subdirectories (e.g. `Fonts/Fredoka/static/`) are discovered automatically.
Fonts are keyed by lowercased stem (`fredoka-semibold`). PIL fonts are
`@lru_cache`d by `(path, size)` to avoid re-parsing on every render call.
`register_with_qt()` adds all fonts to Qt's font database (called once after
`QApplication` exists).

---

## RowContext

`RowContext(is_default: bool)` is passed to each `SettingRow` via
`apply_context()` when the current item changes. When `is_default=True` the
toggle checkbox is hidden — the defaults item IS the source, so "use default"
has no meaning for it. New display modes (e.g. a read-only lock for exported
items) can be added to `RowContext` without changing any slot signatures.
