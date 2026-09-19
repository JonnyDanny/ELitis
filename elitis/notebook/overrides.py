"""
Cell 3e — per-item emergency override panel.

Runs check_text_fit() on all items and surfaces a controls row for each item
that has warnings.  Also accessible manually (button in filmstrip equivalent)
so users can fix things the renderer does not flag.

Overrides written here set use_default=False on the relevant per-item SF so
they survive defaults-item changes and appear in the saved project JSON.
"""
from __future__ import annotations

from pathlib import Path


def override_panel(project, font_manager=None) -> None:
    """
    Show per-item override controls for items with text fit warnings.

    ``font_manager`` is used to run check_text_fit(); if omitted a temporary
    FontManager is created pointing at /content/project/Fonts/.
    """
    import ipywidgets as w
    from IPython.display import display, HTML

    from elitis.core import renderer
    from elitis.core.font_manager import FontManager

    if font_manager is None:
        fonts_dir = Path("/content/project/Fonts")
        font_manager = FontManager(fonts_dir if fonts_dir.exists() else Path("/nonexistent"))

    # -- run dry-layout check on all items ------------------------------------
    warnings_by_id: dict[str, list] = {}
    for item in project.content_items:
        ws = renderer.check_text_fit(item, project, font_manager)
        if ws:
            warnings_by_id[item.id] = ws

    if not warnings_by_id:
        print("No text fit issues detected. You can still add manual overrides below.")

    items_with_issues = [
        item for item in project.content_items
        if item.id in warnings_by_id
    ]
    items_manual = [
        item for item in project.content_items
        if item.id not in warnings_by_id
    ]

    # -- per-item override rows -----------------------------------------------
    def _make_row(item, show_warnings: bool):
        warnings = warnings_by_id.get(item.id, [])

        s     = item.settings
        title = w.HTML(
            f"<b style='color:#{'f66' if warnings else 'fa0'}'>{item.label or item.id}</b>"
        )

        # Warning badges
        badges = w.HTML("".join(
            f"<span style='background:#333;color:#f66;font-size:11px;"
            f"padding:1px 5px;border-radius:3px;margin-right:4px'>{ww.code}</span>"
            for ww in warnings
        )) if warnings else w.HTML("")

        # Min font size override
        current_min = s.font_min_size.value if not s.font_min_size.use_default else \
                      project.defaults.settings.font_min_size.value
        w_min = w.BoundedIntText(
            value=current_min, min=4, max=100, step=2,
            description="Min font px",
            style={"description_width": "90px"},
            layout=w.Layout(width="180px"),
        )

        # Max lines override
        current_lines = s.font_max_lines.value if not s.font_max_lines.use_default else \
                        project.defaults.settings.font_max_lines.value
        w_lines = w.BoundedIntText(
            value=current_lines, min=1, max=8, step=1,
            description="Max lines",
            style={"description_width": "90px"},
            layout=w.Layout(width="160px"),
        )

        # Accept image hash as-is (only when relevant)
        from elitis.core.data_io import check_image_integrity, HASH_OK
        severity, _ = check_image_integrity(item)
        btn_accept_img = w.Button(
            description="Accept image", button_style="warning", icon="check",
            layout=w.Layout(width="130px", display="block" if severity != HASH_OK else "none"),
        )

        btn_apply = w.Button(description="Apply", button_style="success", icon="check",
                             layout=w.Layout(width="80px"))
        btn_reset = w.Button(description="Reset", button_style="", icon="times",
                             layout=w.Layout(width="80px"))
        status    = w.Output()

        def _apply(_):
            with status:
                status.clear_output()
                item.settings.font_min_size.value       = w_min.value
                item.settings.font_min_size.use_default = False
                item.settings.font_max_lines.value      = w_lines.value
                item.settings.font_max_lines.use_default = False
                print(f"Applied: min_size={w_min.value}px, max_lines={w_lines.value}")

        def _reset(_):
            with status:
                status.clear_output()
                item.settings.font_min_size.use_default  = True
                item.settings.font_max_lines.use_default = True
                w_min.value   = project.defaults.settings.font_min_size.value
                w_lines.value = project.defaults.settings.font_max_lines.value
                print("Reset to project defaults.")

        def _accept_img(_):
            with status:
                status.clear_output()
                from elitis.core.data_io import accept_image_hash
                accept_image_hash(item)
                print("Image hash accepted.")
                btn_accept_img.layout.display = "none"

        btn_apply.on_click(_apply)
        btn_reset.on_click(_reset)
        btn_accept_img.on_click(_accept_img)

        return w.VBox([
            w.HBox([title, badges]),
            w.HBox([w_min, w_lines, btn_accept_img]),
            w.HBox([btn_apply, btn_reset]),
            status,
            w.HTML("<hr style='border-color:#222;margin:4px 0'>"),
        ])

    if items_with_issues:
        display(HTML(
            f"<b style='color:#f66'>{len(items_with_issues)} item(s) with text fit issues:</b>"
        ))
        for item in items_with_issues:
            display(_make_row(item, show_warnings=True))

    # -- manual section (accordion) -------------------------------------------
    if items_manual:
        manual_rows = [_make_row(item, show_warnings=False) for item in items_manual]
        acc = w.Accordion(children=[w.VBox(manual_rows)])
        acc.set_title(0, f"Manual overrides ({len(items_manual)} items without issues)")
        acc.selected_index = None  # collapsed by default
        display(acc)

    display(HTML(
        "<small style='color:#666'>Changes apply when you re-run Cell 4 (Render).</small>"
    ))
