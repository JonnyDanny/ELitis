"""
ELItis codebase walkthrough — press any key to advance, Q to quit.

Covers two tracks:
  1  Qt desktop frontend
  2  Jupyter / Colab frontend

No ELItis installation required; pure stdlib.
"""
import os
import sys

# ---------------------------------------------------------------------------
# Terminal helpers
# ---------------------------------------------------------------------------

def _getch():
    if sys.platform == "win32":
        import msvcrt
        return msvcrt.getch()
    else:
        import tty, termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            return sys.stdin.read(1).encode()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _clear():
    os.system("cls" if sys.platform == "win32" else "clear")


def _show(index, total, title, body):
    _clear()
    bar = "─" * 62
    print(bar)
    print(f"  [{index}/{total}]  {title}")
    print(bar)
    print()
    for line in body.strip().splitlines():
        print(f"  {line}")
    print()
    print("  [any key] next   [b] back   [q] quit")
    while True:
        ch = _getch()
        if ch in (b"q", b"Q"):
            _clear()
            sys.exit(0)
        if ch in (b"b", b"B"):
            return "back"
        return "next"


def _run(sections):
    i = 0
    while i < len(sections):
        title, body = sections[i]
        result = _show(i + 1, len(sections), title, body)
        if result == "back" and i > 0:
            i -= 1
        else:
            i += 1
    _clear()
    print("  End of track. Run again to repeat.")
    print()


# ---------------------------------------------------------------------------
# Track 1 — Qt desktop
# ---------------------------------------------------------------------------

QT_SECTIONS = [

("Entry point", """
python -m elitis
  └── elitis/__main__.py
        └── QApplication + AppState(projects, egest, fonts)
              └── MainWindow(state)

AppState (elitis/ui/app_state.py) subclasses BaseAppState and adds:
  - Qt signals  (status_message, preview_requested, …)
  - sourced_dir property  →  <project>/Ingest/Sourced/
  - ingest_file()         →  idempotency guard (see slide 4)
  - paste_image_from_clipboard()
"""),

("BaseAppState — the write boundary", """
elitis/core/app_state.py

ALL model mutations go through one of:
  commit_field(field_name, value, use_default)
  commit_crop(x, y, w, h)
  commit_label(item_id, label)   ← also calls _autosave()
  commit_image(item_id, path)    ← also calls _autosave()

Each calls _react(item) which:
  1. marks the item dirty (clears it from _clean_ids)
  2. fires _on_changed(item)  →  Qt: triggers live preview re-render

_autosave() writes the project JSON if _project_path is known.
Tune/crop changes do NOT autosave — save happens at render time.
"""),

("Project JSON — save points", """
Saved automatically when:
  commit_image()  →  image assigned (any source)
  commit_label()  →  label edited in Data tab
  export_batch()  →  after render_all() completes

Also saved explicitly via File → Save (save_project / save_project_as).

_project_path is set when the user loads or saves a project.
Before first save it is None, so _autosave() is a no-op — the
user must do File → Save once to anchor the path.
"""),

("Image ingest — ingest_file()", """
elitis/ui/app_state.py → ingest_file(path)

  if path is already inside self.ingest_dir:
      return path as-is  (idempotency guard)
  else:
      return save_sourced_image(path.read_bytes(), path.name,
                                self.sourced_dir)

This means double-importing the same file is safe.
The file dialog and drag-drop both route through ingest_file().
"""),

("Atomic ingest pipeline — save_sourced_image()", """
elitis/core/ingest.py

5-step crash-safe commit:
  1. Write sidecar .json.partial  (source_url, original_name, timestamp)
  2. Write image to <rand8>.tmp   (rand8 = os.urandom(4).hex())
  3. Hash the .tmp  →  blake3 or sha256, first 16 hex chars
  4. Rename image   →  {hash16}_{rand8}.ext
  5. Rename sidecar →  {hash16}_{rand8}.json  (remove .partial)

On crash between steps 1-4 a .tmp or .json.partial is left behind.
cleanup_buffers(dest_dir) removes these orphans on next startup.

rand8 is the acquisition ID — same content pasted twice gets two
distinct files (different rand8) even though hash16 is identical.
"""),

("Clipboard paste — paste_image_from_clipboard()", """
elitis/ui/app_state.py

Qt clipboard can hold multiple formats simultaneously.
Priority order checked:

  1. \"image\" mime   →  QImage → PIL RGBA → PNG bytes
  2. \"base64\" text  →  base64.b64decode()
  3. \"files\" list   →  first image file → path.read_bytes()
  4. \"url\" text     →  fetch_url_bytes(url, timeout=15)

All four routes end at:
  save_sourced_image(data, name, self.sourced_dir, source_url=…)
  commit_image(item.id, str(committed_path))
"""),

("Drag and drop", """
elitis/ui/main_window.py

dragEnterEvent:  accepts if any dropped URL passes _url_is_image()
                 (checks suffix against _IMAGE_EXTS set)

dropEvent:
  for each URL in mime.urls():
    if local file  →  state.ingest_file(path)
    if HTTP URL    →  fetch_url_bytes(href)
                      save_sourced_image(data, name, sourced_dir,
                                         source_url=href)

  ingested[0]  →  assigned to current item
  ingested[1+] →  saved to Sourced/ only (status message lists names)
"""),

("render_all — stem assignment", """
elitis/core/renderer.py → render_all()

Before the render loop, stems are computed once for all items:

  1. Quick Counter pass to find max collision depth (N)
  2. postfix_reserve = len(f\"_{N}\")  →  2 for ≤9, 3 for ≤99, …
  3. stem_budget = max(20, 60 - prefix_overhead - ext_overhead
                            - postfix_reserve)
  4. _assign_stems(items, warnings, max_stem=stem_budget)

_assign_stems:
  - first occurrence of a colliding stem → bare stem
  - subsequent → stem_2, stem_3, …
  - one warning per collision GROUP (not per item)
"""),

("last_output_path — stale file cleanup", """
elitis/core/models.py  →  ThumbnailItem.last_output_path

Stored in the project JSON.  Set by render_all() after each save.

On the NEXT render, before writing the new file:
  old = Path(item.last_output_path)
  if old != new_dest and old.exists():
      old.unlink()          # silent OSError swallow

Triggers when:
  - label renamed        → different stem → different filename
  - numbered toggled     → NNN_ prefix added/removed
  - format changed       → .png → .jpg
  - collision rank shifts → stem_2 → stem_3

After unlink, last_output_path is stamped with the new path.
"""),

("PNG metadata — elitis tEXt chunk", """
elitis/core/renderer.py → _build_png_meta()

Every PNG output embeds a tEXt chunk with key \"elitis\":
  {
    \"version\":     \"0.2.0.pre\",
    \"rendered_at\": \"2025-…\",
    \"project\":     \"my_project\",
    \"item_id\":     \"a1b2c3d4\",
    \"label\":       \"Elden Ring 🔥\",
    \"image_hash\":  first 16 chars of sha256,
    \"settings\":    { full ResolvedSettings flat dict },
    \"warnings\":    [ {code, severity, message}, … ]
  }

Read back with:
  from PIL import Image
  img = Image.open(\"000_Elden_Ring__.png\")
  print(img.text[\"elitis\"])

JPEG output does NOT embed metadata (no tEXt equivalent in JFIF).
"""),

]


# ---------------------------------------------------------------------------
# Track 2 — Jupyter / Colab
# ---------------------------------------------------------------------------

NB_SECTIONS = [

("Cell architecture", """
ELItis_Colab.ipynb — five execution cells:

  Cell 0  Setup      install package, define PROJECT_DIR / OUTPUT_DIR
  Cell 1  Import     upload zip/CSV → load/create project → save JSON
  Cell 2  Images     assign images per item (upload, URL, paste)
  Cell 3  Tune       font, text, overlay panels (re-run → Cell 4)
  Cell 4  Render     full-res batch render → warnings → gallery → save
  Cell 5  Export     zip OUTPUT_DIR → browser download

Loop: 3 → 4 until the gallery looks right, then run 5 once.
Cells 1-2 each write the project JSON, so a VM disconnect only
loses tune changes made after the last Cell 4 run.
"""),

("Cell 1 — import_panel()", """
elitis/notebook/display.py → import_panel()

First run (existing_project=None):
  1. Colab files.upload()  →  zip extracted to PROJECT_DIR
  2. Discover .json / .csv / image files in the extracted tree
  3. If .json found  →  load_project() + remap image paths
     If only labels  →  Project.new() + add_item() per label
     If only images  →  use filenames as labels

After import_panel returns, Cell 1 does:
  _PROJECT_JSON = PROJECT_DIR / f\"{project.name}.json\"
  save_project(project, _PROJECT_JSON)

This establishes the canonical save path used by Cells 2 and 4.
Re-running Cell 1 with existing_project triggers additive
reconciliation (new labels merged, duplicates/conflicts reported).
"""),

("Cell 2 — image_panel() and paste_button()", """
elitis/notebook/images.py → image_panel(project, project_path=…)

Shows one row per unmatched item:
  [label]  [URL field]  [path field]  [Assign]  [Paste image]

URL / path assign  →  sets item.image_path + _try_hash()
                   →  calls _autosave() (writes _PROJECT_JSON)

Paste button       →  elitis/notebook/paste.py → paste_button()
                       renders an ipywidgets HBox with a JS clipboard
                       reader wired to a UUID-scoped Python receiver

Each assignment auto-saves. If the VM disconnects after Cell 2,
all image paths assigned so far are persisted in _PROJECT_JSON.
"""),

("paste_button internals — JS→kernel channel", """
elitis/notebook/paste.py

JS side (runs in the browser on button click):
  1. navigator.clipboard.read()  →  try formats in order:
       image/*             →  toBase64(blob)  →  {mode:\"b64\", …}
       text/html base64    →  parse src= attr  →  {mode:\"b64\", …}
       text/html HTTP URL  →  extract src=     →  {mode:\"url\", …}
       text/uri-list       →                   →  {mode:\"url\", …}
       text/plain URL      →                   →  {mode:\"url\", …}
  2. kernel.execute(RECV_FN(JSON.stringify(payload)))

Python receiver (registered in ip.user_ns):
  fn_name = f\"_elitis_paste_{uuid4().hex[:8]}\"  ← unique per button
  _recv(payload_json):
    mode \"b64\" → base64.b64decode() → save_sourced_image()
    mode \"url\" → fetch_url_bytes()  → save_sourced_image()
    mode \"empty\" / \"error\" → print status message

toBase64() chunks 8192 bytes to avoid JS call-stack overflow on
large clipboard images.
"""),

("Cell 3 — tune panels", """
elitis/notebook/tune.py  →  font_panel / text_panel / overlay_panel

Each panel renders ipywidgets sliders / dropdowns / colour pickers
that write directly to project.defaults.settings.<field>.value.

These mutations bypass BaseAppState.commit_field() — they go
straight to the model object.  No _autosave() fires here.

Save point: Cell 4 calls save_project() after render_all().
If the VM disconnects mid-tune before Cell 4, tune changes are lost.
This is intentional — tune is iterative preview work, not final data.
Reconnect, reload _PROJECT_JSON in Cell 1, re-run the tune cells.
"""),

("Cell 4 — render and save", """
Cell 4 does:
  shutil.rmtree(OUTPUT_DIR)     ← wipe previous render
  OUTPUT_DIR.mkdir()
  saved, warnings = renderer.render_all(project, font_manager,
                                         OUTPUT_DIR, …)
  save_project(project, _PROJECT_JSON)   ← persists last_output_path
  show_warnings(warnings)
  show_gallery(OUTPUT_DIR)

render_all stamps item.last_output_path after each file is written.
The save_project call after render ensures those paths survive.

shutil.rmtree means the stale-file deletion logic in render_all
(which checks item.last_output_path before writing) always sees
old.exists() == False in Colab — the rmtree already cleaned up.
The stale-file logic matters on desktop where OUTPUT_DIR persists.
"""),

("Cell 5 — zip export", """
Cell 5:
  images = sorted(OUTPUT_DIR.glob(\"*\"))
  with zipfile.ZipFile(zip_path, \"w\", ZIP_DEFLATED) as zf:
      for p in images:
          zf.write(p, p.name)   ← flat zip, no subdirectory
  files.download(str(zip_path))

The zip contains exactly what Cell 4 wrote — no re-render.
Filenames inside the zip are the bare stem+ext (e.g. 000_Zelda.png),
not the full path, so the zip extracts cleanly into any folder.

If Cell 4 was never run, OUTPUT_DIR.glob(\"*\") returns nothing
and Cell 5 raises RuntimeError before creating the zip.
"""),

("VM disconnect resilience — what survives", """
Saved on every image assignment (Cell 2):
  ✓ item.image_path
  ✓ item.image_hash

Saved after Cell 1:
  ✓ labels, origins, any image paths already in the uploaded JSON

Saved after Cell 4:
  ✓ item.last_output_path
  ✓ tune settings (font, text, overlay panel values)

NOT saved between Cells 3 and 4:
  ✗ tune settings changed in Cells 3a–3e
    (reconnect → Cell 1 → re-run tune cells → Cell 4)

The worst-case loss on an unexpected disconnect is tune settings
from the current iteration — image assignments are never lost once
Cell 2 has processed them.
"""),

]


# ---------------------------------------------------------------------------
# Track selector and main
# ---------------------------------------------------------------------------

TRACKS = {
    "1": ("Qt desktop",       QT_SECTIONS),
    "2": ("Jupyter / Colab",  NB_SECTIONS),
}


def main():
    _clear()
    print("  ELItis codebase tour")
    print("  " + "─" * 40)
    print()
    for key, (name, sections) in TRACKS.items():
        print(f"    {key}  {name}  ({len(sections)} sections)")
    print()
    print("    q  quit")
    print()
    print("  Choose track: ", end="", flush=True)

    while True:
        ch = _getch()
        if ch in (b"q", b"Q"):
            _clear()
            return
        key = ch.decode("utf-8", errors="ignore")
        if key in TRACKS:
            break

    name, sections = TRACKS[key]
    _run(sections)


if __name__ == "__main__":
    main()
