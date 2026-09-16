"""
Entry point for ELItis.

Modes:
  (no args)              → GUI interactive
  --batch                → GUI, opens batch export dialog on launch
  --cli <file>           → CLI batch from CSV/TXT/JSON
  --cli --interactive    → CLI interactive prompts
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path


# Project-root resolution: ELItis/ lives next to this package
_ROOT = Path(__file__).parent.parent.resolve()

FONTS_DIR    = _ROOT / "Fonts"
INGEST_DIR   = _ROOT / "Ingest"
EGEST_DIR    = _ROOT / "Egest"
PROJECTS_DIR = _ROOT / "Projects"


def _ensure_dirs():
    for d in (FONTS_DIR, INGEST_DIR / "Images", INGEST_DIR / "Pasted", EGEST_DIR, PROJECTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def run_gui(batch_mode: bool = False):
    from PySide6.QtWidgets import QApplication
    from elitis.ui.theme import stylesheet
    from elitis.ui.app_state import AppState
    from elitis.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("ELItis")
    app.setStyleSheet(stylesheet())

    state = AppState(
        projects_dir=PROJECTS_DIR,
        ingest_dir=INGEST_DIR,
        egest_dir=EGEST_DIR,
        fonts_dir=FONTS_DIR,
    )
    state.font_manager.register_with_qt()

    window = MainWindow(state)
    window.show()

    if batch_mode:
        # Trigger batch export dialog after UI is shown
        from PySide6.QtCore import QTimer
        QTimer.singleShot(200, lambda: _gui_batch_dialog(state, window))

    sys.exit(app.exec())


def _gui_batch_dialog(state, parent):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    if not state.project.content_items:
        QMessageBox.information(parent, "Batch export", "No items in project.")
        return
    out_dir, _ = QFileDialog.getExistingDirectory(
        parent, "Select output folder", str(state.egest_dir)
    )
    if out_dir:
        state.project.output_dir = out_dir
        saved = state.export_batch()
        QMessageBox.information(parent, "Done", f"Exported {len(saved)} images to:\n{out_dir}")


def main():
    _ensure_dirs()

    parser = argparse.ArgumentParser(prog="elitis", description="Tier list thumbnail generator")
    parser.add_argument("--batch",       action="store_true", help="Start in batch export mode")
    parser.add_argument("--cli",         action="store_true", help="Run in CLI mode (no GUI)")
    parser.add_argument("--interactive", action="store_true", help="CLI interactive prompts")
    parser.add_argument("--format",      default="PNG",       help="Output format: PNG or JPEG")
    parser.add_argument("--output",      default=None,        help="Output directory")
    parser.add_argument("input",         nargs="?",           help="Input CSV/TXT/JSON (CLI mode)")
    args = parser.parse_args()

    if args.cli:
        if args.interactive or not args.input:
            from elitis.cli.runner import run_cli_interactive
            run_cli_interactive(PROJECTS_DIR, EGEST_DIR, FONTS_DIR)
        else:
            from elitis.cli.runner import run_cli_batch
            run_cli_batch(
                input_path=Path(args.input),
                projects_dir=PROJECTS_DIR,
                egest_dir=EGEST_DIR,
                fonts_dir=FONTS_DIR,
                fmt=args.format.upper(),
                output_dir=Path(args.output) if args.output else None,
            )
    else:
        run_gui(batch_mode=args.batch)


if __name__ == "__main__":
    main()
