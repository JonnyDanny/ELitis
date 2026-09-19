"""
Project-wide tune panels — ipywidgets controls for Cell 3a/3b/3c.

Each panel reads the current defaults item settings, creates controls
pre-populated with those values, and wires observers that write back
immediately so the project stays live.  Re-run Cell 4 to see the effect.

Per-item overrides (emergency escape hatches) are in overrides.py.
"""
from __future__ import annotations

from pathlib import Path

from elitis.notebook._utils import rgb_to_hex, hex_to_rgb


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _label(text: str):
    import ipywidgets as w
    return w.HTML(f"<b style='color:#ccc'>{text}</b>")


def _section(title: str, children):
    import ipywidgets as w
    box = w.VBox([_label(title)] + list(children),
                 layout=w.Layout(padding="8px 0 16px 0"))
    return box


def _row(label: str, widget):
    import ipywidgets as w
    lbl = w.HTML(
        f"<span style='color:#aaa;font-size:13px;min-width:140px;"
        f"display:inline-block'>{label}</span>"
    )
    return w.HBox([lbl, widget])


def _observe(widget, sf, transform=None):
    """Wire widget value → sf.value via observer."""
    def _cb(change):
        val = change["new"]
        sf.value = transform(val) if transform else val
    widget.observe(_cb, names="value")


# ---------------------------------------------------------------------------
# Cell 3a · Font panel
# ---------------------------------------------------------------------------

def font_panel(project, font_names: list[str] | None = None) -> None:
    """
    ipywidgets controls for project-wide font settings.

    ``font_names`` overrides auto-discovery.  When omitted, the panel scans
    /content/project/Fonts/ for .ttf/.otf files and prepends "default".
    """
    import ipywidgets as w
    from IPython.display import display

    s = project.defaults.settings

    # -- discover fonts -------------------------------------------------------
    if font_names is None:
        fonts_dir = Path("/content/project/Fonts")
        discovered = sorted(
            p.stem for p in fonts_dir.rglob("*")
            if p.suffix.lower() in (".ttf", ".otf", ".woff")
        ) if fonts_dir.exists() else []
        font_names = ["default"] + discovered

    current_font = s.font_name.value
    if current_font not in font_names:
        font_names = [current_font] + font_names

    # -- widgets --------------------------------------------------------------
    w_font     = w.Dropdown(options=font_names, value=current_font,
                            layout=w.Layout(width="260px"))
    w_size     = w.IntSlider(value=s.font_size.value, min=8, max=300, step=2,
                             continuous_update=False,
                             layout=w.Layout(width="260px"))
    w_auto     = w.Checkbox(value=s.font_auto_size.value, description="Auto-size")
    w_min_size = w.IntSlider(value=s.font_min_size.value, min=4, max=100, step=2,
                             continuous_update=False,
                             layout=w.Layout(width="260px"))
    w_lines    = w.IntSlider(value=s.font_max_lines.value, min=1, max=6, step=1,
                             layout=w.Layout(width="260px"))

    # -- observers ------------------------------------------------------------
    _observe(w_font,     s.font_name)
    _observe(w_size,     s.font_size)
    _observe(w_auto,     s.font_auto_size)
    _observe(w_min_size, s.font_min_size)
    _observe(w_lines,    s.font_max_lines)

    # min-size and max-lines only meaningful when auto-size is on
    def _toggle_auto(change):
        w_min_size.disabled = not change["new"]
        w_lines.disabled    = not change["new"]
    w_auto.observe(_toggle_auto, names="value")
    w_min_size.disabled = not s.font_auto_size.value
    w_lines.disabled    = not s.font_auto_size.value

    panel = _section("3a · Font", [
        _row("Font",          w_font),
        _row("Max size (px)", w_size),
        w_auto,
        _row("Min size (px)", w_min_size),
        _row("Max lines",     w_lines),
        w.HTML("<small style='color:#666'>Changes apply when you re-run Cell 4 (Render).</small>"),
    ])
    display(panel)


# ---------------------------------------------------------------------------
# Cell 3b · Text style panel
# ---------------------------------------------------------------------------

def text_panel(project) -> None:
    """ipywidgets controls for project-wide text style and position."""
    import ipywidgets as w
    from IPython.display import display

    s = project.defaults.settings

    w_color     = w.ColorPicker(value=rgb_to_hex(s.text_color.value),
                                description="", layout=w.Layout(width="80px"))
    w_opacity   = w.IntSlider(value=s.text_opacity.value, min=0, max=255,
                              continuous_update=False, layout=w.Layout(width="260px"))
    w_transform = w.ToggleButtons(
        options=["none", "upper", "lower", "title"],
        value=s.text_transform.value,
        style={"button_width": "70px"},
    )
    w_align     = w.ToggleButtons(
        options=["left", "center", "right"],
        value=s.text_align.value,
        style={"button_width": "70px"},
    )
    w_tx        = w.FloatSlider(value=s.text_x.value, min=0.0, max=1.0, step=0.01,
                                readout_format=".2f", continuous_update=False,
                                layout=w.Layout(width="260px"))
    w_ty        = w.FloatSlider(value=s.text_y.value, min=0.0, max=1.0, step=0.01,
                                readout_format=".2f", continuous_update=False,
                                layout=w.Layout(width="260px"))

    _observe(w_color,     s.text_color,     transform=hex_to_rgb)
    _observe(w_opacity,   s.text_opacity)
    _observe(w_transform, s.text_transform)
    _observe(w_align,     s.text_align)
    _observe(w_tx,        s.text_x)
    _observe(w_ty,        s.text_y)

    panel = _section("3b · Text style", [
        _row("Color",      w_color),
        _row("Opacity",    w_opacity),
        _row("Transform",  w_transform),
        _row("Align",      w_align),
        _row("Position X", w_tx),
        _row("Position Y", w_ty),
        w.HTML("<small style='color:#666'>Changes apply when you re-run Cell 4 (Render).</small>"),
    ])
    display(panel)


# ---------------------------------------------------------------------------
# Cell 3c · Overlay panel
# ---------------------------------------------------------------------------

def overlay_panel(project) -> None:
    """ipywidgets controls for project-wide box overlay, outline, and shadow."""
    import ipywidgets as w
    from IPython.display import display

    s = project.defaults.settings

    # ── Box ──────────────────────────────────────────────────────────────────
    w_box_on       = w.Checkbox(value=s.box_enabled.value, description="Box enabled")
    w_box_color    = w.ColorPicker(value=rgb_to_hex(s.box_color.value),
                                   description="", layout=w.Layout(width="80px"))
    w_box_opacity  = w.IntSlider(value=s.box_opacity.value, min=0, max=255,
                                 continuous_update=False, layout=w.Layout(width="240px"))
    w_box_height   = w.FloatSlider(value=s.box_height.value, min=0.0, max=1.0, step=0.01,
                                   readout_format=".2f", continuous_update=False,
                                   layout=w.Layout(width="240px"))
    w_box_pos      = w.ToggleButtons(
        options=["bottom", "top", "full"],
        value=s.box_position.value,
        style={"button_width": "70px"},
    )

    _observe(w_box_on,      s.box_enabled)
    _observe(w_box_color,   s.box_color,   transform=hex_to_rgb)
    _observe(w_box_opacity, s.box_opacity)
    _observe(w_box_height,  s.box_height)
    _observe(w_box_pos,     s.box_position)

    box_controls = [
        _row("Color",    w_box_color),
        _row("Opacity",  w_box_opacity),
        _row("Height",   w_box_height),
        _row("Position", w_box_pos),
    ]

    def _toggle_box(change):
        for ctrl in box_controls:
            ctrl.children[1].disabled = not change["new"]
    w_box_on.observe(_toggle_box, names="value")
    for ctrl in box_controls:
        ctrl.children[1].disabled = not s.box_enabled.value

    # ── Outline ──────────────────────────────────────────────────────────────
    w_out_on    = w.Checkbox(value=s.outline_enabled.value, description="Outline enabled")
    w_out_color = w.ColorPicker(value=rgb_to_hex(s.outline_color.value),
                                description="", layout=w.Layout(width="80px"))
    w_out_width = w.IntSlider(value=s.outline_width.value, min=0, max=20,
                              layout=w.Layout(width="240px"))

    _observe(w_out_on,    s.outline_enabled)
    _observe(w_out_color, s.outline_color, transform=hex_to_rgb)
    _observe(w_out_width, s.outline_width)

    outline_controls = [_row("Color", w_out_color), _row("Width", w_out_width)]

    def _toggle_outline(change):
        for ctrl in outline_controls:
            ctrl.children[1].disabled = not change["new"]
    w_out_on.observe(_toggle_outline, names="value")
    for ctrl in outline_controls:
        ctrl.children[1].disabled = not s.outline_enabled.value

    # ── Shadow ───────────────────────────────────────────────────────────────
    w_shad_on     = w.Checkbox(value=s.shadow_enabled.value, description="Shadow enabled")
    w_shad_color  = w.ColorPicker(value=rgb_to_hex(s.shadow_color.value),
                                  description="", layout=w.Layout(width="80px"))
    w_shad_ox     = w.IntSlider(value=s.shadow_offset_x.value, min=-30, max=30,
                                layout=w.Layout(width="240px"))
    w_shad_oy     = w.IntSlider(value=s.shadow_offset_y.value, min=-30, max=30,
                                layout=w.Layout(width="240px"))
    w_shad_blur   = w.IntSlider(value=s.shadow_blur.value, min=0, max=30,
                                layout=w.Layout(width="240px"))

    _observe(w_shad_on,    s.shadow_enabled)
    _observe(w_shad_color, s.shadow_color,    transform=hex_to_rgb)
    _observe(w_shad_ox,    s.shadow_offset_x)
    _observe(w_shad_oy,    s.shadow_offset_y)
    _observe(w_shad_blur,  s.shadow_blur)

    shadow_controls = [
        _row("Color",    w_shad_color),
        _row("Offset X", w_shad_ox),
        _row("Offset Y", w_shad_oy),
        _row("Blur",     w_shad_blur),
    ]

    def _toggle_shadow(change):
        for ctrl in shadow_controls:
            ctrl.children[1].disabled = not change["new"]
    w_shad_on.observe(_toggle_shadow, names="value")
    for ctrl in shadow_controls:
        ctrl.children[1].disabled = not s.shadow_enabled.value

    panel = _section("3c · Overlay", [
        w_box_on, *box_controls,
        w.HTML("<hr style='border-color:#333'>"),
        w_out_on, *outline_controls,
        w.HTML("<hr style='border-color:#333'>"),
        w_shad_on, *shadow_controls,
        w.HTML("<small style='color:#666'>Changes apply when you re-run Cell 4 (Render).</small>"),
    ])
    display(panel)
