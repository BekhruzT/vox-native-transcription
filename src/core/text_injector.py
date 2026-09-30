"""Deliver final transcripts through the clipboard and optional paste shortcut."""

import ctypes
import sys
import time
from ctypes import wintypes

from pynput.keyboard import Controller, Key
from PySide6.QtWidgets import QApplication


GMEM_MOVEABLE = 0x0002
CF_UNICODETEXT = 13


class TextInjector:
    """Copy completed text and optionally paste it once."""

    def __init__(self) -> None:
        """Create the keyboard shortcut controller."""
        self._keyboard = Controller()

    def deliver(self, text: str, paste: bool) -> bool:
        """Copy final text and optionally paste into the confirmed target."""
        if not text:
            return False
        try:
            copied = self._copy_to_clipboard(text)
        except Exception as exc:
            print(f"[INJECTOR] Clipboard write failed; paste skipped: {exc}")
            return False
        if not copied:
            print("[INJECTOR] Clipboard write failed; paste skipped")
            return False
        if not paste:
            return False
        try:
            self._keyboard.press(Key.ctrl)
            try:
                self._keyboard.press("v")
                self._keyboard.release("v")
            finally:
                self._keyboard.release(Key.ctrl)
        except Exception as exc:
            print(f"[INJECTOR] Paste shortcut failed; transcription remains on clipboard: {exc}")
            return False
        return True

    def _copy_to_clipboard(self, text: str) -> bool:
        """Publish text for other processes before the Qt event loop resumes."""
        if sys.platform != "win32":
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            return clipboard.text() == text

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE
        user32.CloseClipboard.restype = wintypes.BOOL
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]

        buffer = ctypes.create_unicode_buffer(text)
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, ctypes.sizeof(buffer))
        if not handle:
            return False
        try:
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                return False
            ctypes.memmove(pointer, buffer, ctypes.sizeof(buffer))
            kernel32.GlobalUnlock(handle)
            for _ in range(8):
                if user32.OpenClipboard(None):
                    break
                time.sleep(0.01)
            else:
                return False
            try:
                if not user32.EmptyClipboard() or not user32.SetClipboardData(CF_UNICODETEXT, handle):
                    return False
                handle = None
                return True
            finally:
                user32.CloseClipboard()
        finally:
            if handle:
                kernel32.GlobalFree(handle)
