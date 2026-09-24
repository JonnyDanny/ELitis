"""
Cell 2 — image assignment panel.

Shows items without images and provides:
  - Bulk upload:  files.upload() → auto-match by filename stem
  - URL download: download an image from a URL into the project dir
  - Manual path:  type an absolute path (for symlinks / mounted drives)
  - Clipboard:    "Paste image" button per row (all clipboard modes supported)

After assignment, image_hash is computed and stored on the item.
"""
from __future__ import annotations

from pathlib import Path


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}


def image_panel(
    project,
    project_dir: str | Path | None = None,
    sourced_dir: str | Path | None = None,
    project_path: str | Path | None = None,
) -> None:
    """
    Display the image assignment UI for all unmatched items.

    ``project_dir`` is where uploaded/URL-fetched images are saved; defaults to
    /content/project/Images/ in Colab.

    ``sourced_dir`` is where clipboard-pasted images are committed via the
    atomic ingest pipeline; defaults to ``project_dir/../Ingest/Sourced/``.

    ``project_path`` is the JSON file to auto-save after each assignment.
    Pass it to survive a Colab VM disconnect without re-doing image work.
    """
    import ipywidgets as w
    from IPython.display import display, HTML

    project_dir = Path(project_dir) if project_dir else Path("/content/project/Images")
    project_dir.mkdir(parents=True, exist_ok=True)
    sourced_dir = Path(sourced_dir) if sourced_dir else project_dir.parent / "Ingest" / "Sourced"
    _project_path = Path(project_path) if project_path else None

    def _autosave():
        if _project_path:
            try:
                from elitis.core.data_io import save_project
                save_project(project, _project_path)
            except Exception:
                pass

    unmatched = [
        item for item in project.content_items
        if not item.image_path or not Path(item.image_path).exists()
    ]

    if not unmatched:
        print(f"All {len(project.content_items)} items have images assigned.")
        return

    print(f"{len(unmatched)} item(s) without images:")

    # -- build image lookup from already-uploaded files -----------------------
    def _rebuild_lookup() -> dict[str, Path]:
        lut: dict[str, Path] = {}
        for p in project_dir.rglob("*"):
            if p.suffix.lower() in IMAGE_EXTS:
                lut[p.name.lower()] = p
                lut[p.stem.lower()] = p
        return lut

    # ── Bulk upload button ───────────────────────────────────────────────────
    btn_upload = w.Button(description="Upload images", button_style="primary",
                          icon="upload")
    out_upload = w.Output()

    def _on_upload(_):
        with out_upload:
            out_upload.clear_output()
            try:
                from google.colab import files as _cf
                uploaded = _cf.upload()
            except ImportError:
                print("files.upload() not available outside Colab.")
                return
            lut = _rebuild_lookup()
            for name, data in uploaded.items():
                dest = project_dir / name
                dest.write_bytes(data)
                lut[dest.name.lower()] = dest
                lut[dest.stem.lower()] = dest

            matched = 0
            for item in unmatched:
                if item.image_path and Path(item.image_path).exists():
                    continue
                key = (item.label or "").lower().replace(" ", "_")
                match = lut.get(key) or lut.get((item.label or "").lower())
                if match:
                    item.image_path = str(match)
                    _try_hash(item)
                    matched += 1
            print(f"Matched {matched}/{len(unmatched)} item(s) by filename stem.")
            _refresh_table()

    btn_upload.on_click(_on_upload)

    # ── Table refresh — defined here so paste callbacks can call it ─────────
    table_out = w.Output()

    def _refresh_table():
        with table_out:
            table_out.clear_output()
            still = sum(
                1 for it in project.content_items
                if not it.image_path or not Path(it.image_path).exists()
            )
            if still == 0:
                display(HTML("<b style='color:#6f6'>All items have images.</b>"))
            else:
                display(HTML(f"<b style='color:#fa0'>{still} item(s) still unmatched.</b>"))

    # ── Per-item URL / path / paste inputs ──────────────────────────────────
    from elitis.notebook.paste import paste_button

    rows_widgets: list[tuple] = []  # (item, url_input, path_input, status_out)

    for item in unmatched:
        lbl    = w.HTML(
            f"<span style='color:#ccc;min-width:180px;display:inline-block'>"
            f"{item.label or item.id}</span>"
        )
        w_url  = w.Text(placeholder="https://... image URL",
                        layout=w.Layout(width="280px"))
        w_path = w.Text(placeholder="or /absolute/path.png",
                        layout=w.Layout(width="200px"))
        btn    = w.Button(description="Assign", button_style="", icon="check",
                          layout=w.Layout(width="80px"))
        status = w.Output()

        def _make_assign(it, wu, wp, st):
            def _assign(_):
                with st:
                    st.clear_output()
                    url  = wu.value.strip()
                    path = wp.value.strip()
                    if url:
                        dest = _download_url(url, project_dir, it.label or it.id)
                        if dest:
                            it.image_path = str(dest)
                            _try_hash(it)
                            _autosave()
                            print(f"Downloaded -> {dest.name}")
                        else:
                            print("Download failed.")
                    elif path and Path(path).exists():
                        it.image_path = path
                        _try_hash(it)
                        _autosave()
                        print(f"Assigned {Path(path).name}")
                    else:
                        print("Provide a valid URL or path.")
            return _assign

        def _make_on_pasted(it, st):
            def _on_pasted(path):
                it.image_path = str(path)
                _try_hash(it)
                _autosave()
                with st:
                    st.clear_output()
                    print(f"Pasted → {path.name}")
                _refresh_table()
            return _on_pasted

        btn.on_click(_make_assign(item, w_url, w_path, status))
        btn_paste = paste_button(sourced_dir, _make_on_pasted(item, status))

        rows_widgets.append((item, w_url, w_path, status))
        display(w.VBox([
            w.HBox([lbl, w_url, w_path, btn, btn_paste]),
            status,
        ]))

    display(w.VBox([
        w.HBox([btn_upload, out_upload]),
        table_out,
    ]))
    _refresh_table()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _try_hash(item) -> None:
    if item.image_path and Path(item.image_path).exists():
        try:
            from elitis.core.data_io import compute_image_hash
            item.image_hash = compute_image_hash(item.image_path)
        except Exception:
            pass


def _download_url(url: str, dest_dir: Path, label: str) -> Path | None:
    import urllib.request
    import urllib.error
    # Derive a safe filename from the URL path, falling back to label
    from pathlib import PurePosixPath
    try:
        stem = PurePosixPath(url.split("?")[0]).stem or label
        suffix = PurePosixPath(url.split("?")[0]).suffix or ".jpg"
    except Exception:
        stem, suffix = label, ".jpg"

    safe_stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)[:60]
    dest = dest_dir / f"{safe_stem}{suffix}"

    try:
        urllib.request.urlretrieve(url, str(dest))
        return dest
    except Exception:
        return None
