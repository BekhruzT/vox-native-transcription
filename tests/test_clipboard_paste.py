"""Check transcript clipboard delivery with controlled keyboard and clipboard boundaries."""

import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from pynput.keyboard import Key
from PySide6.QtWidgets import QApplication

from src.core.text_injector import TextInjector


class FakeKeyboard:
    """Record the keyboard events sent by the real injector."""

    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def press(self, key: object) -> None:
        """Record a key down event."""
        self.events.append(("down", key))

    def release(self, key: object) -> None:
        """Record a key up event."""
        self.events.append(("up", key))


class ClipboardPasteTests(unittest.TestCase):
    """Check clipboard lifetime and the single paste shortcut."""

    def test_deliver_uses_clipboard_and_one_paste(self) -> None:
        """The full result stays copied after one automatic Ctrl+V."""
        injector = TextInjector()
        injector._keyboard = FakeKeyboard()
        transcript = ("A longer line with punctuation, café, and 漢字.\n" * 80).strip()
        self.assertTrue(hasattr(TextInjector, "deliver"))
        with patch.object(injector, "_copy_to_clipboard", return_value=True) as copy:
            self.assertTrue(injector.deliver(transcript, paste=True))
        copy.assert_called_once_with(transcript)
        self.assertEqual(injector._keyboard.events, [("down", Key.ctrl), ("down", "v"), ("up", "v"), ("up", Key.ctrl)])

    def test_deliver_without_target_never_sends_keys(self) -> None:
        """The fallback copies text and leaves the keyboard untouched."""
        injector = TextInjector()
        injector._keyboard = FakeKeyboard()
        self.assertTrue(hasattr(TextInjector, "deliver"))
        with patch.object(injector, "_copy_to_clipboard", return_value=True) as copy:
            self.assertFalse(injector.deliver("manual paste", paste=False))
        copy.assert_called_once_with("manual paste")
        self.assertEqual(injector._keyboard.events, [])

    def test_clipboard_failure_never_pastes_stale_text(self) -> None:
        """A failed copy cannot paste the previous clipboard contents."""
        injector = TextInjector()
        injector._keyboard = FakeKeyboard()
        with patch.object(injector, "_copy_to_clipboard", return_value=False) as copy:
            self.assertFalse(injector.deliver("new transcript", paste=True))
        copy.assert_called_once_with("new transcript")
        self.assertEqual(injector._keyboard.events, [])

    @unittest.skipUnless(sys.platform == "win32" and os.getenv("VOX_TEST_REAL_CLIPBOARD") == "1", "requires the live Windows clipboard")
    def test_windows_clipboard_visible_before_event_loop_resumes(self) -> None:
        """A separate process can read the transcript while Vox's Qt thread is busy."""
        app = QApplication.instance() or QApplication([])
        injector = TextInjector()
        original = app.clipboard().text()
        transcript = "Hello. Can you do ABC 123? Go ahead."
        try:
            self.assertTrue(injector._copy_to_clipboard("https://github.com/BekhruzT/talking-head-glb"))
            self.assertFalse(injector.deliver(transcript, paste=False))
            observed = subprocess.run(["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard -Raw"], capture_output=True, text=True, check=True)
            self.assertEqual(observed.stdout.strip(), transcript)
        finally:
            self.assertTrue(injector._copy_to_clipboard(original))


if __name__ == "__main__":
    unittest.main()
