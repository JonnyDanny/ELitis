"""
Source image ingestion: atomic write → hash → commit.

Guarantees
----------
- No partial files: image bytes are written to an ``elitis_{rand8}.tmp`` buffer
  first.  Only after a successful hash and rename does the committed file appear.
- Sidecar written before image bytes so provenance survives a mid-write crash.
- Each acquisition gets its own committed pair even when the raw content is
  identical to an existing file — no provenance is discarded.
- Leftover ``elitis_*.tmp`` / ``elitis_*.json`` buffer files from crashed
  sessions are removed by ``cleanup_buffers()``.

Directory layout
----------------
Ingest/Sourced/
  elitis_{rand8}.json                    ← sidecar written first  (step 1)
  elitis_{rand8}.tmp                     ← image in-flight        (step 2)
        ↓ commit (hash + rename)
  {hash16}_{rand8}.{ext}                 ← final image            (step 4)
  {hash16}_{rand8}.json                  ← final sidecar          (step 5)
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".gif"}


def _hash16(path: Path) -> tuple[str, int, int]:
    """
    Return (hex16, width, height) for the image at *path*.

    Uses blake3 when available, falls back to sha256.  The hex string is
    truncated to 16 characters (64 bits) — sufficient for dedup in any
    realistic image library.
    """
    from PIL import Image as _Image

    raw = path.read_bytes()

    try:
        import blake3 as _b3
        digest = _b3.blake3(raw).hexdigest()[:16]
    except ImportError:
        digest = hashlib.sha256(raw).hexdigest()[:16]

    with _Image.open(path) as img:
        w, h = img.size

    return digest, w, h


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_sourced_image(
    data: bytes,
    original_name: str,
    dest_dir: Path,
    source_url: Optional[str] = None,
) -> Path:
    """
    Atomically write *data* to *dest_dir* and return the committed path.

    Steps
    -----
    1. Write sidecar ``elitis_{rand8}.json`` with pre-hash provenance.
    2. Write image bytes to ``elitis_{rand8}.tmp``.
    3. Hash the written file (blake3 or sha256 truncated to 16 hex chars).
    4. Rename image → ``{hash16}_{rand8}.{ext}``.
    5. Update sidecar with hash + dimensions, rename → same stem + ``.json``,
       remove the partial sidecar.

    Parameters
    ----------
    data          Raw image bytes (PNG, JPEG, etc.).
    original_name Filename as the user or browser supplied it — used for the
                  extension and recorded in the sidecar.
    dest_dir      Target directory (created if absent).
    source_url    URL the image was downloaded from, if known.

    Returns
    -------
    Path to the committed image file.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    rand8    = os.urandom(4).hex()
    buf_img  = dest_dir / f"elitis_{rand8}.tmp"
    buf_json = dest_dir / f"elitis_{rand8}.json"

    # Step 1 — write sidecar with what we know before touching image bytes
    acquired_at = datetime.now().isoformat(timespec="seconds")
    sidecar_partial: dict = {
        "acquired_at":      acquired_at,
        "source_url":       source_url,
        "original_filename": original_name,
    }
    buf_json.write_text(
        json.dumps(sidecar_partial, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Step 2 — write image bytes
    buf_img.write_bytes(data)

    # Step 3 — hash
    hash16, width, height = _hash16(buf_img)

    # Determine extension from original name; default to .png
    ext = Path(original_name).suffix.lower()
    if ext not in _IMAGE_EXTS:
        ext = ".png"

    # Step 4 — rename image to committed name
    final_stem = f"{hash16}_{rand8}"
    final_img  = dest_dir / f"{final_stem}{ext}"
    buf_img.rename(final_img)

    # Step 5 — update sidecar with hash + dims, rename, remove partial sidecar
    sidecar_full = {
        **sidecar_partial,
        "hash":   hash16,
        "width":  width,
        "height": height,
    }
    final_json = dest_dir / f"{final_stem}.json"
    final_json.write_text(
        json.dumps(sidecar_full, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    buf_json.unlink()

    return final_img


def fetch_url_bytes(url: str, timeout: int = 15) -> Optional[bytes]:
    """
    Fetch raw bytes from *url*.  Tries ``requests`` first, falls back to
    ``urllib.request``.  Returns ``None`` on any network or HTTP error.
    """
    try:
        import requests as _req
        r = _req.get(url, timeout=timeout)
        r.raise_for_status()
        return r.content
    except ImportError:
        pass
    except Exception:
        return None
    try:
        import urllib.request as _ur
        with _ur.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            return resp.read()
    except Exception:
        return None


def cleanup_buffers(dest_dir: Path) -> int:
    """
    Remove leftover ``elitis_*.tmp`` and ``elitis_*.json`` buffer files.

    Safe to call on app startup even when *dest_dir* does not yet exist.
    Returns the number of files removed.
    """
    if not dest_dir.exists():
        return 0
    removed = 0
    for pattern in ("elitis_*.tmp", "elitis_*.json"):
        for f in dest_dir.glob(pattern):
            f.unlink(missing_ok=True)
            removed += 1
    return removed
