"""Focused rendering and interaction checks for the Hotkey settings dialog."""

import ctypes
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton

from src.config.settings import Settings
from src.ui.settings_dialog import SettingsDialog


class RecordingHotkeyManager:
    """Record registration requests without creating a global keyboard hook."""

    def __init__(self) -> None:
        """Start with no registration requests."""
        self.registered: list[str] = []

    def register(self, hotkey: str) -> bool:
        """Accept and record a requested hotkey."""
        self.registered.append(hotkey)
        return True


class SettingsDialogTests(unittest.TestCase):
    """Check the real dialog with isolated settings persistence."""

    @classmethod
    def setUpClass(cls) -> None:
        """Create the Qt application once for this test class."""
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        """Open a dialog backed by a temporary settings file."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.settings = Settings(Path(self.temp_dir.name))
        self.manager = RecordingHotkeyManager()
        self.dialog = SettingsDialog(self.settings, self.manager)
        self.dialog.show()
        self.app.processEvents()
        self.addCleanup(self.dialog.close)

    def _assert_helper_fits(self) -> None:
        """Check rendered text height and client geometry."""
        helper = next(label for label in self.dialog.findChildren(QLabel) if label.text().startswith("Click the field"))
        text_height = QFontMetrics(helper.font()).boundingRect(0, 0, helper.width(), 1000, Qt.TextWordWrap, helper.text()).height()
        self.assertGreaterEqual(helper.height(), text_height, f"helper height {helper.height()} < required text height {text_height}")
        self.assertLessEqual(helper.mapTo(self.dialog, helper.rect().bottomRight()).y(), self.dialog.contentsRect().bottom(), "helper extends below client area")
        self.assertLessEqual(helper.mapTo(self.dialog, helper.rect().bottomRight()).x(), self.dialog.contentsRect().right(), "helper extends beyond client width")

    def _assert_helper_at_scale(self, target: float) -> None:
        """Check helper geometry in a process with the requested effective Qt scale."""
        if os.environ.get("VOX_DIALOG_SCALE_CHILD") == "1":
            self.assertAlmostEqual(self.app.primaryScreen().devicePixelRatio(), target, delta=0.02)
            self._assert_helper_fits()
            return
        host_ratio = self.app.primaryScreen().devicePixelRatio() / float(os.environ.get("QT_SCALE_FACTOR", "1"))
        env = dict(os.environ, QT_SCALE_FACTOR=str(target / host_ratio), VOX_DIALOG_SCALE_CHILD="1")
        result = subprocess.run(
            [sys.executable, "-m", "unittest", f"tests.test_settings_dialog.SettingsDialogTests.{self._testMethodName}", "-v"],
            cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dialog_uses_vox_identity_and_focus_palette(self) -> None:
        """The dialog presents Vox branding and a clear blue capture focus."""
        self.assertEqual(self.dialog.windowTitle(), "Vox Settings")
        self.assertFalse(self.dialog.windowIcon().isNull())
        self.assertGreaterEqual(self.dialog.width(), 440)
        self.assertIn("#161920", self.dialog.styleSheet().lower())
        self.assertEqual(self.dialog.font().family(), "Balsamiq Sans")
        self.assertTrue(any(label.text() == "Hotkey" for label in self.dialog.findChildren(QLabel)))
        self.assertIn("#2e6cff", self.dialog.styleSheet().lower())
        self.dialog._hotkey_edit.setFocus()
        self.app.processEvents()
        self.assertIn("#2e6cff", self.dialog._hotkey_edit.styleSheet().lower())
        for widget in (self.dialog._hotkey_edit, *self.dialog.findChildren(QPushButton)):
            bottom_right = widget.mapTo(self.dialog, widget.rect().bottomRight())
            self.assertLessEqual(bottom_right.x(), self.dialog.contentsRect().right(), f"{widget} extends beyond client width")
            self.assertLessEqual(bottom_right.y(), self.dialog.contentsRect().bottom(), f"{widget} extends below client area")
        if sys.platform == "win32":
            dark = ctypes.c_int()
            result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                ctypes.c_void_p(int(self.dialog.winId())), 20, ctypes.byref(dark), ctypes.sizeof(dark)
            )
            if result == 0:
                self.assertEqual(dark.value, 1, "native title bar did not request immersive dark mode")

    def test_helper_fits_default_dialog_at_100_percent(self) -> None:
        """The full helper sentence fits at the baseline scale."""
        self.assertEqual(next(label for label in self.dialog.findChildren(QLabel) if label.text().startswith("Click the field")).text(), "Click the field and press your desired key combination")
        self._assert_helper_at_scale(1.0)

    def test_save_hover_retains_legible_contrast(self) -> None:
        """The Save hover color keeps its white label readable."""
        match = re.search(r"QPushButton#saveButton:hover\s*\{\s*background:\s*(#[0-9a-fA-F]{6})", self.dialog.styleSheet())
        self.assertIsNotNone(match, "Save hover color is missing")
        color = QColor(match.group(1))
        channels = (color.redF(), color.greenF(), color.blueF())
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
        luminance = sum(component * weight for component, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
        contrast = 1.05 / (luminance + 0.05)
        self.assertGreaterEqual(contrast, 4.5, f"Save hover contrast {contrast:.2f}:1 on {color.name()}")

    def test_helper_fits_default_dialog_at_125_percent(self) -> None:
        """The full helper sentence fits when Qt scales the entire dialog."""
        self._assert_helper_at_scale(1.25)

    def test_capture_and_save_preserve_behavior(self) -> None:
        """Saving a captured combination registers and persists it."""
        self.dialog._hotkey_edit.setFocus()
        self.app.processEvents()
        QTest.keyClick(self.dialog._hotkey_edit, Qt.Key_K, Qt.ControlModifier | Qt.ShiftModifier)
        self.app.processEvents()
        self.assertEqual(self.dialog._hotkey_edit.hotkey, "<ctrl>+<shift>+k")
        next(button for button in self.dialog.findChildren(QPushButton) if button.text() == "Save").click()
        self.assertEqual(self.dialog.result(), QDialog.Accepted)
        self.assertEqual(self.manager.registered, ["<ctrl>+<shift>+k"])
        self.assertEqual(Settings(Path(self.temp_dir.name)).get("hotkey"), "<ctrl>+<shift>+k")

    def test_cancel_preserves_saved_hotkey(self) -> None:
        """Cancelling a captured combination leaves persistence untouched."""
        original = self.settings.get("hotkey")
        self.dialog._hotkey_edit.setFocus()
        self.app.processEvents()
        QTest.keyClick(self.dialog._hotkey_edit, Qt.Key_K, Qt.ControlModifier | Qt.ShiftModifier)
        next(button for button in self.dialog.findChildren(QPushButton) if button.text() == "Cancel").click()
        self.assertEqual(self.dialog.result(), QDialog.Rejected)
        self.assertEqual(self.manager.registered, [])
        self.assertEqual(Settings(Path(self.temp_dir.name)).get("hotkey"), original)
