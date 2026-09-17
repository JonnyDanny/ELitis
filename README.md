# ELItis

Tier list thumbnail generator. Produces a styled image for every item in your
list — consistent font, box overlay, crop, and text — exported as PNG or JPEG.
Clean rewrite of StamperEL; stores all measurements as fractions of the output
canvas so resolution can change without re-tuning any setting.

## Requirements

- Python 3.12+
- PySide6, Pillow

```bash
pip install PySide6 Pillow
```

## Quick start

```bash
# Interactive GUI
python -m elitis

# GUI, opens batch export dialog immediately on launch
python -m elitis --batch

# CLI: render labels from a CSV / TXT file, output PNG files
python -m elitis --cli my_list.csv

# CLI interactive: prompts for labels, then renders
python -m elitis --cli --interactive
```

## Project layout

```
ELItis/
├── elitis/            # Python package
│   ├── core/          # Pure logic — no Qt imports
│   │   ├── models.py
│   │   ├── renderer.py
│   │   ├── data_io.py
│   │   └── font_manager.py
│   ├── ui/            # PySide6 UI
│   │   ├── app_state.py
│   │   ├── main_window.py
│   │   ├── tabs/
│   │   └── widgets/
│   └── cli/
├── Fonts/             # Drop .ttf/.otf here (subdirectories OK)
├── Ingest/            # Source images
├── Egest/             # Output thumbnails
└── Projects/          # Saved .json project files
```

## GUI overview

Four tabs:

| Tab | Purpose |
|-----|---------|
| **Preview** | Full-size preview, filmstrip navigation, image assignment, single/batch export |
| **Framing** | Interactive crop overlay, fit mode, canvas size |
| **Fonts & Style** | Font selection, text appearance, outline, shadow, box overlay |
| **Data** | Label list, image paths, CSV import, project save/load |

All settings on every item default to the **Defaults (template)** item (☁ Defaults
button in Preview). Override any setting per-item by unchecking the toggle next to it.

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| `←` / `→` | Previous / next item |
| `Ctrl+V` | Paste image from clipboard |

## Save format

Projects are saved as JSON (version `0.2.0.pre`). Files from the earlier
`is_phantom` / `use_phantom` format (pre-0.2) are still loaded correctly.

## Fonts

Place any `.ttf` or `.otf` file anywhere under `Fonts/` — subdirectories are
scanned recursively. The bundled Fredoka family (26 static TTFs) is discovered
automatically.

## CLI batch from CSV

CSV/TXT files: one label per line; multi-column files use the first column by
default (pass `--column N` to pick another). A project file is created in
`Projects/` alongside the export.

## Output

Batch export saves to `Egest/<project-name>/` as `000_Label.png`,
`001_Label.png`, …. Single-item export from the Preview tab uses the same
naming in the same folder.
