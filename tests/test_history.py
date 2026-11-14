"""Check that finished transcriptions are kept on disk and recoverable from the tray."""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication

from src.config.history import History
from src.config.settings import Settings
from src.ui.app import STTApplication
from src.ui.system_tray import SystemTray


def menu_action(tray: SystemTray, label: str) -> QAction:
    """Find a top-level tray menu action by its label."""
    return next(action for action in tray.contextMenu().actions() if action.text() == label)


def recent_labels(tray: SystemTray) -> list[str]:
    """List the labels shown in the tray's Recent submenu."""
    return [action.text() for action in menu_action(tray, "Recent").menu().actions()]


class HistoryStoreTests(unittest.TestCase):
    """Exercise the history store against a temporary settings folder."""

    def setUp(self) -> None:
        """Give each test an empty folder for history.json."""
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.file = self.folder / "history.json"

    def test_limits_keep_twenty_and_show_ten_newest(self) -> None:
        """Twenty-five adds keep twenty on disk and show the ten newest first."""
        history = History(self.folder)
        for index in range(25):
            history.add(f"note {index}")
        self.assertEqual((len(json.loads(self.file.read_text(encoding="utf-8"))), history.recent()), (20, [f"note {index}" for index in range(24, 14, -1)]))

    def test_entries_older_than_seven_days_are_dropped_on_load(self) -> None:
        """An eight-day-old entry is gone after reload while a fresh one survives."""
        now = time.time()
        self.file.write_text(json.dumps([{"text": "fresh", "time": now}, {"text": "stale", "time": now - 8 * 24 * 3600}]), encoding="utf-8")
        self.assertEqual(History(self.folder).recent(), ["fresh"])

    def test_restart_loads_saved_entries(self) -> None:
        """A new store on the same folder sees what the previous one saved."""
        history = History(self.folder)
        history.add("first")
        history.add("second")
        self.assertEqual(History(self.folder).recent(), ["second", "first"])

    def test_empty_and_whitespace_text_add_nothing(self) -> None:
        """Silence never becomes a history entry."""
        history = History(self.folder)
        history.add("")
        history.add(" \n\t ")
        self.assertEqual((history.recent(), self.file.exists()), ([], False))

    def test_damaged_file_loads_empty_and_later_adds_save(self) -> None:
        """Missing, invalid, or wrongly shaped files load empty without blocking new saves."""
        for name, content in (("missing", None), ("invalid json", "{not json"), ("wrong shape", '{"text": "x"}'), ("wrong types", '[{"text": 5, "time": 1}, {"time": 1}]')):
            with self.subTest(name):
                self.file.unlink(missing_ok=True)
                if content is not None:
                    self.file.write_text(content, encoding="utf-8")
                history = History(self.folder)
                loaded = history.recent()
                history.add("hello")
                self.assertEqual((loaded, History(self.folder).recent()), ([], ["hello"]))

    def test_fresh_install_saves_history(self) -> None:
        """Settings without a settings.json default to saving history."""
        self.assertIs(Settings(config_dir=self.folder).get("save_history"), True)


class TrayRecentTests(unittest.TestCase):
    """Exercise the tray's Recent submenu without showing the tray."""

    @classmethod
    def setUpClass(cls) -> None:
        """Create the Qt application once for the tray tests."""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def test_long_text_previews_one_line_and_copies_in_full(self) -> None:
        """A 300-character entry previews on one short line and copies all of it."""
        text = "line one\n" * 33 + "end"
        tray = SystemTray()
        tray.set_recent([text])
        action = menu_action(tray, "Recent").menu().actions()[0]
        with patch("src.ui.system_tray.QApplication") as application:
            action.trigger()
        self.assertEqual((len(text), "\n" in action.text(), len(action.text()) <= 60), (300, False, True))
        application.clipboard.return_value.setText.assert_called_once_with(text)

    def test_ampersand_is_escaped_in_preview(self) -> None:
        """An ampersand shows literally instead of becoming a menu mnemonic."""
        tray = SystemTray()
        tray.set_recent(["Tom & Jerry"])
        self.assertEqual(recent_labels(tray), ["Tom && Jerry"])


class AppHistoryTests(unittest.TestCase):
    """Drive history through the real application wiring with hardware and providers patched out."""

    @classmethod
    def setUpClass(cls) -> None:
        """Create the Qt application once for the app tests."""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        """Initialize the app against a temporary APPDATA folder."""
        appdata = tempfile.TemporaryDirectory()
        self.addCleanup(appdata.cleanup)
        self.enterContext(patch.dict(os.environ, {"APPDATA": appdata.name}))
        for name in ("AudioRecorder", "ElevenLabsProvider", "OpenAIProvider", "HotkeyManager"):
            self.enterContext(patch(f"src.ui.app.{name}"))
        self.enterContext(patch.object(STTApplication, "_init_overlays"))
        self.enterContext(patch.object(SystemTray, "show"))
        self.folder = Path(appdata.name) / "InputSTT"
        self.stt = STTApplication()
        self.assertTrue(self.stt.initialize())
        self.session = self.stt._create_session()
        self.tray = self.stt._system_tray

    def test_completed_transcription_is_first_recent_entry(self) -> None:
        """Finishing a dictation puts its text at the top of Recent."""
        self.session.transcription_complete.emit("hello world")
        self.assertEqual(recent_labels(self.tray)[0], "hello world")

    def test_disabling_save_history_forgets_and_persists(self) -> None:
        """Unchecking Save history deletes the file, empties Recent, stops saving, and is remembered."""
        self.session.transcription_complete.emit("hello world")
        menu_action(self.tray, "Save history").trigger()
        self.session.transcription_complete.emit("after")
        settings = json.loads((self.folder / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(((self.folder / "history.json").exists(), recent_labels(self.tray), menu_action(self.tray, "Recent").isEnabled(), settings["save_history"]), (False, [], False, False))

    def test_clear_history_empties_recent_and_deletes_file(self) -> None:
        """Clear history removes every entry from the menu and the disk."""
        self.session.transcription_complete.emit("hello world")
        menu_action(self.tray, "Clear history").trigger()
        self.assertEqual(((self.folder / "history.json").exists(), recent_labels(self.tray), menu_action(self.tray, "Recent").isEnabled()), (False, [], False))


if __name__ == "__main__":
    unittest.main()
