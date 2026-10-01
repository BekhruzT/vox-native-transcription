"""
Settings dialog for Input-STT.

Allows users to configure hotkey bindings and other settings.
"""

import ctypes
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QWidget,
    QMessageBox
)
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QKeySequence, QPaintEvent, QPainter, QPainterPath, QPen
from PySide6.QtCore import Qt, Signal, QSize

from ..config.settings import Settings
from ..core.hotkey_manager import HotkeyManager
from .system_tray import SystemTray, render_waveform_pixmap


@lru_cache(maxsize=1)
def _dialog_font_family() -> Optional[str]:
    """Load the bundled dialog font once per process."""
    font_path = Path(__file__).resolve().parent / "resources" / "fonts" / "BalsamiqSans-Regular.ttf"
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
    return families[0] if families else None


class InkPanel(QWidget):
    """Paint the softly offset, irregular outline around Hotkey settings."""

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the slate panel and its faint second contour."""
        bounds = self.rect().adjusted(2, 2, -6, -6)
        left, top, right, bottom = map(float, (bounds.left(), bounds.top(), bounds.right(), bounds.bottom()))
        outline = QPainterPath()
        outline.moveTo(left + 14, top)
        outline.lineTo(right - 11, top + 1)
        outline.quadTo(right, top, right, top + 12)
        outline.lineTo(right - 1, bottom - 13)
        outline.quadTo(right, bottom, right - 13, bottom)
        outline.lineTo(left + 11, bottom - 1)
        outline.quadTo(left, bottom, left, bottom - 11)
        outline.lineTo(left + 1, top + 13)
        outline.quadTo(left, top, left + 14, top)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(105, 152, 238, 92), 1))
        painter.drawPath(outline.translated(3, 3))
        painter.setBrush(QColor("#20293a"))
        painter.setPen(QPen(QColor("#566b91"), 2))
        painter.drawPath(outline)


class WaveFlourish(QWidget):
    """Show a small hand-drawn blue wave beside the Hotkey heading."""

    def sizeHint(self) -> QSize:
        """Reserve room for the wave without affecting the heading baseline."""
        return QSize(30, 20)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw a restrained two-crest wave."""
        wave = QPainterPath()
        wave.moveTo(1, 11)
        wave.cubicTo(6, 2, 9, 17, 15, 9)
        wave.cubicTo(20, 2, 24, 13, 29, 5)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#79aaff"), 2, Qt.SolidLine, Qt.RoundCap))
        painter.drawPath(wave)


class HotkeyEdit(QLineEdit):
    """
    Custom line edit for capturing hotkey combinations.
    
    When focused, captures key presses and displays the hotkey string.
    """
    
    hotkey_changed = Signal(str)
    
    def __init__(self, parent=None):
        """Initialize the hotkey edit."""
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("Click and press keys...")
        self.setAlignment(Qt.AlignCenter)
        self._hotkey = ""
        self._is_capturing = False
        self._modifiers = set()
        self._key = ""
    
    @property
    def hotkey(self) -> str:
        """Get the current hotkey string in pynput format."""
        return self._hotkey
    
    def set_hotkey(self, hotkey: str) -> None:
        """Set the hotkey string."""
        self._hotkey = hotkey
        self.setText(self._format_display(hotkey))
    
    def _format_display(self, hotkey: str) -> str:
        """Format hotkey for display (strip angle brackets, add spaces)."""
        # Remove angle brackets and format nicely
        display = hotkey.replace("<", "").replace(">", "")
        display = display.replace("+", " + ")
        # Replace cmd with Win for display
        display = display.replace("cmd", "Win")
        return display.title()
    
    def focusInEvent(self, event) -> None:
        """Handle focus in - start capturing."""
        super().focusInEvent(event)
        self._is_capturing = True
        self._modifiers = set()
        self._key = ""
        self.setStyleSheet("""
            QLineEdit {
                border: 2px solid #2e6cff;
                background: #161920;
                color: #eceff4;
                padding: 8px;
                border-radius: 8px;
            }
        """)
        self.setText("Press key combination...")
    
    def focusOutEvent(self, event) -> None:
        """Handle focus out - stop capturing."""
        super().focusOutEvent(event)
        self._is_capturing = False
        self.setStyleSheet("""
            QLineEdit {
                border: 2px solid #71a3fa;
                background: #161920;
                color: #eceff4;
                padding: 8px;
                border-radius: 8px;
            }
        """)
        if self._hotkey:
            self.setText(self._format_display(self._hotkey))
        else:
            self.setText("")
    
    def keyPressEvent(self, event) -> None:
        """Handle key press - capture hotkey in pynput format."""
        if not self._is_capturing:
            super().keyPressEvent(event)
            return
        
        # Track modifiers
        modifiers = event.modifiers()
        key = event.key()
        
        # Build modifier list in pynput format
        mod_parts = []
        if modifiers & Qt.ControlModifier:
            mod_parts.append("<ctrl>")
        if modifiers & Qt.AltModifier:
            mod_parts.append("<alt>")
        if modifiers & Qt.ShiftModifier:
            mod_parts.append("<shift>")
        if modifiers & Qt.MetaModifier:
            mod_parts.append("<cmd>")
        
        # Get key name
        key_name = ""
        if key not in (Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta):
            key_seq = QKeySequence(key)
            key_name = key_seq.toString().lower()
            
            # Special key name mappings for pynput
            key_map = {
                "space": "<space>",
                " ": "<space>",
                "return": "<enter>",
                "enter": "<enter>",
            }
            key_name = key_map.get(key_name, key_name)
        
        # Build hotkey string in pynput format
        if mod_parts and key_name:
            self._hotkey = "+".join(mod_parts + [key_name])
            self.setText(self._format_display(self._hotkey))
            self.hotkey_changed.emit(self._hotkey)
            
            # Auto-defocus after successful capture
            self.clearFocus()
        elif mod_parts:
            # Show current modifiers (display format)
            display_mods = [m.replace("<", "").replace(">", "").replace("cmd", "Win") for m in mod_parts]
            self.setText(" + ".join(display_mods).title() + " + ...")
    
    def keyReleaseEvent(self, event) -> None:
        """Handle key release."""
        if not self._is_capturing:
            super().keyReleaseEvent(event)


class SettingsDialog(QDialog):
    """
    Settings configuration dialog.
    
    Allows users to:
    - Configure the global hotkey
    - (Future: audio device, language, etc.)
    """
    
    def __init__(
        self,
        settings: Settings,
        hotkey_manager: Optional[HotkeyManager] = None,
        parent=None
    ):
        """
        Initialize the settings dialog.
        
        Args:
            settings: Settings manager instance.
            hotkey_manager: Optional HotkeyManager to update on save.
            parent: Parent widget.
        """
        super().__init__(parent)
        
        self._settings = settings
        self._hotkey_manager = hotkey_manager
        self._original_hotkey = settings.get("hotkey", "<cmd>+<alt>+j")
        
        self.setWindowTitle("Vox Settings")
        self.setWindowIcon(QIcon(render_waveform_pixmap(48, SystemTray.COLOR_IDLE, SystemTray.BG_COLOR)))
        self.setMinimumWidth(440)
        self.setModal(True)
        if font_family := _dialog_font_family():
            font = QFont(font_family)
            font.setPixelSize(14)
            self.setFont(font)

        if sys.platform == "win32":
            try:
                enabled = ctypes.c_int(1)
                dwm = ctypes.windll.dwmapi.DwmSetWindowAttribute
                hwnd = ctypes.c_void_p(int(self.winId()))
                if dwm(hwnd, 20, ctypes.byref(enabled), ctypes.sizeof(enabled)) != 0:
                    dwm(hwnd, 19, ctypes.byref(enabled), ctypes.sizeof(enabled))
            except (AttributeError, OSError):
                pass
        
        self.setStyleSheet("""
            QDialog {
                background: #161920;
            }
            QLabel {
                color: #eceff4;
            }
            QLabel#hotkeyTitle {
                font-size: 22px;
                color: #f2f4fa;
            }
            QPushButton {
                background: #2d3a53;
                color: #eceff4;
                border: 1px solid #52617c;
                border-radius: 5px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background: #3c4e6e;
            }
            QPushButton:pressed {
                background: #26344c;
            }
            QPushButton#saveButton {
                background: #2e6cff;
                color: #ffffff;
                border-color: #2e6cff;
            }
            QPushButton#saveButton:hover {
                background: #2563eb;
            }
            QPushButton#saveButton:pressed { background: #2255d7; }
        """)
        
        self._setup_ui()
        self.resize(460, self.sizeHint().height())
    
    def _setup_ui(self) -> None:
        """Setup the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)
        
        hotkey_panel = InkPanel()
        hotkey_layout = QVBoxLayout(hotkey_panel)
        hotkey_layout.setSpacing(8)
        hotkey_layout.setContentsMargins(19, 17, 19, 18)

        title_layout = QHBoxLayout()
        title_layout.setSpacing(7)
        title = QLabel("Hotkey")
        title.setObjectName("hotkeyTitle")
        title_layout.addWidget(title)
        title_layout.addWidget(WaveFlourish())
        title_layout.addStretch()
        hotkey_layout.addLayout(title_layout)
        
        self._hotkey_edit = HotkeyEdit()
        self._hotkey_edit.set_hotkey(self._original_hotkey)
        self._hotkey_edit.setStyleSheet("""
            QLineEdit {
                border: 2px solid #71a3fa;
                background: #161920;
                color: #eceff4;
                padding: 8px;
                border-radius: 8px;
            }
        """)
        
        hotkey_label = QLabel("Toggle Recording:")
        hotkey_layout.addWidget(hotkey_label)
        hotkey_layout.addWidget(self._hotkey_edit)
        
        help_label = QLabel("Click the field and press your desired key combination")
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #b5c2d9; font-size: 12px;")
        hotkey_layout.addWidget(help_label)
        
        layout.addWidget(hotkey_panel)
        
        layout.addStretch()
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        
        save_button = QPushButton("Save")
        save_button.setObjectName("saveButton")
        save_button.clicked.connect(self._on_save)
        button_layout.addWidget(save_button)
        
        layout.addLayout(button_layout)
    
    def _on_save(self) -> None:
        """Handle save button click."""
        new_hotkey = self._hotkey_edit.hotkey
        
        if not new_hotkey:
            QMessageBox.warning(
                self,
                "Invalid Hotkey",
                "Please set a valid hotkey combination."
            )
            return
        
        # Try to register the new hotkey
        if self._hotkey_manager:
            if not self._hotkey_manager.register(new_hotkey):
                QMessageBox.warning(
                    self,
                    "Hotkey Error",
                    f"Could not register hotkey '{new_hotkey}'.\n"
                    "It may be in use by another application."
                )
                # Restore original hotkey
                self._hotkey_manager.register(self._original_hotkey)
                return
        
        # Save settings
        self._settings.set("hotkey", new_hotkey)
        self._settings.save()
        
        self.accept()


