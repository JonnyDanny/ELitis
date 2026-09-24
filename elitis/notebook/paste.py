"""
Clipboard paste widget for Jupyter / Colab.

Handles all clipboard data modes in priority order:
  1. image/*        — raw image blob (screenshot, "Copy image" in browser)
  2. text/html      — HTML snippet containing an inline base64 data-URL <img>
  3. text/html      — HTML snippet containing an HTTP <img src="...">
  4. text/uri-list  — bare image URL
  5. text/plain     — URL-looking text ending in an image extension

Communication channel: JS → Python via kernel.execute() with the payload
JSON-encoded as a string argument to a per-button function registered in the
kernel namespace.  This avoids ipywidgets comm plumbing and works in both
classic Jupyter Notebook and Colab.
"""
from __future__ import annotations

import base64
import json
import uuid
from pathlib import Path
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# JavaScript template
# The placeholder __RECV_FN__ is replaced at button-creation time with the
# unique Python receiver name for that button.
# ---------------------------------------------------------------------------

_JS = r"""
(function () {
    "use strict";

    const RECV = '__RECV_FN__';

    // ------------------------------------------------------------------
    // helpers
    // ------------------------------------------------------------------
    function toBase64(ab) {
        // chunk to avoid spreading huge Uint8Array onto the call stack
        const bytes = new Uint8Array(ab);
        let binary = '';
        const CHUNK = 8192;
        for (let i = 0; i < bytes.length; i += CHUNK)
            binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
        return btoa(binary);
    }

    const EXT = {
        'image/png': '.png', 'image/jpeg': '.jpg', 'image/jpg': '.jpg',
        'image/webp': '.webp', 'image/gif': '.gif', 'image/bmp': '.bmp',
        'image/tiff': '.tiff',
    };

    function extFor(mime) { return EXT[mime.toLowerCase()] || '.png'; }

    function guessName(url) {
        try {
            const seg = new URL(url).pathname.split('/').pop();
            return (seg && seg.includes('.')) ? seg : 'image.jpg';
        } catch { return 'image.jpg'; }
    }

    function send(payload) {
        const kernel =
            (window.IPython && IPython.notebook && IPython.notebook.kernel) ||
            (window.Jupyter  && Jupyter.notebook  && Jupyter.notebook.kernel);
        if (!kernel) { console.error('elitis: Jupyter kernel not found'); return; }
        kernel.execute(RECV + '(' + JSON.stringify(JSON.stringify(payload)) + ')');
    }

    // ------------------------------------------------------------------
    // main
    // ------------------------------------------------------------------
    navigator.clipboard.read().then(async (items) => {
        for (const item of items) {

            // --- mode 1: direct image blob ----------------------------------
            const IMG_TYPES = [
                'image/png', 'image/jpeg', 'image/webp',
                'image/gif', 'image/bmp', 'image/tiff',
            ];
            for (const t of IMG_TYPES) {
                if (item.types.includes(t)) {
                    const ab = await item.getType(t).then(b => b.arrayBuffer());
                    send({ mode: 'b64', mime: t, data: toBase64(ab),
                           name: 'clipboard' + extFor(t), source_url: null });
                    return;
                }
            }

            // --- mode 2 & 3: text/html may contain <img src="…"> -----------
            if (item.types.includes('text/html')) {
                const html = await item.getType('text/html').then(b => b.text());

                // inline data-URL: <img src="data:image/png;base64,ABC...">
                const mData = html.match(
                    /<img[^>]+src="data:image\/([^;]+);base64,([^"]+)"/i
                );
                if (mData) {
                    const mime = 'image/' + mData[1].toLowerCase();
                    send({ mode: 'b64', mime, data: mData[2],
                           name: 'clipboard' + extFor(mime), source_url: null });
                    return;
                }

                // HTTP URL in src attribute
                const mUrl = html.match(/<img[^>]+src="(https?:\/\/[^"]+)"/i);
                if (mUrl) {
                    const url = mUrl[1];
                    send({ mode: 'url', url, name: guessName(url), source_url: url });
                    return;
                }
            }

            // --- mode 4 & 5: uri-list or plain text URL --------------------
            for (const tt of ['text/uri-list', 'text/plain']) {
                if (!item.types.includes(tt)) continue;
                const raw  = await item.getType(tt).then(b => b.text());
                const line = raw.trim().split('\n')[0].trim();
                if (/^https?:\/\/.+\.(png|jpe?g|webp|gif|bmp|tiff?)/i.test(line)) {
                    send({ mode: 'url', url: line, name: guessName(line), source_url: line });
                    return;
                }
            }
        }

        // Nothing usable in any item
        send({ mode: 'empty' });

    }).catch(err => send({ mode: 'error', message: String(err) }));
})();
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def paste_button(
    sourced_dir: Path,
    on_assigned: Callable[[Path], None],
    *,
    label: str = "Paste image",
    button_style: str = "",
) -> "ipywidgets.HBox":
    """
    Return a widget containing a clipboard paste button and a status area.

    Parameters
    ----------
    sourced_dir   Directory passed to ``save_sourced_image()``.
    on_assigned   Called with the committed ``Path`` after a successful paste.
    label         Button label text.
    button_style  ipywidgets button style (``""``, ``"primary"``, etc.).

    Notes
    -----
    Requires HTTPS or localhost — browsers block Clipboard API on plain HTTP.
    ``IPython.notebook.kernel`` must be accessible in the page (works in both
    classic Jupyter Notebook and Colab; JupyterLab ≥ 4 may need an extension).
    """
    import ipywidgets as w
    from IPython.display import display, Javascript

    status = w.Output(layout=w.Layout(margin="0 0 0 8px"))
    btn    = w.Button(description=label, button_style=button_style, icon="clipboard",
                      layout=w.Layout(width="auto"))

    # Unique receiver name so multiple buttons in the same notebook don't clash
    fn_name = f"_elitis_paste_{uuid.uuid4().hex[:8]}"

    def _recv(payload_json: str) -> None:
        with status:
            status.clear_output(wait=True)
            try:
                payload = json.loads(payload_json)
            except Exception as exc:
                print(f"Paste decode error: {exc}")
                return

            mode = payload.get("mode", "")
            if mode == "empty":
                print("Nothing to paste — no image on clipboard.")
                return
            if mode == "error":
                print(f"Clipboard error: {payload.get('message', '?')}")
                return

            from elitis.core.ingest import save_sourced_image

            try:
                if mode == "b64":
                    data = base64.b64decode(payload["data"])
                    path = save_sourced_image(
                        data,
                        payload["name"],
                        sourced_dir,
                        source_url=payload.get("source_url"),
                    )
                elif mode == "url":
                    data = _fetch_url(payload["url"])
                    if data is None:
                        print(f"Could not fetch: {payload['url']}")
                        return
                    path = save_sourced_image(
                        data,
                        payload["name"],
                        sourced_dir,
                        source_url=payload.get("source_url"),
                    )
                else:
                    print(f"Unknown paste mode: {mode!r}")
                    return
            except Exception as exc:
                print(f"Ingest failed: {exc}")
                return

            print(f"✓ {path.name}")
            on_assigned(path)

    # Register in kernel namespace so JS-executed Python can call it by name
    ip = _get_ipython()
    if ip is not None:
        ip.user_ns[fn_name] = _recv

    def _on_click(_):
        js = _JS.replace("__RECV_FN__", fn_name)
        display(Javascript(js))

    btn.on_click(_on_click)
    return w.HBox([btn, status], layout=w.Layout(align_items="center"))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_url(url: str, timeout: int = 15) -> Optional[bytes]:
    from elitis.core.ingest import fetch_url_bytes
    return fetch_url_bytes(url, timeout=timeout)


def _get_ipython():
    try:
        from IPython import get_ipython
        return get_ipython()
    except ImportError:
        return None
