"""Identify a focused editable control for safe automatic paste."""

import sys
from typing import Any


class FocusDetector:
    """Capture and recheck a focused text control through Windows UI Automation."""

    def __init__(self, automation: Any | None = None) -> None:
        """Use a supplied automation provider or load the Windows provider."""
        if automation is not None:
            self._automation = automation
        elif sys.platform == "win32":
            try:
                import uiautomation
                self._automation = uiautomation
            except ImportError:
                self._automation = None
        else:
            self._automation = None

    def capture_text_target(self) -> tuple[int, ...] | None:
        """Return the focused editable control's stable runtime identity."""
        if self._automation is None:
            return None
        try:
            control = self._automation.GetFocusedControl()
            if control is None:
                return None
            try:
                value_pattern = control.GetValuePattern()
            except Exception:
                value_pattern = None
            if value_pattern is not None:
                try:
                    if value_pattern.IsReadOnly:
                        return None
                except Exception:
                    return None
            elif control.ControlTypeName != "EditControl":
                return None
            identity = tuple(control.GetRuntimeId())
            return identity or None
        except Exception as exc:
            print(f"[FOCUS] Could not inspect focused control: {exc}")
            return None

    def is_same_text_target(self, target: tuple[int, ...]) -> bool:
        """Confirm that the captured editable control still has focus."""
        return self.capture_text_target() == target
