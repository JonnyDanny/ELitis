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


def render_all(
    project: Project,
    font_manager: FontManager,
    output_dir: Path,
    fmt: str = "PNG",
    on_progress=None,
) -> tuple[list[Path], list[RenderWarning]]:
    """
    Batch-render every content item to *output_dir*.

    Returns ``(saved_paths, warnings)`` where *warnings* is the combined list
    from ``check_text_fit()`` for all items.  Items with no image are rendered
    as a grey checkerboard and an ``image_missing`` warning is added.

    *on_progress(done, total, path)* is called after each file is written.
    Pass None to skip it.

    Output filenames are ``NNN_sanitised_label.ext``, NNN zero-padded to three
    digits.  JPEG output is converted to RGB before saving.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    saved:    list[Path]          = []
    warnings: list[RenderWarning] = []
    items = project.content_items

    for i, item in enumerate(items):
        # image_missing warning
        if not item.effective_image(project.defaults):
            warnings.append(RenderWarning(
                item_id=item.id, severity="error",
                code="image_missing",
                message=f"No image assigned — rendered as checkerboard",
            ))

        # text fit warnings
        warnings.extend(check_text_fit(item, project, font_manager))

        img  = render_thumbnail(item, project, font_manager)
        safe = _safe_filename(item.label or item.id)
        ext  = "jpg" if fmt.upper() == "JPEG" else fmt.lower()
        dest = output_dir / f"{i:03d}_{safe}.{ext}"
        if fmt.upper() == "JPEG":
            img = img.convert("RGB")
        img.save(str(dest), format=fmt)
        saved.append(dest)
        if on_progress:
            on_progress(i + 1, len(items), dest)

    return saved, warnings


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
