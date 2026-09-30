"""Check UI Automation focus classification without operating the live desktop."""

import importlib
import importlib.util
import unittest


class FakeValuePattern:
    """Represent a UI Automation value pattern."""

    def __init__(self, read_only: bool) -> None:
        self.IsReadOnly = read_only


class FakeControl:
    """Represent one focused UI Automation control."""

    def __init__(self, kind: str, identity: tuple[int, ...], read_only: bool | None = None) -> None:
        self.ControlTypeName = kind
        self.identity = identity
        self.read_only = read_only

    def GetValuePattern(self) -> FakeValuePattern | None:
        """Return an optional editable value pattern."""
        return FakeValuePattern(self.read_only) if self.read_only is not None else None

    def GetRuntimeId(self) -> tuple[int, ...]:
        """Return the control's runtime identity."""
        return self.identity


class FakeAutomation:
    """Return the current control from a controlled focus state."""

    def __init__(self, control: FakeControl | None) -> None:
        self.control = control

    def GetFocusedControl(self) -> FakeControl | None:
        """Expose the current focused control."""
        return self.control


class FocusDetectorTests(unittest.TestCase):
    """Check the target evidence and same-target recheck."""

    def detector_class(self) -> type:
        """Load the detector after asserting that the delivery feature exists."""
        self.assertIsNotNone(importlib.util.find_spec("src.core.focus_detector"))
        return importlib.import_module("src.core.focus_detector").FocusDetector

    def test_focus_target_classification(self) -> None:
        """Editable controls are accepted while read-only and unknown controls are refused."""
        cases = [
            (FakeControl("EditControl", (1,)), (1,)),
            (FakeControl("DocumentControl", (2,)), None),
            (FakeControl("DocumentControl", (8,), read_only=False), (8,)),
            (FakeControl("GroupControl", (3,), read_only=False), (3,)),
            (FakeControl("EditControl", (4,), read_only=True), None),
            (FakeControl("GroupControl", (5,)), None),
            (FakeControl("TextControl", (6,)), None),
            (None, None),
        ]
        for control, expected in cases:
            with self.subTest(control=control):
                self.assertEqual(self.detector_class()(FakeAutomation(control)).capture_text_target(), expected)

    def test_changed_focus_is_rejected(self) -> None:
        """A different runtime identity cannot receive the automatic paste."""
        automation = FakeAutomation(FakeControl("EditControl", (1,)))
        detector = self.detector_class()(automation)
        target = detector.capture_text_target()
        automation.control = FakeControl("EditControl", (2,))
        self.assertFalse(detector.is_same_text_target(target))


if __name__ == "__main__":
    unittest.main()
