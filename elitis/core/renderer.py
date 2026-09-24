"""
Pure Pillow rendering — no Qt imports.

render_thumbnail() is the single public entry point used by both the GUI preview
worker (called in a background thread) and the CLI/batch export pipeline.
All drawing logic lives here so preview and export are always bit-for-bit identical.

Pipeline for one item
---------------------
1. Load background image (or fall back to a grey checkerboard if absent/corrupt).
2. Apply image framing: crop the source region, then scale/letterbox it to the canvas.
3. Composite the semi-transparent box overlay.
4. Draw text with optional outline and shadow on a separate RGBA layer, then alpha-
   composite that layer onto the image so the text never clips the background.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
import textwrap
import io

from PIL import Image, ImageDraw, ImageFilter
from PIL.PngImagePlugin import PngInfo

from elitis.core.models import ResolvedSettings, ThumbnailItem, Project, RenderWarning
from elitis.core.font_manager import FontManager


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_thumbnail(
    item: ThumbnailItem,
    project: Project,
    font_manager: FontManager,
    preview_size: Optional[tuple[int, int]] = None,
) -> Image.Image:
    """
    Render one thumbnail and return a Pillow RGBA Image.

    If *preview_size* is given the output is proportionally scaled to fit within
    that box (used for live preview — much faster than full-res on every keystroke).
    The full-res path is taken when *preview_size* is None.

    This function never raises for bad image paths; it silently falls back to a
    checkerboard so the UI stays responsive and partial projects are still usable.
    """
    cfg = project.resolve_item(item)
    bg = _load_background(item, project, cfg)
    bg = _apply_framing(bg, cfg)
    bg = _composite_box(bg, cfg)
    if item.label:
        bg = _draw_text(bg, item.label, cfg, font_manager)
    if preview_size:
        bg = _fit_to_preview(bg, preview_size)
    return bg


def check_source_resolution(path_str: str, cfg: ResolvedSettings) -> str | None:
    """
    Return a human-readable warning when the source image is much smaller than
    the output canvas, or ``None`` when the resolution is adequate.

    "Much smaller" is defined as either dimension being less than half the
    corresponding canvas dimension — at that ratio LANCZOS upscaling produces
    visibly blurry results.  This is informational; the render still proceeds
    normally.

    Returns ``None`` without opening the file when *path_str* is empty.
    Silently returns ``None`` if the file cannot be opened.
    """
    if not path_str:
        return None
    try:
        with Image.open(path_str) as img:
            iw, ih = img.size
    except Exception:
        return None
    cw, ch = cfg.canvas_width, cfg.canvas_height
    if iw * 2 < cw or ih * 2 < ch:
        return (
            f"Source image ({iw}×{ih} px) is much smaller than the canvas "
            f"({cw}×{ch} px) — upscaling may cause visible blurring."
        )
    return None


def check_text_fit(
    item: ThumbnailItem,
    project: Project,
    font_manager: FontManager,
) -> list[RenderWarning]:
    """
    Dry-run the text layout for *item* and return any fit warnings.

    Runs the same layout logic as render_thumbnail but without actually drawing
    anything, so it is safe to call on all items after a tune step without
    triggering a full re-render.  Returns an empty list when the label is empty
    or all checks pass.

    Checks performed (in order):
      text_word_too_wide  — a single word is wider than the text area at min size
      text_truncated      — text still overflows after reaching minimum font size
      text_overflow       — rendered text block extends outside canvas bounds
      text_ragged         — multi-line: line 2+ uses <60% of line 1 width
      text_underutilized  — all lines use <40% of available text width
    """
    cfg  = project.resolve_item(item)
    text = _apply_transform(item.label or "", cfg.text_transform)
    if not text.strip():
        return []

    pad      = cfg.box_padding
    usable_w = cfg.canvas_width - pad * 2
    warnings: list[RenderWarning] = []

    dummy    = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    min_font = font_manager.get_pil_font(cfg.font_name, cfg.font_min_size)

    # -- text_word_too_wide: any word wider than the text area at min size ----
    for word in text.split():
        bb = dummy.textbbox((0, 0), word, font=min_font)
        if bb[2] - bb[0] > usable_w:
            warnings.append(RenderWarning(
                item_id=item.id, severity="error",
                code="text_word_too_wide",
                message=(
                    f"Word '{word}' is wider than the text area at minimum "
                    f"font size ({cfg.font_min_size}px)"
                ),
            ))
            break

    # -- run the actual layout the renderer would use -------------------------
    font, lines = _fit_text(
        text, usable_w,
        cfg.font_name, cfg.font_size, cfg.font_min_size,
        cfg.font_max_lines, cfg.font_auto_size, font_manager,
    )

    # -- text_truncated: hit min_size AND lines were still cut ----------------
    if cfg.font_auto_size and font.size <= cfg.font_min_size:
        full_lines = _wrap_text(text, min_font, usable_w)
        cut = len(full_lines) - cfg.font_max_lines
        if cut > 0:
            warnings.append(RenderWarning(
                item_id=item.id, severity="error",
                code="text_truncated",
                message=(
                    f"Text still overflows after reaching minimum font size "
                    f"({cfg.font_min_size}px) -- {cut} line(s) cut"
                ),
            ))

    # -- measure the laid-out lines -------------------------------------------
    line_bboxes  = [dummy.textbbox((0, 0), ln, font=font) for ln in lines]
    line_heights = [bb[3] - bb[1] for bb in line_bboxes]
    line_widths  = [bb[2] - bb[0] for bb in line_bboxes]
    spacing  = max(4, int(font.size * 0.15))
    total_h  = sum(line_heights) + spacing * max(0, len(lines) - 1)

    # -- text_overflow: block outside canvas ----------------------------------
    cy         = int(cfg.canvas_height * cfg.text_y)
    block_top  = cy - total_h // 2
    block_bot  = block_top + total_h
    if block_top < 0 or block_bot > cfg.canvas_height:
        edge = f"top={block_top}px" if block_top < 0 else f"bottom={block_bot}px"
        warnings.append(RenderWarning(
            item_id=item.id, severity="error",
            code="text_overflow",
            message=f"Text block extends outside canvas bounds ({edge})",
        ))

    if line_widths:
        max_lw = max(line_widths)

        # -- text_underutilized: <40% of usable width -------------------------
        if max_lw < usable_w * 0.4:
            pct = max_lw * 100 // usable_w
            warnings.append(RenderWarning(
                item_id=item.id, severity="warn",
                code="text_underutilized",
                message=f"Text uses only {pct}% of available width",
            ))

        # -- text_ragged: multi-line with short trailing lines ----------------
        if len(lines) > 1 and line_widths[0] > usable_w * 0.8:
            for i, lw in enumerate(line_widths[1:], 1):
                if lw < line_widths[0] * 0.6:
                    pct = lw * 100 // max(line_widths[0], 1)
                    warnings.append(RenderWarning(
                        item_id=item.id, severity="warn",
                        code="text_ragged",
                        message=(
                            f"Multi-line text: line {i + 1} uses only {pct}% "
                            "of line 1 width -- consider rewording"
                        ),
                    ))
                    break

    return warnings


def preflight_render(
    project: Project,
    fmt: str = "PNG",
    numbered: bool = True,
) -> list[RenderWarning]:
    """
    Return filename-level warnings without rendering anything.

    Runs the same stem-assignment and collision detection that ``render_all``
    would use, so callers can surface problems (duplicate stems, missing images)
    before committing to a full render pass.

    Useful in the CLI to print warnings and let the user abort before spending
    time on a large batch.  The GUI can call this when the user opens the batch
    export dialog to show a pre-flight summary.
    """
    from collections import Counter as _Counter
    items    = project.content_items
    ext      = "jpg" if fmt.upper() == "JPEG" else fmt.lower()
    warnings: list[RenderWarning] = []

    _prefix_overhead = 4 if numbered else 0
    _ext_overhead    = 1 + len(ext)
    _gen_budget      = max(20, 60 - _prefix_overhead - _ext_overhead - 2)
    _raw_check       = [_safe_filename(it.label or it.id, max_len=_gen_budget) for it in items]
    _max_n           = max((n for n in _Counter(_raw_check).values() if n > 1), default=1)
    _postfix_reserve = len(f"_{_max_n}")
    _stem_budget     = max(20, 60 - _prefix_overhead - _ext_overhead - _postfix_reserve)
    _assign_stems(items, warnings, max_stem=_stem_budget)

    for item in items:
        if not item.effective_image(project.defaults):
            warnings.append(RenderWarning(
                item_id=item.id, severity="error",
                code="image_missing",
                message="No image assigned — will render as checkerboard",
            ))

    return warnings


def render_all(
    project: Project,
    font_manager: FontManager,
    output_dir: Path,
    fmt: str = "PNG",
    on_progress=None,
    numbered: bool = True,
) -> tuple[list[Path], list[RenderWarning]]:
    """
    Batch-render every content item to *output_dir*.

    Returns ``(saved_paths, warnings)`` where *warnings* is the combined list
    from ``check_text_fit()`` for all items.  Items with no image are rendered
    as a grey checkerboard and an ``image_missing`` warning is added.

    *on_progress(done, total, path)* is called after each file is written.
    Pass None to skip it.

    When *numbered* is True (default) output filenames are ``NNN_stem.ext``,
    NNN zero-padded to three digits.  When False the prefix is omitted and
    stem uniqueness is the only guarantee against collisions — colliding stems
    receive a ``_2`` / ``_3`` postfix automatically.

    JPEG output is converted to RGB before saving.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    saved:    list[Path]          = []
    warnings: list[RenderWarning] = []
    items = project.content_items

    # Resolve stems once for the whole batch; emits filename_collision warnings.
    # stem budget = 60 (target) minus fixed overhead so the full filename
    # stays within that target:
    #   numbered prefix  "NNN_"   = 4 chars
    #   collision postfix "_NN"   = up to 3 chars  (counted in _assign_stems)
    #   extension        ".ext"   = 2–5 chars
    # All three are well within 255 (NTFS/ext4 limit) even without adjustment,
    # but the explicit budget keeps filenames predictably short.
    from collections import Counter as _Counter
    ext = "jpg" if fmt.upper() == "JPEG" else fmt.lower()
    _prefix_overhead = 4 if numbered else 0        # "NNN_"
    _ext_overhead    = 1 + len(ext)                # ".ext"
    # Dynamic postfix reserve: count actual max collision depth so "_N" always fits.
    # Quick pass at generous budget (reserve=2) to find max_n; then recompute.
    _gen_budget  = max(20, 60 - _prefix_overhead - _ext_overhead - 2)
    _raw_check   = [_safe_filename(it.label or it.id, max_len=_gen_budget) for it in items]
    _max_n       = max((n for n in _Counter(_raw_check).values() if n > 1), default=1)
    _postfix_reserve = len(f"_{_max_n}")           # 2 for ≤9, 3 for ≤99, 4 for ≤999, …
    _stem_budget     = max(20, 60 - _prefix_overhead - _ext_overhead - _postfix_reserve)
    stems = _assign_stems(items, warnings, max_stem=_stem_budget)

    for i, (item, stem) in enumerate(zip(items, stems)):
        item_warnings: list[RenderWarning] = []

        if not item.effective_image(project.defaults):
            item_warnings.append(RenderWarning(
                item_id=item.id, severity="error",
                code="image_missing",
                message=f"No image assigned — rendered as checkerboard",
            ))

        item_warnings.extend(check_text_fit(item, project, font_manager))
        warnings.extend(item_warnings)

        img      = render_thumbnail(item, project, font_manager)
        filename = f"{i:03d}_{stem}.{ext}" if numbered else f"{stem}.{ext}"
        dest     = output_dir / filename

        # Delete the previous output file if the filename changed (label rename,
        # collision resolution shift, format change, etc.).
        if item.last_output_path:
            old = Path(item.last_output_path)
            if old != dest and old.exists():
                try:
                    old.unlink()
                except OSError:
                    pass

        if fmt.upper() == "JPEG":
            img = img.convert("RGB")
            img.save(str(dest), format=fmt)
        elif fmt.upper() == "PNG":
            img.save(str(dest), format=fmt,
                     pnginfo=_build_png_meta(item, project, item_warnings))
        else:
            img.save(str(dest), format=fmt)

        item.last_output_path = str(dest)
        saved.append(dest)
        if on_progress:
            on_progress(i + 1, len(items), dest)

    return saved, warnings


# ---------------------------------------------------------------------------
# PNG metadata
# ---------------------------------------------------------------------------

def _build_png_meta(
    item: ThumbnailItem,
    project: Project,
    item_warnings: list[RenderWarning],
) -> PngInfo:
    """Embed ELItis generation metadata in a PNG tEXt chunk (key: ``elitis``)."""
    import json as _json
    from dataclasses import fields as _dc_fields
    from datetime import datetime as _dt

    try:
        from importlib.metadata import version as _pkg_version
        _version = _pkg_version("elitis")
    except Exception:
        _version = "0.2.0.dev"

    cfg = project.resolve_item(item)
    settings_dict: dict = {}
    for f in _dc_fields(cfg):
        v = getattr(cfg, f.name)
        settings_dict[f.name] = list(v) if isinstance(v, tuple) else v

    payload = {
        "version":     _version,
        "rendered_at": _dt.now().isoformat(timespec="seconds"),
        "project":     project.name,
        "item_id":     item.id,
        "label":       item.label,
        "image_path":  item.image_path,
        "image_hash":  item.image_hash.sha256[:16] if item.image_hash else None,
        "settings":    settings_dict,
        "warnings": [
            {"code": w.code, "severity": w.severity, "message": w.message}
            for w in item_warnings
        ],
    }

    meta = PngInfo()
    meta.add_text("elitis", _json.dumps(payload, ensure_ascii=False))
    return meta


# ---------------------------------------------------------------------------
# Color suggestion stubs
# Connection points for future image-based or AI-driven palette tools.
# Not implemented — raise NotImplementedError.
# ---------------------------------------------------------------------------

def _suggest_text_color(image: Image.Image) -> tuple:
    # FUTURE: analyse dominant/average image colours and return a contrasting
    # text colour as an (R, G, B) tuple.
    raise NotImplementedError

def _suggest_box_color(image: Image.Image) -> tuple:
    # FUTURE: suggest a complementary or neutral overlay box colour
    # derived from the image palette.
    raise NotImplementedError

def _suggest_box_opacity(image: Image.Image) -> int:
    # FUTURE: suggest an overlay opacity (0-255) based on the visual busyness
    # of the image region where the box will be placed.
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_background(item: ThumbnailItem, project: Project, cfg: ResolvedSettings) -> Image.Image:
    """
    Open the item's image file as RGBA, or return a grey checkerboard on failure.

    The checkerboard is intentional: it signals "no image" visually without crashing
    the render pipeline.  Failures (missing file, corrupt data, unsupported format)
    are silently swallowed here because rendering should always succeed.
    """
    path_str = item.effective_image(project.defaults)
    if path_str:
        try:
            return Image.open(path_str).convert("RGBA")
        except Exception:
            pass   # fall through to checkerboard
    return _checkerboard(cfg.canvas_width, cfg.canvas_height)


def _apply_framing(img: Image.Image, cfg: ResolvedSettings) -> Image.Image:
    """
    Resize and position the source image onto the output canvas.

    Two-step pipeline
    -----------------
    Step 1 — crop to the selected region (``fill`` and ``zoom`` modes only).
    Step 2 — apply the fit mode to produce an image of exactly (canvas_width, canvas_height).

    Modes
    -----
    fill    — the crop rect is AR-locked to the output canvas (enforced by FramingCanvas);
              the cropped region is stretched to fill with no letterbox bars.
    zoom    — freehand crop rect; the cropped region is letterboxed to fit.
    fit     — whole source image, letterboxed to fit (no crop step).
    stretch — whole source image stretched to fill, ignoring aspect ratio.
    center  — whole source image at native resolution, centered; edges may be clipped.
    """
    W, H = cfg.canvas_width, cfg.canvas_height
    fit = cfg.image_fit

    # Step 1 — apply crop rect for fill/zoom (skip if it covers the whole image)
    cx, cy, cw, ch = cfg.crop_x, cfg.crop_y, cfg.crop_w, cfg.crop_h
    if fit in ('fill', 'zoom') and not (cx == 0 and cy == 0 and cw == 1 and ch == 1):
        iw, ih = img.size
        px = int(cx * iw)
        py = int(cy * ih)
        pw = max(1, int(cw * iw))
        ph = max(1, int(ch * ih))
        img = img.crop((px, py, px + pw, py + ph))

    iw, ih = img.size

    # Step 2 — fit mode
    if fit == 'fill':
        # Crop is AR-matched to canvas; stretch fills without letterbox.
        return img.resize((W, H), Image.Resampling.LANCZOS)

    if fit == 'zoom':
        # Freehand crop; scale the cropped region to fit within the canvas.
        scale = min(W / iw, H / ih)
        nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        canvas.paste(img, ((W - nw) // 2, (H - nh) // 2))
        return canvas

    if fit == 'stretch':
        return img.resize((W, H), Image.Resampling.LANCZOS)

    if fit == 'fit':
        # Whole image, letterboxed.
        scale = min(W / iw, H / ih)
        nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        canvas.paste(img, ((W - nw) // 2, (H - nh) // 2))
        return canvas

    # center — native resolution, centered; edges clip when image is larger than canvas
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    ox = max(0, (W - iw) // 2)
    oy = max(0, (H - ih) // 2)
    sx = max(0, (iw - W) // 2)
    sy = max(0, (ih - H) // 2)
    paste_w = min(iw - sx, W - ox)
    paste_h = min(ih - sy, H - oy)
    canvas.paste(img.crop((sx, sy, sx + paste_w, sy + paste_h)), (ox, oy))
    return canvas


def _composite_box(img: Image.Image, cfg: ResolvedSettings) -> Image.Image:
    """
    Draw a semi-transparent colour bar (bottom, top, or full canvas) over the image.

    The overlay is composited as a separate RGBA layer so the box opacity is applied
    uniformly — it doesn't interact with any transparency already in the background.
    Returns the input unchanged if ``box_enabled`` is False.
    """
    if not cfg.box_enabled:
        return img
    W, H = img.size
    box_h = int(H * cfg.box_height)
    r, g, b = cfg.box_color
    a = cfg.box_opacity
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    if cfg.box_position == "bottom":
        draw.rectangle((0, H - box_h, W, H), fill=(r, g, b, a))
    elif cfg.box_position == "top":
        draw.rectangle((0, 0, W, box_h), fill=(r, g, b, a))
    else:  # full
        draw.rectangle((0, 0, W, H), fill=(r, g, b, a))
    return Image.alpha_composite(img, overlay)


def _draw_text(img: Image.Image, label: str, cfg: ResolvedSettings, font_manager: FontManager) -> Image.Image:
    """
    Render label text onto a blank RGBA layer, then alpha-composite it onto *img*.

    Draws (in order) shadow → outline → fill, so the shadow is always behind the
    outline and the outline is always behind the fill.  The separate layer ensures
    the text opacity setting applies uniformly to the whole text block.
    """
    W, H = img.size
    text = _apply_transform(label, cfg.text_transform)
    pad = cfg.box_padding

    usable_w = W - pad * 2

    font, lines = _fit_text(
        text, usable_w,
        cfg.font_name, cfg.font_size, cfg.font_min_size,
        cfg.font_max_lines, cfg.font_auto_size,
        font_manager,
    )

    # Measure total text block height and max line width
    draw_tmp = ImageDraw.Draw(img.copy())
    line_bboxes = [draw_tmp.textbbox((0, 0), ln, font=font) for ln in lines]
    line_heights = [bb[3] - bb[1] for bb in line_bboxes]
    line_widths  = [bb[2] - bb[0] for bb in line_bboxes]
    spacing = max(4, int(font.size * 0.15))
    total_h = sum(line_heights) + spacing * (len(lines) - 1)
    max_w = max(line_widths) if line_widths else 0

    # text_x/text_y are normalised canvas fractions; the anchor is the block center
    cx = int(W * cfg.text_x)
    cy = int(H * cfg.text_y)
    block_top = cy - total_h // 2

    text_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(text_layer)

    tr, tg, tb = cfg.text_color
    ta = cfg.text_opacity

    y_cursor = block_top
    for ln, lh, lw in zip(lines, line_heights, line_widths):
        if cfg.text_align == "left":
            x = cx - max_w // 2
        elif cfg.text_align == "right":
            x = cx + max_w // 2 - lw
        else:
            x = cx - lw // 2

        if cfg.shadow_enabled:
            sx, sy = cfg.shadow_offset_x, cfg.shadow_offset_y
            sr, sg, sb = cfg.shadow_color
            _draw_shadow(text_layer, d, ln, x, y_cursor, font, (sr, sg, sb, ta), sx, sy, cfg.shadow_blur)

        if cfg.outline_enabled:
            ow = cfg.outline_width
            or_, og, ob = cfg.outline_color
            for dx in range(-ow, ow + 1):
                for dy in range(-ow, ow + 1):
                    if dx == 0 and dy == 0:
                        continue
                    if abs(dx) + abs(dy) > ow + 1:
                        continue
                    d.text((x + dx, y_cursor + dy), ln, font=font, fill=(or_, og, ob, ta))

        d.text((x, y_cursor), ln, font=font, fill=(tr, tg, tb, ta))
        y_cursor += lh + spacing

    return Image.alpha_composite(img, text_layer)


def _draw_shadow(
    layer: Image.Image,
    draw: ImageDraw.Draw,
    text: str,
    x: int,
    y: int,
    font,
    color: tuple,
    ox: int,
    oy: int,
    blur: int,
) -> None:
    """
    Draw a (optionally blurred) drop shadow for *text* at (*x*+*ox*, *y*+*oy*).

    When *blur* is zero the shadow is drawn directly with the provided *draw* object.
    When *blur* > 0 the shadow is rendered onto a small scratch image, blurred with a
    Gaussian kernel, and pasted onto *layer* — the explicit *layer* argument replaces
    the old ``draw._image`` private-attribute access.
    """
    if blur <= 0:
        draw.text((x + ox, y + oy), text, font=font, fill=color)
        return
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    margin = blur * 2
    shadow_img = Image.new("RGBA", (tw + margin * 2, th + margin * 2), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow_img)
    sd.text((margin, margin), text, font=font, fill=color)
    shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(radius=blur))
    layer.paste(shadow_img, (x + ox - margin, y + oy - margin), shadow_img)


def _fit_text(
    text: str,
    max_width: int,
    font_name: str,
    max_size: int,
    min_size: int,
    max_lines: int,
    auto_size: bool,
    font_manager: FontManager,
) -> tuple:
    """
    Return (font, lines) such that *lines* fits within *max_width* and *max_lines*.

    When *auto_size* is True the font size is stepped down by 2pt from *max_size* to
    *min_size* until the wrapped text fits.  At *min_size* the lines are hard-truncated
    to *max_lines* rather than continuing to shrink (there is no useful size below
    the minimum).
    """
    sizes = range(max_size, min_size - 1, -2) if auto_size else [max_size]

    for size in sizes:
        font = font_manager.get_pil_font(font_name, size)
        lines = _wrap_text(text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines

    # At min_size: truncate rather than shrink further
    font = font_manager.get_pil_font(font_name, min_size)
    lines = _wrap_text(text, font, max_width)
    return font, lines[:max_lines]


def _wrap_text(text: str, font, max_width: int) -> list[str]:
    """
    Word-wrap *text* to fit within *max_width* pixels using real PIL text measurement.

    A single word that is already wider than *max_width* is placed on its own line
    (no character-level splitting).  Returns ``[""]`` for empty input so callers
    always get at least one line.
    """
    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    words = text.split()
    lines: list[str] = []
    current: list[str] = []

    for word in words:
        candidate = " ".join(current + [word])
        bb = dummy.textbbox((0, 0), candidate, font=font)
        w = bb[2] - bb[0]
        if w <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]

    if current:
        lines.append(" ".join(current))
    return lines or [""]


def _apply_transform(text: str, transform: str) -> str:
    """Apply a simple case transform (none / upper / lower / title) to *text*."""
    match transform:
        case "upper": return text.upper()
        case "lower": return text.lower()
        case "title": return text.title()
        case _: return text


def _fit_to_preview(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Scale *img* down proportionally so it fits within *size*; never upscale."""
    img.thumbnail(size, Image.Resampling.LANCZOS)
    return img


def _safe_filename(s: str, max_len: int = 60) -> str:
    """
    Convert an arbitrary string to a safe filesystem stem.

    Keeps alphanumerics, spaces, hyphens, and underscores; replaces everything else
    with ``_``.  Strips surrounding whitespace, truncates to *max_len*, and returns
    ``"item"`` if the sanitised result would be empty.
    """
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in s).strip()
    return safe[:max_len] or "item"


def _assign_stems(
    items: list,
    warnings: list[RenderWarning],
    max_stem: int = 60,
) -> list[str]:
    """
    Return one filename stem per item, guaranteed unique within the list.

    *max_stem* is the maximum stem length **before** any collision postfix is
    appended.  ``render_all`` computes this as the target filename budget minus
    the fixed overhead of the numeric prefix, extension, and worst-case postfix,
    so the full filename stays within that budget regardless of which options
    are active.

    When two or more items produce the same sanitised stem the first occurrence
    keeps the bare stem and subsequent ones receive a ``_2``, ``_3`` … postfix.
    One ``filename_collision`` warning is emitted per collision group.
    """
    from collections import Counter, defaultdict

    raw = [_safe_filename(item.label or item.id, max_len=max_stem) for item in items]
    counts = Counter(raw)
    collision_stems = {stem for stem, n in counts.items() if n > 1}

    if not collision_stems:
        return raw

    # One warning per collision group — list every affected label
    groups: dict[str, list] = defaultdict(list)
    for item, stem in zip(items, raw):
        if stem in collision_stems:
            groups[stem].append(item)

    for stem, group in groups.items():
        labels = [it.label or it.id for it in group]
        warnings.append(RenderWarning(
            item_id=group[0].id,
            severity="warn",
            code="filename_collision",
            message=(
                f"{len(group)} labels truncate to the same {len(stem)}-char stem "
                f'"{stem}" — _2 … _{len(group)} postfixes added to later items. '
                f"Labels: {', '.join(repr(l) for l in labels)}"
            ),
        ))

    # Assign postfixes: first occurrence bare, rest _N
    counters: dict[str, int] = {}
    result: list[str] = []
    for stem in raw:
        if stem not in collision_stems:
            result.append(stem)
        else:
            n = counters.get(stem, 0) + 1
            counters[stem] = n
            result.append(stem if n == 1 else f"{stem}_{n}")

    return result


def _checkerboard(w: int, h: int, sq: int = 40) -> Image.Image:
    """
    Generate a grey checkerboard RGBA image of size *w*×*h*.

    Used as a placeholder when no background image is assigned or loadable.
    *sq* controls the pixel size of each square.
    """
    img = Image.new("RGBA", (w, h))
    pix = img.load()
    light = (200, 200, 200, 255)
    dark  = (160, 160, 160, 255)
    for y in range(h):
        for x in range(w):
            pix[x, y] = light if ((x // sq) + (y // sq)) % 2 == 0 else dark
    return img
