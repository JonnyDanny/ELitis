"""
Project serialization (JSON) and label import (CSV / plain-text).

Design rules:
  - Import always creates a new Project object; the source file is never modified.
  - Project is saved to Projects/<name>.json.
  - Encoding detection uses chardet; falls back to UTF-8 on failure.
"""
from __future__ import annotations
from dataclasses import fields as dc_fields
from pathlib import Path
from typing import Optional
import json
import csv
import io

from elitis.core.models import (
    Project, ThumbnailItem, ItemSettings, SF, PHANTOM_DEFAULTS
)

try:
    import chardet
    _HAS_CHARDET = True
except ImportError:
    _HAS_CHARDET = False


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _sf_to_dict(sf: SF) -> dict:
    v = sf.value
    if isinstance(v, tuple):
        v = list(v)
    return {"value": v, "use_default": sf.use_default}


def _sf_from_dict(d: dict, default_key: str) -> SF:
    v = d.get("value", PHANTOM_DEFAULTS.get(default_key))
    if isinstance(v, list):
        v = tuple(v)
    # "use_phantom" is the old key name — kept for backward compatibility
    use_default = d.get("use_default", d.get("use_phantom", True))
    return SF(value=v, use_default=use_default)


def _settings_to_dict(s: ItemSettings) -> dict:
    return {f.name: _sf_to_dict(getattr(s, f.name)) for f in dc_fields(s)}


def _settings_from_dict(d: dict) -> ItemSettings:
    s = ItemSettings()
    for f in dc_fields(s):
        if f.name in d:
            setattr(s, f.name, _sf_from_dict(d[f.name], f.name))
    return s


def _item_to_dict(item: ThumbnailItem) -> dict:
    return {
        "id": item.id,
        "label": item.label,
        "image_path": item.image_path,
        "is_phantom": item.is_phantom,
        "settings": _settings_to_dict(item.settings),
    }


def _item_from_dict(d: dict) -> ThumbnailItem:
    return ThumbnailItem(
        id=d["id"],
        label=d.get("label", ""),
        image_path=d.get("image_path"),
        is_phantom=d.get("is_phantom", False),
        settings=_settings_from_dict(d.get("settings", {})),
    )


# ---------------------------------------------------------------------------
# Public save / load
# ---------------------------------------------------------------------------

def save_project(project: Project, path: Path):
    project.touch()
    data = {
        "name": project.name,
        "output_dir": project.output_dir,
        "created_at": project.created_at,
        "modified_at": project.modified_at,
        "items": [_item_to_dict(i) for i in project.items],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_project(path: Path) -> Project:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = [_item_from_dict(d) for d in data.get("items", [])]
    if not items or not items[0].is_phantom:
        items.insert(0, ThumbnailItem.make_phantom())
    return Project(
        name=data.get("name", path.stem),
        items=items,
        output_dir=data.get("output_dir", "Egest"),
        created_at=data.get("created_at", ""),
        modified_at=data.get("modified_at", ""),
    )


# ---------------------------------------------------------------------------
# Import labels from CSV / plain text
# ---------------------------------------------------------------------------

def import_labels(source_path: Path, column: int = 0, has_header: bool | None = None) -> list[str]:
    """
    Read labels from a CSV or plain-text file (one per row/line).
    Returns a list of non-empty strings. Source file is not modified.
    """
    raw = source_path.read_bytes()
    encoding = _detect_encoding(raw)
    text = raw.decode(encoding, errors="replace")

    suffix = source_path.suffix.lower()
    if suffix in (".csv", ".tsv"):
        return _read_csv_column(text, column, has_header)
    else:
        return _read_lines(text)


def _read_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _read_csv_column(text: str, column: int, has_header: bool | None) -> list[str]:
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return []

    # Auto-detect header: if any cell in row 0 looks like a header word
    _HEADER_WORDS = {"title", "name", "text", "label", "content", "desc", "description"}
    if has_header is None:
        first = {c.strip().lower() for c in rows[0]}
        has_header = bool(first & _HEADER_WORDS)

    start = 1 if has_header else 0
    labels = []
    for row in rows[start:]:
        if column < len(row):
            val = row[column].strip()
            if val:
                labels.append(val)
    return labels


def _detect_encoding(raw: bytes) -> str:
    if _HAS_CHARDET:
        result = chardet.detect(raw[:100_000])
        enc = result.get("encoding")
        if enc:
            return enc
    return "utf-8"


# ---------------------------------------------------------------------------
# Create a new project from imported labels
# ---------------------------------------------------------------------------

def project_from_labels(
    labels: list[str],
    name: str,
    output_dir: str,
    projects_dir: Path,
) -> tuple[Project, Path]:
    """
    Build a new Project from a list of labels and save it to disk.
    Returns (project, saved_path).
    """
    project = Project.new(name, output_dir)
    for label in labels:
        project.add_item(label)
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip()
    dest = projects_dir / f"{safe_name}.json"
    # Avoid clobbering existing files
    if dest.exists():
        stem = safe_name
        counter = 1
        while dest.exists():
            dest = projects_dir / f"{stem}_{counter}.json"
            counter += 1
    save_project(project, dest)
    return project, dest
