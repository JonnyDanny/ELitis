# ELItis

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

Tier list thumbnail generator. Produces a styled image for every item in your
list — consistent font, box overlay, crop, and text — exported as PNG or JPEG.
All measurements are stored as fractions of the output canvas so resolution
can change without re-tuning any setting.

## Requirements

- Python 3.12+
- PySide6, Pillow (desktop app)
- ipywidgets, IPython (Jupyter / Colab frontend only)

```bash
pip install PySide6 Pillow
# or, for Colab:
pip install ipywidgets Pillow
```

Optional faster hashing:

```bash
pip install blake3
```

## Quick start — Desktop

```bash
# Interactive GUI
python -m elitis

# GUI, opens batch export dialog immediately on launch
python -m elitis --batch

# CLI batch from a saved project file
python -m elitis --cli my_project.json
```

## Quick start — Jupyter / Colab

Open `ELItis_Colab.ipynb` in Google Colab or any Jupyter environment.
The notebook walks through five cells:

| Cell | Purpose |
|------|---------|
| 0 | Install deps, mount Drive |
| 1 | Load or create a project |
| 2 | Assign images (upload, URL, paste from clipboard) |
| 3 | Tune per-item settings and previews |
| 4 | Batch export |

Clipboard paste in Colab: click **Paste image** in the Cell 2 widget, then
accept the browser permission prompt. Handles raw image data, inline base64,
and HTTP image URLs.

## Project layout

```
ELItis/
├── elitis/
│   ├── core/              # Pure logic — no Qt or Jupyter imports
│   │   ├── models.py
│   │   ├── renderer.py
│   │   ├── data_io.py
│   │   ├── font_manager.py
│   │   ├── ingest.py      # Atomic source-image store
│   │   ├── text_utils.py
│   │   └── app_state.py   # Shared session state (base class)
│   ├── ui/                # PySide6 desktop app
│   │   ├── app_state.py
│   │   ├── main_window.py
│   │   ├── tabs/
│   │   └── widgets/
│   ├── notebook/          # Jupyter / Colab frontend
│   │   ├── images.py      # Image assignment panel
│   │   ├── paste.py       # Clipboard paste widget
│   │   ├── tune.py        # Per-item settings panel
│   │   └── display.py
│   └── cli/               # Headless batch runner
├── Fonts/                 # Drop .ttf/.otf here (subdirectories OK)
├── Ingest/
│   ├── Pasted/            # Clipboard images (desktop app)
│   └── Sourced/           # Content-addressed ingest store (all frontends)
├── Egest/                 # Output thumbnails
├── Projects/              # Saved .json project files
└── ELItis_Colab.ipynb
```

## GUI overview

Four tabs:

| Tab | Purpose |
|-----|---------|
| **Preview** | Full-size preview, filmstrip navigation, image assignment, single/batch export |
| **Framing** | Interactive crop overlay, fit mode, canvas size |
| **Fonts & Style** | Font selection, text appearance, outline, shadow, box overlay |
| **Data** | Label list, image paths, label import, project save/load |

All settings on every item default to the **Defaults (template)** item (☁ Defaults
button in Preview). Override any setting per-item by unchecking the toggle next to it.

### Image acquisition — desktop

- **Ctrl+V** — paste from clipboard (raw image, base64 data-URL, or HTTP URL)
- **Double-click Image cell** — file picker (files outside `Ingest/` are copied
  into `Ingest/Sourced/` automatically)
- **Drag and drop** — local image files or HTTP image URLs onto the window

Every acquired image is committed to `Ingest/Sourced/` as
`{hash16}_{rand8}.ext` with a JSON sidecar recording provenance
(source URL, original filename, timestamp). Output PNGs embed render settings
in a tEXt chunk (key `elitis`).

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| `←` / `→` | Previous / next item |
| `Ctrl+V` | Paste image from clipboard |

## Batch CLI

The CLI batch mode requires a project JSON file that already has all settings,
image paths, and per-item crop data assigned. Save a project from the GUI or
Colab first, then run:

```bash
python -m elitis --cli my_project.json
python -m elitis --cli my_project.json --format JPEG --output /path/to/out
```

## Label import

In the Data tab (GUI) or via the notebook Cell 1, you can import a plain-text
or CSV file of labels. One label per line; CSV/TSV uses the first column by
default.

**Blank lines are skipped automatically.** Lines that serve as section headers
or tier separators (e.g. `"S TIER"`, `"---"`) are treated as ordinary labels
and will become rendered items — remove them in the Data tab after import if
they are not meant to be part of the output. The final item count is what the
Data tab shows, not the raw line count of the source file.

## Save format

Projects are saved as JSON (version `0.2.0.pre`). Files from the earlier
`is_phantom` / `use_phantom` format (pre-0.2) are still loaded correctly.
Per-item crop/pan data is stored as normalised fractions (`crop_x`, `crop_y`,
`crop_w`, `crop_h`) so it remains valid across canvas resolution changes.

## Fonts

Place any `.ttf` or `.otf` file anywhere under `Fonts/` — subdirectories are
scanned recursively. The bundled Fredoka family (26 static TTFs) is discovered
automatically.

## Output

Batch export saves to `Egest/<project-name>/` as `000_Label.png`,
`001_Label.png`, …. Single-item export from the Preview tab uses the same
naming in the same folder. PNG output embeds the full render configuration in
a `elitis` tEXt metadata chunk.
