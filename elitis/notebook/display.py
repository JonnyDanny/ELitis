"""
Cell-level display helpers for the Colab/Jupyter frontend.

All functions call IPython.display themselves so cells stay as one-liners.
Functions that return HTML strings (suffix _html) are for embedding inside
larger layouts without triggering display.
"""
from __future__ import annotations

import base64
import io as _io
import json
import shutil
import zipfile
from pathlib import Path
from typing import Optional

from elitis.notebook._utils import html_table, rgb_to_hex


# ---------------------------------------------------------------------------
# Cell 1 — import panel
# ---------------------------------------------------------------------------

def import_panel(
    project_dir: str | Path,
    output_dir: str | Path,
    canvas_w: int = 1280,
    canvas_h: int = 720,
    existing_project=None,
):
    """
    Full Cell-1 flow: upload zip/CSV, extract, load or build project, show summary.

    Re-running with ``existing_project`` triggers additive reconciliation: the
    uploaded CSV is merged into the existing project (master stays, new labels
    are added, duplicates/conflicts are reported).

    Returns the loaded or updated Project object.
    """
    from IPython.display import display, HTML

    project_dir = Path(project_dir)
    output_dir  = Path(output_dir)

    # -- upload ---------------------------------------------------------------
    try:
        from google.colab import files as _colab_files
        _in_colab = True
    except ImportError:
        _in_colab = False

    if _in_colab:
        mode = "additive CSV" if existing_project else "project zip"
        print(f"Upload your {mode}:")
        uploaded = _colab_files.upload()
        if not uploaded:
            raise RuntimeError("No file uploaded.")

        if project_dir.exists() and not existing_project:
            shutil.rmtree(project_dir)
        project_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        for name, data in uploaded.items():
            if name.lower().endswith(".zip"):
                with zipfile.ZipFile(_io.BytesIO(data)) as z:
                    z.extractall(project_dir)
                print(f"Extracted {name}")
            else:
                dest = project_dir / name
                dest.write_bytes(data)
                print(f"Saved {name}")
    else:
        print(f"[Not in Colab] Place project files in: {project_dir}")
        project_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

    # -- discover contents ----------------------------------------------------
    IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}
    LABEL_EXTS = {".csv", ".tsv", ".txt"}

    all_images = sorted(p for p in project_dir.rglob("*") if p.suffix.lower() in IMAGE_EXTS)
    all_jsons  = sorted(p for p in project_dir.rglob("*.json"))
    all_labels = sorted(p for p in project_dir.rglob("*") if p.suffix.lower() in LABEL_EXTS)

    img_lookup: dict[str, Path] = {}
    for p in all_images:
        img_lookup[p.name.lower()] = p
        img_lookup[p.stem.lower()] = p

    def _remap(path_str):
        if not path_str:
            return None
        p = Path(path_str)
        return str(img_lookup.get(p.name.lower()) or img_lookup.get(p.stem.lower()) or path_str)

    # -- additive mode --------------------------------------------------------
    if existing_project is not None:
        from elitis.core.data_io import import_labels, reconcile_import, reconcile_report_lines
        for label_file in all_labels:
            labels = import_labels(label_file)
            result = reconcile_import(existing_project, labels, origin=label_file.stem)
            for line in reconcile_report_lines(result):
                print(line)
        display(HTML(items_summary_html(existing_project)))
        return existing_project

    # -- first load -----------------------------------------------------------
    from elitis.core import data_io
    from elitis.core.models import Project

    if all_jsons:
        project = data_io.load_project(all_jsons[0])
        for item in project.items:
            item.image_path = _remap(item.image_path)
        print(f"Loaded '{project.name}' — {len(project.content_items)} items")

        # Also reconcile any accompanying CSVs
        if all_labels:
            from elitis.core.data_io import import_labels, reconcile_import, reconcile_report_lines
            for label_file in all_labels:
                labels = import_labels(label_file)
                result = reconcile_import(project, labels, origin=label_file.stem)
                for line in reconcile_report_lines(result):
                    print(line)
    else:
        if all_labels:
            labels = data_io.import_labels(all_labels[0])
            origin = all_labels[0].stem
        else:
            labels = [p.stem for p in all_images]
            origin = "images"

        project = Project.new("imported", str(output_dir))
        project.defaults.settings.canvas_width.value  = canvas_w
        project.defaults.settings.canvas_height.value = canvas_h
        for label in labels:
            item = project.add_item(label)
            match = (
                img_lookup.get(label.lower().replace(" ", "_"))
                or img_lookup.get(label.lower())
            )
            if match:
                item.image_path = str(match)
                item.origin = origin
        print(f"Created project '{project.name}' — {len(project.content_items)} items")

    display(HTML(items_summary_html(project)))
    return project


# ---------------------------------------------------------------------------
# Items summary (used by Cell 1 and as a standalone refresh)
# ---------------------------------------------------------------------------

def items_summary_html(project) -> str:
    rows = [
        [
            item.label or "—",
            Path(item.image_path).name if item.image_path else "<i style='color:#f66'>no image</i>",
            item.origin or "",
        ]
        for item in project.content_items
    ]
    return (
        "<b>Items ready to render:</b><br>"
        + html_table(["Label", "Image", "Origin"], rows)
    )


def show_items_summary(project) -> None:
    from IPython.display import display, HTML
    display(HTML(items_summary_html(project)))


# ---------------------------------------------------------------------------
# Warnings table (used by Cell 4 and NotebookAppState._on_warnings)
# ---------------------------------------------------------------------------

_SEV_STYLE = {
    "error": "color:#f66;font-weight:bold",
    "warn":  "color:#fa0",
}


def show_warnings(warnings: list) -> None:
    from IPython.display import display, HTML
    if not warnings:
        print("No warnings.")
        return
    rows = [
        [
            f"<span style='{_SEV_STYLE.get(w.severity, '')}'>{w.severity.upper()}</span>",
            w.code,
            w.item_id,
            w.message,
        ]
        for w in warnings
    ]
    display(HTML(
        f"<b style='color:#fa0'>{len(warnings)} warning(s):</b><br>"
        + html_table(["SEV", "CODE", "ITEM", "MESSAGE"], rows, max_height=200)
    ))


# ---------------------------------------------------------------------------
# Gallery (used by Cell 4)
# ---------------------------------------------------------------------------

def show_gallery(output_dir: str | Path, thumb_size: tuple = (320, 180)) -> None:
    from IPython.display import display, HTML
    from PIL import Image

    output_dir = Path(output_dir)
    images = sorted(output_dir.glob("*"))
    if not images:
        print("No rendered images found.")
        return

    def _b64(path: Path) -> str:
        img = Image.open(path)
        img.thumbnail(thumb_size, Image.Resampling.LANCZOS)
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    cards = "".join(
        f"<div style='display:inline-block;margin:6px;text-align:center;vertical-align:top'>"
        f"<img src='data:image/png;base64,{_b64(p)}'"
        f" style='border-radius:4px;display:block'/>"
        f"<small style='color:#ccc'>{p.stem}</small></div>"
        for p in images
    )
    display(HTML(
        "<div style='max-height:640px;overflow-y:auto;background:#1a1a1a;"
        "padding:10px;border-radius:6px;line-height:1.2'>"
        + cards + "</div>"
    ))
