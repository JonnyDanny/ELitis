"""
Project serialization (JSON) and label import (CSV / plain-text).

Design rules
------------
- Import always creates a new Project object; the source file is never modified.
- Projects are saved to Projects/<name>.json.
- Encoding detection uses chardet when available; falls back to UTF-8.
- Backward compatibility: the pre-0.2 field names ``use_phantom`` and ``is_phantom``
  are still accepted on load so old project files continue to work.
"""
from __future__ import annotations
from dataclasses import fields as dc_fields
from pathlib import Path
from typing import Optional
import json
import csv
import io
import hashlib
import zlib

from elitis.core.models import (
    Project, ThumbnailItem, ItemSettings, SF, FIELD_DEFAULTS, ImageHash
)

SAVE_VERSION = "0.2.0.pre"

try:
    import chardet
    _HAS_CHARDET = True
except ImportError:
    _HAS_CHARDET = False


# ---------------------------------------------------------------------------
# Image hash helpers
# ---------------------------------------------------------------------------

def compute_image_hash(path: str | Path) -> ImageHash:
    """
    Compute the integrity fingerprint for the image at *path*.

    Reads the raw file bytes once for all hash computations, then opens the
    image with PIL only to read the pixel dimensions.  Blake3 is used when
    the blake3 package is available; the field is None otherwise.
    """
    from PIL import Image as _Image

    raw = Path(path).read_bytes()

    sha256 = hashlib.sha256(raw).hexdigest()
    crc32  = format(zlib.crc32(raw) & 0xFFFFFFFF, "08x")

    try:
        import blake3 as _blake3
        b3: Optional[str] = _blake3.blake3(raw).hexdigest()
    except ImportError:
        b3 = None

    with _Image.open(path) as img:
        w, h = img.size

    return ImageHash(sha256=sha256, crc32=crc32, blake3=b3, width=w, height=h)


# Severity tokens returned by check_image_integrity
HASH_OK    = "ok"
HASH_WARN  = "warn"   # hash mismatch, resolution same  — benign metadata change
HASH_ERROR = "error"  # hash mismatch + resolution diff, or file missing


def check_image_integrity(item) -> tuple[str, str]:
    """
    Compare an item's stored ImageHash against the file on disk.

    Returns ``(severity, message)`` where severity is one of the HASH_*
    constants.  Returns HASH_OK immediately when no hash is stored (file was
    never fingerprinted) so callers don't need to special-case it.
    """
    if item.image_hash is None or not item.image_path:
        return HASH_OK, ""

    path = Path(item.image_path)
    if not path.exists():
        return HASH_ERROR, f"Image file not found: {path.name}"

    stored  = item.image_hash
    current = compute_image_hash(path)

    if current.sha256 == stored.sha256:
        return HASH_OK, ""

    if current.width == stored.width and current.height == stored.height:
        return HASH_WARN, (
            f"Image file changed (likely metadata rewrite) — "
            f"resolution {current.width}×{current.height} unchanged"
        )

    return HASH_ERROR, (
        f"Image file changed: resolution was {stored.width}×{stored.height}, "
        f"now {current.width}×{current.height}"
    )


def accept_image_hash(item) -> None:
    """
    Recompute and store the hash for item's current image, silencing any
    existing integrity warning.  No-op when image_path is None.
    """
    if item.image_path and Path(item.image_path).exists():
        item.image_hash = compute_image_hash(item.image_path)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _sf_to_dict(sf: SF) -> dict:
    """Serialise one SF to a JSON-compatible dict.  Tuples become lists for JSON."""
    v = sf.value
    if isinstance(v, tuple):
        v = list(v)
    return {"value": v, "use_default": sf.use_default}


def _sf_from_dict(d: dict, default_key: str) -> SF:
    """
    Deserialise one SF from a dict.

    JSON lists are converted back to tuples (e.g. colour triples).  Accepts both the
    current ``use_default`` key and the pre-0.2 ``use_phantom`` key.
    """
    v = d.get("value", FIELD_DEFAULTS.get(default_key))
    if isinstance(v, list):
        v = tuple(v)
    use_default = d.get("use_default", d.get("use_phantom", True))
    return SF(value=v, use_default=use_default)


def _settings_to_dict(s: ItemSettings) -> dict:
    """Serialise all SF fields of *s* to a plain dict."""
    return {f.name: _sf_to_dict(getattr(s, f.name)) for f in dc_fields(s)}


def _settings_from_dict(d: dict) -> ItemSettings:
    """
    Deserialise an ItemSettings from a dict.

    Unknown keys are ignored so forward-compatible project files don't crash on
    older code.  Missing keys are filled with the FIELD_DEFAULTS value.
    """
    s = ItemSettings()
    for f in dc_fields(s):
        if f.name in d:
            setattr(s, f.name, _sf_from_dict(d[f.name], f.name))
    return s


def _hash_to_dict(h: ImageHash) -> dict:
    return {"sha256": h.sha256, "crc32": h.crc32, "blake3": h.blake3,
            "width": h.width, "height": h.height}


def _hash_from_dict(d: dict) -> ImageHash:
    return ImageHash(
        sha256=d["sha256"], crc32=d["crc32"], blake3=d.get("blake3"),
        width=d["width"], height=d["height"],
    )


def _item_to_dict(item: ThumbnailItem) -> dict:
    """Serialise one ThumbnailItem to a JSON-compatible dict."""
    return {
        "id":         item.id,
        "label":      item.label,
        "image_path": item.image_path,
        "image_hash": _hash_to_dict(item.image_hash) if item.image_hash else None,
        "origin":     item.origin,
        "is_default": item.is_default,
        "settings":   _settings_to_dict(item.settings),
    }


def _item_from_dict(d: dict) -> ThumbnailItem:
    """
    Deserialise one ThumbnailItem from a dict.

    Accepts the pre-0.2 ``is_phantom`` key as an alias for ``is_default``.
    """
    is_default = d.get("is_default", d.get("is_phantom", False))
    raw_hash   = d.get("image_hash")
    return ThumbnailItem(
        id=d["id"],
        label=d.get("label", ""),
        image_path=d.get("image_path"),
        is_default=is_default,
        settings=_settings_from_dict(d.get("settings", {})),
        image_hash=_hash_from_dict(raw_hash) if raw_hash else None,
        origin=d.get("origin"),
    )


# ---------------------------------------------------------------------------
# Public save / load
# ---------------------------------------------------------------------------

def save_project(project: Project, path: Path):
    """
    Serialise *project* to a UTF-8 JSON file at *path*.

    Creates parent directories as needed.  Calls ``project.touch()`` to update the
    ``modified_at`` timestamp before writing.
    """
    project.touch()
    data = {
        "version": SAVE_VERSION,
        "name": project.name,
        "output_dir": project.output_dir,
        "created_at": project.created_at,
        "modified_at": project.modified_at,
        "items": [_item_to_dict(i) for i in project.items],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_project(path: Path) -> Project:
    """
    Load a project from a JSON file.

    If the first item in the file is not the defaults item (e.g. the file was
    edited by hand and the sentinel was removed), a fresh defaults item is
    inserted at position 0 so the invariant ``items[0].is_default`` always holds.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    items = [_item_from_dict(d) for d in data.get("items", [])]
    if not items or not items[0].is_default:
        items.insert(0, ThumbnailItem.make_defaults())
    return Project(
        name=data.get("name", path.stem),
        items=items,
        output_dir=data.get("output_dir", "Egest"),
        created_at=data.get("created_at", ""),
        modified_at=data.get("modified_at", ""),
    )


def save_version(path: Path) -> str:
    """
    Return the ``version`` string from a saved project file.

    Returns ``"0.1"`` for pre-versioned files (no ``version`` key) and
    ``"unknown"`` if the file cannot be read or parsed.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("version", "0.1")
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Import labels from CSV / plain text
# ---------------------------------------------------------------------------

def import_labels(source_path: Path, column: int = 0, has_header: bool | None = None) -> list[str]:
    """
    Read display labels from a CSV, TSV, or plain-text file.

    Plain-text files (not .csv/.tsv) are read one label per line.  CSV/TSV files
    read the given *column* (0-indexed).

    *has_header=None* triggers auto-detection: if any cell in the first row matches
    a common header word (title, name, label, etc.) the row is skipped.  Pass True
    or False to override.

    Returns a list of non-empty stripped strings.  The source file is never modified.
    """
    raw = source_path.read_bytes()
    encoding = _detect_encoding(raw)
    text = raw.decode(encoding, errors="replace")

    suffix = source_path.suffix.lower()
    if suffix in (".csv", ".tsv"):
        delimiter = "\t" if suffix == ".tsv" else ","
        return _read_csv_column(text, column, has_header, delimiter=delimiter)
    else:
        return _read_lines(text)


def _read_lines(text: str) -> list[str]:
    """Split *text* into non-empty stripped lines."""
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _read_csv_column(text: str, column: int, has_header: bool | None, delimiter: str = ",") -> list[str]:
    """
    Extract one column from CSV/TSV text and return non-empty cell values.

    *delimiter* should be ``","`` for CSV and ``"\\t"`` for TSV.  Auto-detects a
    header row by checking whether the first row contains any of a set of common
    header words.  Rows where *column* is out of bounds are skipped silently rather
    than raising IndexError.
    """
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return []

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
    """
    Detect the character encoding of *raw* bytes.

    Uses chardet when available (inspects the first 100 KB).  Falls back to UTF-8,
    which handles the vast majority of modern text files.
    """
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
    Build a new Project from a list of labels and immediately save it to disk.

    If a file named ``<name>.json`` already exists in *projects_dir* a numeric
    suffix is appended (``<name>_1.json``, ``<name>_2.json``, …) until an unused
    filename is found — existing projects are never overwritten.

    Returns ``(project, saved_path)``.
    """
    project = Project.new(name, output_dir)
    for label in labels:
        project.add_item(label)
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip()
    dest = projects_dir / f"{safe_name}.json"
    if dest.exists():
        stem = safe_name
        counter = 1
        while dest.exists():
            dest = projects_dir / f"{stem}_{counter}.json"
            counter += 1
    save_project(project, dest)
    return project, dest
