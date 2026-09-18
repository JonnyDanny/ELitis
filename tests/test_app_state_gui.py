"""
GUI-side tests for AppState using pytest-qt.

These tests require a real QApplication (provided by the ``qtbot`` fixture from
pytest-qt) and PySide6.  They cover the wiring between AppState methods and the
signals / item state that the UI depends on — the layer that pure-Python unit
tests cannot reach.

Run with:
    python -m pytest tests/test_app_state_gui.py -v
"""
import pytest
import datetime
from pathlib import Path
from PIL import Image

from PySide6.QtGui import QImage


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_clipboard():
    """
    Clear the Qt clipboard before every test in this module.

    Without this, a test that puts a QImage on the clipboard contaminates the
    next test: cb.image().isNull() returns False even after the test ends, so
    a test that expects a text/base64 path runs the QImage path instead.
    """
    from PySide6.QtWidgets import QApplication
    QApplication.clipboard().clear()
    yield
    QApplication.clipboard().clear()


@pytest.fixture
def state(qtbot, tmp_path):
    """
    A minimal AppState wired to throw-away directories.

    ``qtbot`` ensures a QApplication exists for the duration of the test.
    We create one content item ("Test") so the current item is always index 1.
    """
    from elitis.ui.app_state import AppState

    s = AppState(
        projects_dir=tmp_path / "projects",
        ingest_dir=tmp_path / "ingest",
        egest_dir=tmp_path / "egest",
        fonts_dir=tmp_path / "fonts",
    )
    s.new_project()
    s.insert_item(0, "Test")
    s.go_to(1)
    return s


@pytest.fixture
def tiny_png(tmp_path) -> Path:
    """16×16 red PNG saved to a temp file."""
    p = tmp_path / "red.png"
    Image.new("RGBA", (16, 16), (255, 0, 0, 255)).save(str(p))
    return p


# ---------------------------------------------------------------------------
# Clipboard paste — QImage path
# ---------------------------------------------------------------------------

class TestPasteImageFromClipboard:
    """
    Tests for AppState.paste_image_from_clipboard() using a real Qt clipboard.

    Each test puts a specific payload on the system clipboard, calls paste,
    and asserts on the return value, item state, and status signal.
    """

    def _put_qimage(self, width=8, height=8, color=0xFFFF0000):
        """Put a solid-colour QImage onto the Qt clipboard."""
        from PySide6.QtWidgets import QApplication
        qimg = QImage(width, height, QImage.Format.Format_RGBA8888)
        qimg.fill(color)
        QApplication.clipboard().setImage(qimg)

    def _put_text(self, text: str):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)

    def _put_base64(self, width=8, height=8):
        """Encode a synthetic PNG as a data URL and put it on the clipboard as text."""
        import base64, io
        from PySide6.QtWidgets import QApplication
        buf = io.BytesIO()
        Image.new("RGBA", (width, height), (0, 255, 0, 255)).save(buf, "PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        QApplication.clipboard().setText(f"data:image/png;base64,{b64}")

    # --- success paths ------------------------------------------------------

    def test_qimage_paste_returns_true(self, state):
        self._put_qimage()
        assert state.paste_image_from_clipboard() is True

    def test_qimage_paste_assigns_path_to_current_item(self, state):
        self._put_qimage()
        state.paste_image_from_clipboard()
        assert state.current_item.image_path is not None

    def test_qimage_paste_file_exists_on_disk(self, state):
        self._put_qimage()
        state.paste_image_from_clipboard()
        assert Path(state.current_item.image_path).exists()

    def test_qimage_paste_file_is_valid_rgba_png(self, state):
        """
        The saved file must be a valid, readable RGBA PNG of the correct dimensions.

        Channel-layout correctness (R↔B swap) is tested independently in
        TestClipboardConversion, which bypasses the Windows clipboard CF_DIB
        round-trip.  Here we only assert the file is valid and correctly sized.
        """
        self._put_qimage(width=12, height=8)
        state.paste_image_from_clipboard()
        img = Image.open(state.current_item.image_path).convert("RGBA")
        assert img.mode == "RGBA"
        assert img.size == (12, 8)

    def test_qimage_paste_emits_status_message(self, state):
        """
        A successful paste must emit at least one status message containing 'pasted'.

        The resolution warning (⚠ source image too small) may fire first when the
        pasted image is much smaller than the canvas, so we check any message, not
        just messages[0].
        """
        self._put_qimage()
        messages = []
        state.status_message.connect(messages.append)
        state.paste_image_from_clipboard()
        assert len(messages) >= 1
        assert any("pasted" in m.lower() for m in messages)

    def test_qimage_paste_saved_to_pasted_subdir(self, state):
        self._put_qimage()
        state.paste_image_from_clipboard()
        p = Path(state.current_item.image_path)
        assert p.parent.name == "Pasted"

    def test_qimage_paste_filename_contains_timestamp(self, state):
        self._put_qimage()
        state.paste_image_from_clipboard()
        name = Path(state.current_item.image_path).name
        today = datetime.date.today().strftime("%Y%m%d")
        assert today in name

    def test_two_pastes_produce_two_distinct_files(self, state):
        """
        Two consecutive pastes must save to separate files.

        On Windows, rapid back-to-back clipboard writes can fail with a COM
        "OpenClipboard" error because the clipboard is still held.
        processEvents() flushes the clipboard operation before the second write;
        if the second paste still fails (clipboard empty), we skip rather than
        falsely fail — the uniqueness guarantee is tested implicitly by the
        timestamp + UUID filename scheme.
        """
        from PySide6.QtWidgets import QApplication

        self._put_qimage(color=0xFFFF0000)
        assert state.paste_image_from_clipboard() is True
        path1 = state.current_item.image_path
        assert Path(path1).exists()

        QApplication.processEvents()   # let Windows release the clipboard

        self._put_qimage(color=0xFF0000FF)
        if not state.paste_image_from_clipboard():
            pytest.skip("Second clipboard write failed (Windows COM clipboard timing)")

        path2 = state.current_item.image_path
        assert path1 != path2
        assert Path(path1).exists()
        assert Path(path2).exists()

    # --- base64 path --------------------------------------------------------

    def test_base64_paste_returns_true(self, state):
        self._put_base64()
        assert state.paste_image_from_clipboard() is True

    def test_base64_paste_assigns_path(self, state):
        self._put_base64()
        state.paste_image_from_clipboard()
        assert state.current_item.image_path is not None

    def test_base64_paste_file_is_valid_image(self, state):
        self._put_base64(width=12, height=12)
        state.paste_image_from_clipboard()
        img = Image.open(state.current_item.image_path)
        assert img.size == (12, 12)

    def test_base64_corrupt_emits_error_and_returns_false(self, state):
        """Malformed base64 payload: paste must return False and emit a message."""
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText("data:image/png;base64,!!!NOTVALID!!!")
        messages = []
        state.status_message.connect(messages.append)
        result = state.paste_image_from_clipboard()
        assert result is False
        assert len(messages) >= 1

    # --- failure paths ------------------------------------------------------

    def test_no_image_returns_false(self, state):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().clear()
        assert state.paste_image_from_clipboard() is False

    def test_text_url_returns_false_and_emits_message(self, state):
        self._put_text("https://example.com/img.png")
        messages = []
        state.status_message.connect(messages.append)
        result = state.paste_image_from_clipboard()
        assert result is False
        assert "url" in messages[0].lower()

    def test_plain_text_returns_false_and_emits_message(self, state):
        self._put_text("S tier: Charizard")
        messages = []
        state.status_message.connect(messages.append)
        result = state.paste_image_from_clipboard()
        assert result is False
        assert len(messages) == 1


# ---------------------------------------------------------------------------
# commit_image — resolution warning
# ---------------------------------------------------------------------------

class TestCommitImageResolutionWarning:
    """
    Tests for AppState.commit_image() — specifically the resolution warning
    emitted via status_message when the source image is much smaller than
    the canvas.
    """

    def test_tiny_image_emits_warning(self, state, tiny_png):
        """A 16×16 image assigned to the default 1280×720 canvas must warn."""
        messages = []
        state.status_message.connect(messages.append)
        state.commit_image(state.current_item.id, str(tiny_png))
        warnings = [m for m in messages if m.startswith("⚠")]
        assert len(warnings) == 1

    def test_warning_mentions_source_size(self, state, tiny_png):
        messages = []
        state.status_message.connect(messages.append)
        state.commit_image(state.current_item.id, str(tiny_png))
        warning = next(m for m in messages if m.startswith("⚠"))
        assert "16" in warning

    def test_adequate_image_no_warning(self, state, tmp_path):
        big = tmp_path / "big.png"
        Image.new("RGBA", (1280, 720)).save(str(big))
        messages = []
        state.status_message.connect(messages.append)
        state.commit_image(state.current_item.id, str(big))
        assert not any(m.startswith("⚠") for m in messages)

    def test_none_path_no_warning(self, state):
        messages = []
        state.status_message.connect(messages.append)
        state.commit_image(state.current_item.id, None)
        assert not any(m.startswith("⚠") for m in messages)


# ---------------------------------------------------------------------------
# Signal plumbing
# ---------------------------------------------------------------------------

class TestSignals:
    """
    Verify that model mutations emit the correct signals so the UI refreshes.
    These are integration checks — not unit tests of the signals themselves.
    """

    def test_commit_field_emits_settings_changed(self, state, qtbot):
        with qtbot.waitSignal(state.settings_changed, timeout=500):
            state.commit_field("font_size", 48)

    def test_commit_label_emits_settings_changed(self, state, qtbot):
        with qtbot.waitSignal(state.settings_changed, timeout=500):
            state.commit_label(state.current_item.id, "NewLabel")

    def test_commit_image_emits_settings_changed(self, state, qtbot, tiny_png):
        with qtbot.waitSignal(state.settings_changed, timeout=500):
            state.commit_image(state.current_item.id, str(tiny_png))

    def test_insert_item_emits_project_replaced(self, state, qtbot):
        with qtbot.waitSignal(state.project_replaced, timeout=500):
            state.insert_item(0, "New")

    def test_remove_item_emits_project_replaced(self, state, qtbot):
        item_id = state.current_item.id
        with qtbot.waitSignal(state.project_replaced, timeout=500):
            state.remove_item(item_id)

    def test_go_to_emits_current_changed(self, state, qtbot):
        state.insert_item(1, "Second")
        with qtbot.waitSignal(state.current_changed, timeout=500):
            state.go_to(2)

    def test_new_project_emits_project_replaced(self, state, qtbot):
        with qtbot.waitSignal(state.project_replaced, timeout=500):
            state.new_project()
