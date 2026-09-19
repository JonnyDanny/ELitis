"""
CLI operating modes.

Usage:
  python -m elitis                          # GUI (interactive)
  python -m elitis --batch                  # GUI batch export dialog
  python -m elitis --cli input.csv          # CLI batch from CSV/JSON
  python -m elitis --cli --interactive      # CLI interactive (prompt per item)
"""
from __future__ import annotations
from pathlib import Path
import sys


def run_cli_batch(
    input_path: Path,
    projects_dir: Path,
    egest_dir: Path,
    fonts_dir: Path,
    fmt: str = "PNG",
    output_dir: Path | None = None,
):
    from elitis.core import data_io, renderer
    from elitis.core.font_manager import FontManager
    from elitis.core.models import Project

    font_manager = FontManager(fonts_dir)

    # Load or import
    if input_path.suffix.lower() == ".json":
        project = data_io.load_project(input_path)
    else:
        labels = data_io.import_labels(input_path)
        if not labels:
            print(f"No labels found in {input_path}", file=sys.stderr)
            sys.exit(1)
        project, saved = data_io.project_from_labels(
            labels, input_path.stem, str(egest_dir), projects_dir
        )
        print(f"Project saved to: {saved}")

    out_dir = output_dir or egest_dir / project.name
    items = project.content_items
    print(f"Rendering {len(items)} items to {out_dir} ...")

    def progress(done, total, path):
        print(f"  [{done}/{total}] {path.name}")

    saved_paths, warnings = renderer.render_all(project, font_manager, out_dir, fmt=fmt, on_progress=progress)
    if warnings:
        for w in warnings:
            print(f"  [{w.severity.upper()}] {w.code}: {w.message}", file=sys.stderr)
    print(f"\nDone. {len(saved_paths)} files saved.")


def run_cli_interactive(
    projects_dir: Path,
    egest_dir: Path,
    fonts_dir: Path,
):
    from elitis.core import data_io, renderer
    from elitis.core.font_manager import FontManager
    from elitis.core.models import Project

    font_manager = FontManager(fonts_dir)
    print("ELItis — Interactive CLI")
    print("------------------------")

    name = input("Project name [untitled]: ").strip() or "untitled"
    project = Project.new(name, str(egest_dir / name))

    print("Enter labels (one per line, empty line to finish):")
    while True:
        try:
            line = input(f"  Item {len(project.content_items) + 1}: ").strip()
        except EOFError:
            break
        if not line:
            break
        project.add_item(line)

    if not project.content_items:
        print("No items entered. Exiting.")
        return

    # Save project
    projects_dir.mkdir(parents=True, exist_ok=True)
    project_path = projects_dir / f"{name}.json"
    data_io.save_project(project, project_path)
    print(f"Project saved: {project_path}")

    proceed = input(f"\nRender {len(project.content_items)} items? [Y/n]: ").strip().lower()
    if proceed in ("n", "no"):
        return

    out_dir = egest_dir / name
    saved, warnings = renderer.render_all(
        project, font_manager, out_dir,
        on_progress=lambda d, t, p: print(f"  [{d}/{t}] {p.name}")
    )
    if warnings:
        for w in warnings:
            print(f"  [{w.severity.upper()}] {w.code}: {w.message}", file=sys.stderr)
    print(f"\nDone. {len(saved)} files in {out_dir}")
