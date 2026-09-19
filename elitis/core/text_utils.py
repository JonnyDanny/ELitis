"""
Label normalization utilities.

Normalization stack, applied in order:
  1. Unicode NFC — precomposed vs combining chars (silent)
  2. Strip invisible/zero-width chars (silent)
  3. Normalize line endings: \\r\\n, \\r → \\n (silent)
  4. Whitespace: strip leading/trailing, collapse runs to single space
  5. Case-dictionary lookup — user-maintained canonical forms

Steps 1-4 are always applied; step 5 requires a case_dict.
The stored label always uses the post-normalization form, never the
lowercase comparison key.  comparison_key() is used only for dedup.

Case dictionary file:  <project_dir>/case_corrections.json
  {"pikachu": "Pikachu", "jon smith": "Jon Smith", ...}
  Keys are lowercase stems; values are the canonical display forms.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

# Zero-width and invisible characters that appear in pasted text
_INVISIBLE = re.compile(
    r"[­"          # soft hyphen
    r"​-‏"    # zero-width space, ZWNJ, ZWJ, LRM, RLM
    r"  "     # line/paragraph separator
    r"﻿]"          # BOM / zero-width no-break space
)

_MULTI_WS = re.compile(r"[ \t]{2,}")


def normalize_label(
    text: str,
    case_dict: dict[str, str] | None = None,
) -> tuple[str, list[str]]:
    """
    Normalize *text* for storage.

    Returns ``(normalized_text, changes)`` where *changes* is a list of
    short tokens describing what was altered (empty when already clean):

    ``"unicode_nfc"``     — precomposed/decomposed form unified
    ``"invisible_chars"`` — zero-width or soft-hyphen chars removed
    ``"line_endings"``    — \\r\\n or bare \\r replaced with \\n
    ``"whitespace"``      — leading/trailing stripped or runs collapsed
    ``"case_dict"``       — canonical form applied from case dictionary
    """
    changes: list[str] = []

    # 1. Unicode NFC
    nfc = unicodedata.normalize("NFC", text)
    if nfc != text:
        text = nfc
        changes.append("unicode_nfc")

    # 2. Invisible / zero-width chars
    cleaned = _INVISIBLE.sub("", text)
    if cleaned != text:
        text = cleaned
        changes.append("invisible_chars")

    # 3. Line endings
    le_norm = text.replace("\r\n", "\n").replace("\r", "\n")
    if le_norm != text:
        text = le_norm
        changes.append("line_endings")

    # 4. Whitespace collapse
    ws_norm = _MULTI_WS.sub(" ", text).strip()
    if ws_norm != text:
        text = ws_norm
        changes.append("whitespace")

    # 5. Case dictionary
    if case_dict:
        canonical = case_dict.get(text.lower()) or case_dict.get(text)
        if canonical and canonical != text:
            text = canonical
            changes.append("case_dict")

    return text, changes


def comparison_key(text: str) -> str:
    """
    Lowercase comparison key for dedup — never stored, never displayed.

    Applies steps 1-4 of normalize_label (no case dict), then lowercases.
    Two labels with the same key are treated as duplicates or case conflicts
    depending on whether their normalized forms also match.
    """
    normalized, _ = normalize_label(text)
    return normalized.lower()


# ---------------------------------------------------------------------------
# Case dictionary persistence
# ---------------------------------------------------------------------------

def load_case_dict(path: str | Path) -> dict[str, str]:
    """
    Load case corrections from *path*.  Returns an empty dict when the file
    does not exist (first-use case; the file is created on the first save).
    """
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_case_dict(path: str | Path, case_dict: dict[str, str]) -> None:
    """
    Persist *case_dict* to *path* as sorted, human-readable JSON.

    Keys are stored lowercase; values are the canonical display forms.
    Parent directories are created as needed.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(dict(sorted(case_dict.items())), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def add_case_correction(
    path: str | Path,
    canonical: str,
) -> dict[str, str]:
    """
    Register *canonical* as the authoritative form for its lowercase key.

    Loads the existing dict, adds/overwrites the entry, saves, and returns
    the updated dict.  The key stored is ``canonical.lower()``.
    """
    case_dict = load_case_dict(path)
    case_dict[canonical.lower()] = canonical
    save_case_dict(path, case_dict)
    return case_dict
