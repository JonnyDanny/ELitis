"""
Clipboard poisoner — manual test helper for the ELItis paste flow.

Puts one pathological payload at a time onto the system clipboard, waits for
you to click Paste in the running ELItis app, then moves on to the next case.

Usage:
    python tools/clipboard_poisoner.py

Keep ELItis open in another window.  After each prompt:
  - Press Enter to load the next payload and try pasting it.
  - Type 'skip' to skip a case.
  - Type 'quit' to exit early.

Each case states what you should observe in ELItis if the code handles it
correctly.  Note anything unexpected — those become new regression tests.
"""
from __future__ import annotations
import sys
import base64
import io
import textwrap
from pathlib import Path
from PIL import Image

# PySide6 must be importable; this script uses it to write the clipboard.
try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage, QClipboard
    from PySide6.QtCore import QMimeData, QUrl
except ImportError:
    sys.exit("PySide6 not found.  Run: pip install PySide6")

_app = QApplication.instance() or QApplication(sys.argv)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cb() -> QClipboard:
    return QApplication.clipboard()


def _set_text(text: str):
    _cb().setText(text)


def _set_qimage(width: int, height: int, fmt: QImage.Format, fill: int):
    img = QImage(width, height, fmt)
    img.fill(fill)
    _cb().setImage(img)


def _set_mime_text(text: str):
    """Puts text only via MimeData (same as _set_text, explicit path)."""
    md = QMimeData()
    md.setText(text)
    _cb().setMimeData(md)


def _make_png_b64(w: int, h: int, color=(128, 200, 50, 255)) -> str:
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), color).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _make_jpeg_b64(w: int, h: int, color=(128, 200, 50)) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

CASES: list[dict] = [

    # -----------------------------------------------------------------------
    # 1 — null clipboard
    # -----------------------------------------------------------------------
    {
        "name": "Empty clipboard",
        "description": "Clipboard is completely empty — no image, no text, no files.",
        "expect": "Status bar: 'Clipboard is empty or has no image'.  Returns False.",
        "setup": lambda: _cb().clear(),
    },

    # -----------------------------------------------------------------------
    # 2 — plain text
    # -----------------------------------------------------------------------
    {
        "name": "Plain text (no URL)",
        "description": "Clipboard contains 'S tier: Charizard, Blastoise'.",
        "expect": "Status bar: 'Clipboard has text, not image data'.  Returns False.",
        "setup": lambda: _set_text("S tier: Charizard, Blastoise"),
    },

    # -----------------------------------------------------------------------
    # 3 — HTTP URL as text
    # -----------------------------------------------------------------------
    {
        "name": "HTTP URL as plain text",
        "description": "Clipboard contains 'http://example.com/image.png' as text.",
        "expect": "Status bar: mentions URL, suggests saving locally.  Returns False.",
        "setup": lambda: _set_text("http://example.com/image.png"),
    },

    # -----------------------------------------------------------------------
    # 4 — HTTPS URL as text
    # -----------------------------------------------------------------------
    {
        "name": "HTTPS URL as plain text",
        "description": "Clipboard contains 'https://cdn.example.com/thumb.webp' as text.",
        "expect": "Status bar: mentions URL.  Returns False.",
        "setup": lambda: _set_text("https://cdn.example.com/thumb.webp"),
    },

    # -----------------------------------------------------------------------
    # 5 — valid small QImage (RGBA8888)
    # -----------------------------------------------------------------------
    {
        "name": "Valid QImage — 8×8 RGBA8888",
        "description": "Small solid-red image in the standard Qt clipboard format.",
        "expect": "Image assigned to current item.  Pasted file appears in Ingest/Pasted/.  No error.",
        "setup": lambda: _set_qimage(8, 8, QImage.Format.Format_RGBA8888, 0xFFFF0000),
    },

    # -----------------------------------------------------------------------
    # 6 — QImage in ARGB32 (the native Qt format, NOT pre-converted)
    # -----------------------------------------------------------------------
    {
        "name": "Valid QImage — ARGB32 (native Qt format)",
        "description": (
            "QImage in Format_ARGB32 — this is what real app pastes produce on Windows "
            "before our Format_RGBA8888 conversion.  Red pixel should stay red."
        ),
        "expect": "Image assigned.  Saved file is red, not blue — channels not swapped.",
        "setup": lambda: _set_qimage(8, 8, QImage.Format.Format_ARGB32, 0xFFFF0000),
    },

    # -----------------------------------------------------------------------
    # 7 — QImage in ARGB32_Premultiplied (Snipping Tool / screenshot format)
    # -----------------------------------------------------------------------
    {
        "name": "Valid QImage — ARGB32_Premultiplied (screenshot format)",
        "description": (
            "Format used by Windows Snipping Tool and screen-capture APIs.  "
            "Pre-multiplied alpha: R channel stored as R*alpha/255.  "
            "For opaque pixels (alpha=255) this equals the real value, so should be fine."
        ),
        "expect": "Image assigned.  Pixel colours correct (no washed-out whites).",
        "setup": lambda: _set_qimage(
            8, 8, QImage.Format.Format_ARGB32_Premultiplied, 0xFF3C78BE
        ),
    },

    # -----------------------------------------------------------------------
    # 8 — QImage with all-zero pixels (fully transparent)
    # -----------------------------------------------------------------------
    {
        "name": "Fully transparent QImage",
        "description": "All pixels have RGBA (0,0,0,0).  Should save as transparent PNG.",
        "expect": "Image assigned.  No crash.  Canvas shows the image (may look empty).",
        "setup": lambda: _set_qimage(16, 16, QImage.Format.Format_RGBA8888, 0x00000000),
    },

    # -----------------------------------------------------------------------
    # 9 — valid base64 PNG data URL
    # -----------------------------------------------------------------------
    {
        "name": "Base64 PNG data URL (small)",
        "description": "Clipboard text is 'data:image/png;base64,...' — a 32×32 green image.",
        "expect": "Image decoded and assigned.  Status: 'Pasted image saved: ...'.",
        "setup": lambda: _set_text(f"data:image/png;base64,{_make_png_b64(32, 32)}"),
    },

    # -----------------------------------------------------------------------
    # 10 — base64 JPEG data URL
    # -----------------------------------------------------------------------
    {
        "name": "Base64 JPEG data URL",
        "description": "Clipboard text is 'data:image/jpeg;base64,...' — a 32×32 JPEG.",
        "expect": "Image decoded, converted to RGBA, assigned.  No crash.",
        "setup": lambda: _set_text(f"data:image/jpeg;base64,{_make_jpeg_b64(32, 32)}"),
    },

    # -----------------------------------------------------------------------
    # 11 — base64 with leading/trailing whitespace
    # -----------------------------------------------------------------------
    {
        "name": "Base64 PNG data URL with surrounding whitespace",
        "description": "data URL preceded by two spaces and followed by a newline.",
        "expect": "Whitespace stripped; image decoded and assigned correctly.",
        "setup": lambda: _set_text(
            f"  data:image/png;base64,{_make_png_b64(8, 8)}\n"
        ),
    },

    # -----------------------------------------------------------------------
    # 12 — truncated base64 (cut off halfway)
    # -----------------------------------------------------------------------
    {
        "name": "Truncated base64 payload",
        "description": "Valid prefix 'data:image/png;base64,' but the base64 string is cut in half.",
        "expect": "Returns False.  Status bar: mentions decoding failure.  No crash.",
        "setup": lambda: _set_text(
            "data:image/png;base64," + _make_png_b64(16, 16)[:20]
        ),
    },

    # -----------------------------------------------------------------------
    # 13 — base64 with valid encoding of non-image bytes
    # -----------------------------------------------------------------------
    {
        "name": "Base64 of random non-image bytes",
        "description": "data:image/png;base64,... but the bytes are random garbage, not a PNG.",
        "expect": "Returns False.  Status bar: decoding failure message.  No crash.",
        "setup": lambda: _set_text(
            "data:image/png;base64," + base64.b64encode(b"\x00\x01\x02" * 200).decode()
        ),
    },

    # -----------------------------------------------------------------------
    # 14 — data URL with non-image MIME type
    # -----------------------------------------------------------------------
    {
        "name": "data:text/plain;base64,... (not an image)",
        "description": "Looks like a data URL but MIME type is text/plain.",
        "expect": "Classified as 'text', not 'base64'.  Status: text-not-image message.",
        "setup": lambda: _set_text(
            "data:text/plain;base64," + base64.b64encode(b"hello world").decode()
        ),
    },

    # -----------------------------------------------------------------------
    # 15 — unencoded SVG data URL (no ;base64, marker)
    # -----------------------------------------------------------------------
    {
        "name": "Unencoded SVG data URL",
        "description": "'data:image/svg+xml,<svg></svg>' — image MIME but no base64 encoding.",
        "expect": "Classified as 'text'.  Status: text-not-image message.  No decode attempt.",
        "setup": lambda: _set_text("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg'/>"),
    },

    # -----------------------------------------------------------------------
    # 16 — oversized QImage (memory stress)
    # -----------------------------------------------------------------------
    {
        "name": "Large QImage — 3840×2160 (4K)",
        "description": "A full 4K frame put on the clipboard.",
        "expect": "Image saved without crash or out-of-memory error.  May be slow.",
        "setup": lambda: _set_qimage(
            3840, 2160, QImage.Format.Format_RGBA8888, 0xFF007FFF
        ),
    },

    # -----------------------------------------------------------------------
    # 17 — 1×1 pixel image
    # -----------------------------------------------------------------------
    {
        "name": "1×1 pixel QImage",
        "description": "The smallest possible valid image.",
        "expect": "Image assigned.  Canvas shows checkerboard with tiny image overlay.",
        "setup": lambda: _set_qimage(1, 1, QImage.Format.Format_RGBA8888, 0xFF00FF00),
    },

    # -----------------------------------------------------------------------
    # 18 — local image file URL (Explorer copy)
    # -----------------------------------------------------------------------
    {
        "name": "Local image file URL (simulated Explorer copy)",
        "description": (
            "MimeData contains a file:/// URL pointing to a real PNG on disk.  "
            "This is what Windows Explorer puts on the clipboard when you Ctrl+C a file."
        ),
        "expect": (
            "Classified as 'files'.  Status: 'use Open image' message naming the file.  "
            "Returns False — the file is NOT opened automatically."
        ),
        "setup": lambda: (
            lambda md: (
                md.setUrls(
                    [QUrl.fromLocalFile(
                        str(Path(__file__).parent.parent / "Fonts" / next(
                            (Path(__file__).parent.parent / "Fonts").rglob("*.ttf"),
                            Path(__file__).parent.parent / "pyproject.toml"
                        ))
                    )]
                ),
                _cb().setMimeData(md),
            )
        )(QMimeData()),
    },

    # -----------------------------------------------------------------------
    # 19 — local non-image file URL
    # -----------------------------------------------------------------------
    {
        "name": "Local non-image file URL (e.g. a .toml file)",
        "description": "MimeData contains a file:/// URL to a .toml file (not an image).",
        "expect": "Classified as 'files'.  Status: 'none are images' message.  Returns False.",
        "setup": lambda: (
            lambda md: (
                md.setUrls([QUrl.fromLocalFile(
                    str(next(Path(__file__).parent.parent.glob("*.toml"),
                             Path(__file__).parent.parent / "README.md"))
                )]),
                _cb().setMimeData(md),
            )
        )(QMimeData()),
    },

    # -----------------------------------------------------------------------
    # 20 — remote URL in url list (browser drag)
    # -----------------------------------------------------------------------
    {
        "name": "Remote URL in url list (browser drag simulation)",
        "description": "MimeData contains a non-local QUrl (https://...) in the urls list.",
        "expect": "Classified as 'url'.  Status: save locally first.  Returns False.",
        "setup": lambda: (
            lambda md: (
                md.setUrls([QUrl("https://example.com/photo.jpg")]),
                _cb().setMimeData(md),
            )
        )(QMimeData()),
    },
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _divider():
    print("\n" + "─" * 60)


def main():
    print(textwrap.dedent("""
    ╔══════════════════════════════════════════════════════════╗
    ║           ELItis clipboard poisoner                      ║
    ║  Keep ELItis open.  Press Enter to load each payload,   ║
    ║  then click Paste (or use the keyboard shortcut).        ║
    ║  Type 'skip' to skip, 'quit' to exit.                   ║
    ╚══════════════════════════════════════════════════════════╝
    """))

    passed = skipped = 0

    for i, case in enumerate(CASES, start=1):
        _divider()
        print(f"[{i}/{len(CASES)}]  {case['name']}")
        print(f"  What:   {case['description']}")
        print(f"  Expect: {case['expect']}")

        cmd = input("\n  Enter = load payload, 'skip' = skip, 'quit' = exit: ").strip().lower()
        if cmd == "quit":
            break
        if cmd == "skip":
            skipped += 1
            print("  → Skipped.")
            continue

        try:
            case["setup"]()
            print("  → Payload on clipboard.  Click Paste now.")
        except Exception as exc:
            print(f"  ✗  Setup failed: {exc}")
            continue

        result = input("  Result OK? [y/n/notes]: ").strip()
        if result.lower().startswith("y") or result == "":
            passed += 1
            print("  ✓")
        else:
            print(f"  ✗  NOTED: {result}")

    _divider()
    print(f"\nDone.  {passed} OK  |  {skipped} skipped  |  {len(CASES)-passed-skipped} issues\n")


if __name__ == "__main__":
    main()
