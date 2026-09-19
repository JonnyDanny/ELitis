# ELItis — Architecture

## Package structure

```
elitis/
├── __init__.py           __version__ = "0.2.0.pre"
├── main.py               entry point, dir setup, arg parsing, run_gui / run_cli
├── __main__.py           delegates to main()
│
├── core/                 Pure logic — zero Qt, zero Jupyter imports
│   ├── models.py         SF, ItemSettings, ResolvedSettings, ThumbnailItem,
│   │                     Project, ImageHash, RenderWarning
│   ├── renderer.py       render_thumbnail(), check_text_fit(), render_all()
│   ├── data_io.py        save/load project, import_labels, reconcile_import
│   ├── text_utils.py     normalize_label(), comparison_key(), case dict I/O
│   ├── app_state.py      BaseAppState — shared write boundary, project coordination
│   └── font_manager.py   FontManager — discovery, Qt registration, PIL cache
│
├── ui/                   PySide6 frontend
│   ├── app_state.py      AppState(QObject, BaseAppState) — signals + Qt-specific ops
│   ├── main_window.py    QMainWindow shell (tab host)
│   ├── theme.py          dark stylesheet
│   ├── tabs/
│   │   ├── import_tab.py    label table, additive CSV import, reconcile report
│   │   ├── images_tab.py    image assignment — file picker, paste, URL; per-item framing
│   │   └── preview_tab.py   canvas, filmstrip, warnings panel, export button
│   ├── dialogs/
│   │   ├── project_settings.py  canvas size (AR lock) + project name/output dir
│   │   ├── tune_modal.py        project-wide: font + fallback chain, text style, overlay
│   │   └── override_modal.py    per-item emergency overrides (font floor, max lines)
│   └── widgets/
│       ├── setting_row.py   SettingRow and subclasses, make_row() factory, RowContext
│       ├── framing_canvas.py  interactive crop/zoom widget
│       ├── canvas_widget.py   live preview display
│       └── color_button.py    inline color picker button
│
├── notebook/             Jupyter/Colab frontend — ipywidgets, IPython.display, google.colab
│   ├── app_state.py      NotebookAppState(BaseAppState) — print/ipywidgets hooks
│   ├── display.py        gallery, warnings table, reconcile report (HTML/widgets)
│   ├── tune.py           ipywidgets panels: font_panel(), text_panel(), overlay_panel()
│   ├── images.py         upload / paste / URL image assignment UI
│   └── overrides.py      emergency per-item override panel
│
└── cli/
    └── runner.py         run_cli_batch(), run_cli_interactive()
```

---

## Data model (`core/models.py`)

### ImageHash

```python
@dataclass
class ImageHash:
    sha256: str            # primary integrity check
    crc32:  str            # fast secondary
    blake3: Optional[str]  # None when blake3 package not installed
    width:  int            # stored for resolution pre-filter
    height: int
```

**Hash severity ladder**

| Severity | Condition |
|----------|-----------|
| `HASH_OK` | sha256 matches |
| `HASH_WARN` | sha256 mismatch, resolution same — benign metadata/EXIF rewrite |
| `HASH_ERROR` | sha256 mismatch + resolution different, or file missing |

`accept_image_hash(item)` recomputes and stores the current hash, silencing any warning.

### RenderWarning

```python
@dataclass
class RenderWarning:
    item_id:  str
    severity: str   # "warn" | "error"
    code:     str   # machine-readable tag (see tables below)
    message:  str   # human-readable, shown in UI
```

**Text fit warning codes** — raised by `check_text_fit()`

| Code | Severity | Condition | Message pattern |
|------|----------|-----------|-----------------|
| `text_word_too_wide` | error | A single word is wider than the text area at min font size | "Word 'X' wider than text area at minimum font size (28px)" |
| `text_truncated` | error | Text still overflows after reaching minimum font size | "Text still overflows after reaching minimum font size (28px) — N line(s) cut" |
| `text_overflow` | error | Rendered text block extends outside canvas bounds | "Text block extends outside canvas (top=−12px)" |
| `text_ragged` | warn | Multi-line: line 2+ uses <60% of line 1 width | "Multi-line text: line 2 uses only 42% of line 1 width" |
| `text_underutilized` | warn | All lines use <40% of available text width | "Text uses only 28% of available width" |

**Image warning codes** (from `check_image_integrity()`)

| Code | Severity | Condition |
|------|----------|-----------|
| `image_missing` | error | No image assigned; renders as checkerboard |
| `image_hash_warn` | warn | sha256 mismatch, same resolution |
| `image_hash_error` | error | sha256 mismatch + resolution changed |

**Emergency overrides** — per-item escape hatches shown in the override modal when a warning fires, or accessible manually via filmstrip button:

| Override | Resolves |
|----------|---------|
| Decrease min font size | `text_truncated`, `text_word_too_wide` |
| Increase max lines | `text_truncated` |
| Edit label (this item only) | any text warning |
| Accept image as-is | `image_hash_warn`, `image_hash_error` |

### SettingField (SF)

```python
@dataclass
class SF:
    value: Any
    use_default: bool = True
```

### ThumbnailItem

```
id: str
label: str           the title stamped on the thumbnail
image_path: str|None
settings: ItemSettings
is_default: bool     True only for items[0] (the defaults item)
image_hash: ImageHash|None   integrity fingerprint, set at image assignment
origin: str|None     CSV filename or project name — merge provenance trail
```

`origin` is visible in the gallery/import tab to let users spot divergences
between sources.

### Project

```
name: str
output_dir: str
items: list[ThumbnailItem]   items[0] is always the defaults item
canvas_width: int            project-level — shared by all items
canvas_height: int
modified_at: str
```

Canvas size lives on `Project`, not on `ItemSettings` — changing it affects
every item and requires a confirmation dialog with an aspect-ratio lock warning.

---

## Settings inheritance

**Project-wide defaults** (tuned once, apply to all items):
- Font: primary font + fallback chain for non-ASCII glyphs
- Text style: color, opacity, alignment, position, transform
- Overlay: box color/opacity/height/position, outline, shadow

**Per-item** (content varies):
- Framing: fit mode + crop (each source image is different)
- Per-item overrides for specific problems (smaller font floor, extra lines) —
  accessed via the override modal, not the regular tune UI

The defaults item (`items[0]`, `is_default=True`) has `use_default=False` on
every field — it IS the source; it has no parent to inherit from.

---

## Canvas size and aspect-ratio lock

Canvas size is a project-level invariant set at creation. Mid-project changes:

1. Show confirmation: *"Canvas size changed — all existing crops may need adjustment. Continue?"*
2. If the aspect ratio also changes: additional warning that all framed images
   are now distorted.

The AR link/unlink toggle (chain icon) links width↔height so changing one
adjusts the other proportionally until the user explicitly breaks the lock.

---

## Label normalization (`core/text_utils.py`)

Normalization stack applied in order before storage or comparison:

| Step | Fixes | Stored | Reported |
|------|-------|--------|----------|
| 1. Unicode NFC | precomposed vs combining chars | yes | no |
| 2. Invisible chars | zero-width, BOM, soft-hyphen | yes | no |
| 3. Line endings | `\r\n`, `\r` → `\n` | yes | no |
| 4. Whitespace | strip + collapse runs | yes | count |
| 5. Case dictionary | `{"pikachu": "Pikachu"}` | yes | per-item |

`comparison_key(text)` — lowercase form for dedup only, never stored.

**Case dictionary** — `<project_dir>/case_corrections.json`

Entries added via "Fix case" action in gallery/import tab, or when user
picks canonical form during reconciliation.

**Case conflict heuristics**

| Situation | Treatment |
|-----------|-----------|
| 1 case mismatch against existing | Report, keep existing form |
| >=2 case conflicts in one import | `systematic_case=True` — likely whole-CSV casing difference |
| Same stem in multiple case forms within incoming CSV | Second+ occurrence treated as within-CSV duplicate |

---

## Additive CSV import & reconciliation (`core/data_io.py`)

**Entry point:** `reconcile_import(project, labels, origin, case_dict=None) → ReconcileResult`

**Pairwise chaining** — always master → subordinate → new master:

```
project + csv1 → project'
project' + csv2 → project''
```

**Per-label classification:**

```
normalize_label(raw)
   ├─ comparison_key in existing?
   │     ├─ normalized == existing  →  exact_skipped
   │     └─ normalized != existing  →  case_conflicts (existing kept)
   └─ new  →  add_item(normalized, origin=origin)
```

`reconcile_report_lines(result)` — ASCII-safe lines, frontend-agnostic.

**Frontend interface (minimum)**

*Qt Import tab*: calls `import_labels()` + `reconcile_import()`, shows
`reconcile_report_lines()` in a status dialog. "Fix case" context menu on label
rows calls `add_case_correction()`.

*Colab Cell 1*: same two calls + `print()` of report lines. Optional ipywidgets
conflict table for case arbitration (deferred).

---

## Frontend state split

### BaseAppState (`core/app_state.py`)

Pure Python. Owns the live `Project` and all write-boundary logic.
Hook methods are no-ops in base; overridden per frontend.

```python
def _on_changed(self, item): pass
def _on_navigation_changed(self, index): pass
def _on_project_replaced(self): pass
def _on_items_status_changed(self): pass
def _on_status_message(self, msg): pass
def _on_warnings(self, warnings: list): pass   # fired after render_all
```

### AppState (`ui/app_state.py`)

`class AppState(QObject, BaseAppState)` — QObject first in MRO (required).
Overrides `_on_*` hooks to emit Qt signals.
Adds: background preview rendering (`_RenderTask / QThreadPool`), clipboard paste,
resolution warning on image assignment.

### NotebookAppState (`notebook/app_state.py`) — planned

`class NotebookAppState(BaseAppState)` — overrides `_on_*` hooks to
`print()` / update `ipywidgets` output widgets.

---

## Write boundary (`core/app_state.py` + subclasses)

The only place that mutates the live model. All tabs / cells / CLI call methods here.

| Method | Writes |
|--------|--------|
| `commit_field(field, value, use_default, item=None)` | one SF |
| `commit_crop(x, y, w, h)` | four crop SFs |
| `commit_label(item_id, label)` | `ThumbnailItem.label` |
| `commit_image(item_id, path)` | `ThumbnailItem.image_path` + `image_hash` |
| `insert_item(at, label)` | new item |
| `remove_item(item_id)` | remove item |
| `move_item(row, delta)` | swap adjacent |
| `replace_items(content_list)` | replace all content items |

Every SF write ends in `_react(item)` → dirty tracking → `_on_*` hook.

**Dirty tracking**

| State | Meaning |
|-------|---------|
| `_defaults_dirty: bool` | defaults item changed since last load/new |
| `_clean_ids: set[str]` | item ids whose last export is still current |
| `is_clean(id)` | True if in `_clean_ids` |
| `mark_rendered(id)` | add to clean after single export |
| `mark_all_rendered()` | all content items clean after batch export |

---

## Render pipeline (`core/renderer.py`)

### render_thumbnail()

Single item, live preview or full-res export. Never raises — bad images fall
back to grey checkerboard so partial projects are always renderable.

```
resolve_item(item)          → ResolvedSettings
_load_background(...)       → RGBA PIL Image (or checkerboard)
_apply_framing(img, cfg)    → crop + fit mode → canvas-sized RGBA
_composite_box(img, cfg)    → semi-transparent overlay rectangle
_draw_text(img, label, cfg) → shadow → outline → fill on separate RGBA layer
[_fit_to_preview(img, size)]→ preview only
```

### check_text_fit()

Dry-run layout to produce warnings without rendering.
Separated from `render_thumbnail` so the preview path stays fast (no warning
computation on every keystroke).

Called by `render_all()` for each item; also callable standalone to re-scan
the warnings panel without re-rendering.

### render_all() → (list[Path], list[RenderWarning])

Batch render + warning scan. Returns both the saved paths and the full warning
list. `_on_warnings(warnings)` hook fires after all items are processed.

### Fit modes

| Mode | Behaviour |
|------|-----------|
| `fill` | AR-locked crop stretched to fill canvas |
| `zoom` | freehand crop letterboxed to fit canvas |
| `fit` | whole image letterboxed |
| `stretch` | whole image stretched, no AR |
| `center` | native resolution, centered, edges clip |

### Color suggestion stubs

Connection points for future image-based or AI-driven palette tools.
Not implemented — raise `NotImplementedError`.

```python
def _suggest_text_color(image) -> tuple: ...
def _suggest_box_color(image) -> tuple: ...
def _suggest_box_opacity(image) -> int: ...
```

---

## Qt UI structure

### Tabs

| Tab | Equivalent cell | Contents |
|-----|----------------|----------|
| **Import** | Cell 1 | Label table, additive CSV, reconcile report, origin column, case dict "Fix" action |
| **Images** | Cell 2 | Image assignment (file picker / paste / URL / folder watch), per-item framing (crop overlay) |
| **Preview** | Cell 4 | Canvas, filmstrip, warnings panel, override button per item |

### Dialogs / modals

| Dialog | When opened | Contents |
|--------|-------------|----------|
| **Project Settings** | New project / Edit → Project | Canvas size (AR link/unlink), project name, output dir |
| **Tune** | Button in Preview tab | Project-wide: font + fallback chain, text style (color/opacity/align/position/transform), overlay (box/outline/shadow) |
| **Override** | Click warning row OR filmstrip button | Per-item: font floor, max lines, label edit; image: accept-as-is |

### Export

Button + save dialog in Preview tab. No dedicated tab (mirrors Colab Cell 5).

### Signals (Qt)

| Signal | Consumers |
|--------|-----------|
| `current_changed(int)` | all tabs refresh |
| `settings_changed()` | (reserved) |
| `project_replaced()` | table + filmstrip rebuild |
| `preview_ready(QPixmap)` | canvas widget |
| `items_status_changed()` | Import tab status column |
| `status_message(str)` | status bar (4 s timeout) |
| `warnings_updated(list)` | warnings panel |

---

## Colab notebook cell architecture

Each cell is independently re-runnable. Cells call functions from
`elitis.notebook.*` — all ipywidgets/display complexity lives there, not in
the notebook itself.

| Cell | Name | Re-run when | One-liner |
|------|------|-------------|-----------|
| **0** | Setup | Once per session | install, define paths, canvas size |
| **1** | Import | New CSV added | `from elitis.notebook.display import import_panel; import_panel(project)` |
| **2** | Images | Unmatched items need images | `from elitis.notebook.images import image_panel; image_panel(project)` |
| **3a** | Tune · Font | Font or fallback changes | `from elitis.notebook.tune import font_panel; font_panel(project)` |
| **3b** | Tune · Text | Text style changes | `from elitis.notebook.tune import text_panel; text_panel(project)` |
| **3c** | Tune · Overlay | Box/outline/shadow changes | `from elitis.notebook.tune import overlay_panel; overlay_panel(project)` |
| **3e** | Overrides | Warning-driven or manual | `from elitis.notebook.overrides import override_panel; override_panel(project)` |
| **4** | Render | After any tune | full render → inline gallery → warnings table |
| **5** | Export | Once at end | zip output → `files.download()` |

**Cell 4 owns the render.** Cell 5 zips what Cell 4 wrote; no re-render.

**Image path remapping:** Windows absolute paths in project JSON translated to Colab
paths by filename stem match via `_remap()` in Cell 0/1.

---

## Multi-font fallback chain — planned

Project-level ordered list: `[primary_font, fallback_1, fallback_2, ...]`

At render time, for each word (or glyph): if the primary font cannot render it,
try fonts in order. Common use: primary is a display font for Latin; fallback is
a CJK or emoji font. Implemented in `FontManager` + `_draw_text`.

---

## 3-way project merge — planned

When merging two project JSONs from two collaborators:

1. **Base** — default-settings file or empty sentinel
2. **Master** — higher authority
3. **Subordinate** — other project

Per-field differences between master and subordinate defaults surface as
*"these two are incongruent → difference is X → these are the defaults."*
User chooses per field; choices are recordable to avoid re-asking on future merges.

Per-item differences resolved the same way. `origin` column in gallery lets users
spot persistent divergences. A "force to project default" command resets all
per-item overrides for a given field.

---

## Save format

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
      "image_hash": null,
      "origin": null,
      "is_default": true,
      "settings": { "canvas_width": {"value": 1280, "use_default": false}, ... }
    },
    {
      "id": "a3f1b2c4",
      "label": "Hollow Knight",
      "image_path": "/path/to/image.png",
      "image_hash": {
        "sha256": "abc123...", "crc32": "deadbeef",
        "blake3": null, "width": 1920, "height": 1080
      },
      "origin": "games.csv",
      "is_default": false,
      "settings": { "canvas_width": {"value": 1280, "use_default": true}, ... }
    }
  ]
}
```

**Backward compatibility:** pre-0.2 `"is_phantom"` / `"use_phantom"` keys still
accepted. `image_hash` and `origin` absent → `None`.

---

## Implementation roadmap

### Phase 1 — Core completions (no UI changes)
- [x] `ImageHash` + `check_image_integrity()` + `accept_image_hash()` in `data_io.py`
- [x] `ThumbnailItem.image_hash`, `.origin`
- [x] `text_utils.py` — `normalize_label()`, `comparison_key()`, case dict
- [x] `reconcile_import()` + `ReconcileResult` in `data_io.py`
- [x] `BaseAppState` extracted to `core/app_state.py`
- [ ] `RenderWarning` dataclass in `models.py`
- [ ] `check_text_fit()` in `renderer.py`
- [ ] `render_all()` → `(list[Path], list[RenderWarning])`
- [ ] Color suggestion stubs in `renderer.py`
- [ ] `BaseAppState._on_warnings` hook

### Phase 2 — Qt UI reorganization
- [ ] `import_tab.py` (rename `data_tab`, add reconcile UI + origin column)
- [ ] `images_tab.py` (new: image sources + per-item framing)
- [ ] `preview_tab.py` (warnings panel, override button per filmstrip item)
- [ ] `tune_modal.py` (project-wide font/text/overlay)
- [ ] `project_settings.py` dialog (canvas size + AR lock)
- [ ] `override_modal.py` (per-item escape hatches)

### Phase 3 — Notebook module
- [ ] `notebook/app_state.py` — `NotebookAppState`
- [ ] `notebook/display.py` — gallery, warnings table, reconcile report
- [ ] `notebook/tune.py` — `font_panel()`, `text_panel()`, `overlay_panel()`
- [ ] `notebook/images.py` — upload/paste/URL assignment
- [ ] `notebook/overrides.py` — emergency panel
- [ ] Update `ELItis_Colab.ipynb` to use notebook module functions

### Phase 4 — Advanced features
- [ ] Multi-font fallback chain
- [ ] Dynamic color suggestion implementation
- [ ] 3-way project merge

---

## Font management (`core/font_manager.py`)

`FontManager.scan()` walks `fonts_dir` with `rglob("*")`.
Fonts keyed by lowercased stem (`fredoka-semibold`).
PIL fonts `@lru_cache`d by `(path, size)`.
`register_with_qt()` adds all fonts to Qt's font database.

---

## RowContext

`RowContext(is_default: bool)` passed to each `SettingRow` via `apply_context()`
when the current item changes. `is_default=True` hides the toggle checkbox.
New display modes (read-only lock, etc.) added to `RowContext` without touching
slot signatures.
