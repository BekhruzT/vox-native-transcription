"""Check that a recording that cannot start tells the user instead of failing silently."""

import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

from src.ui.app import STTApplication
from src.ui.system_tray import SystemTray


class SessionErrorToastTests(unittest.TestCase):
    """Start a recording through the real app wiring with no speech provider configured."""

    @classmethod
    def setUpClass(cls) -> None:
        """Create the Qt application once."""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def test_missing_api_keys_show_error_toast(self) -> None:
        """Pressing the hotkey without API keys shows the error on the toast instead of nothing."""
        appdata = tempfile.TemporaryDirectory()
        self.addCleanup(appdata.cleanup)
        self.enterContext(patch.dict(os.environ, {"APPDATA": appdata.name}))
        for name in ("AudioRecorder", "HotkeyManager"):
            self.enterContext(patch(f"src.ui.app.{name}"))
        for name in ("ElevenLabsProvider", "OpenAIProvider"):
            self.enterContext(patch(f"src.ui.app.{name}", side_effect=ValueError("API key is required")))
        self.enterContext(patch.object(STTApplication, "_init_overlays"))
        self.enterContext(patch.object(SystemTray, "show"))
        stt = STTApplication()
        self.assertTrue(stt.initialize())
        stt._toast = Mock()
        stt._on_toggle_recording()
        stt._toast.show_toast.assert_called_once_with("STT provider not configured. Set OPENAI_API_KEY.")
        stt._toast.hide_toast.assert_not_called()


if __name__ == "__main__":
    unittest.main()
