"""Guard final transcript delivery against unfocused typing and duplicate chunks."""

import inspect
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QObject, Signal

from src.core.session import RecordingSession, RecordingWorker
from src.providers.base import RealtimeTranscriptionOutput, TranscriptionOutputType, TranscriptionStatus


class FakeWorker(QObject):
    """Provide worker signals without starting audio or network activity."""

    text_update = Signal(object)
    finished_recording = Signal()
    error = Signal(str)

    def __init__(self, **kwargs: object) -> None:
        super().__init__()

    def start(self) -> None:
        """Keep the test worker idle."""


class FakeDetector:
    """Expose a controlled focused target to the real session."""

    def __init__(self, target: tuple[int, ...] | None, unchanged: bool = True) -> None:
        self.target = target
        self.unchanged = unchanged

    def capture_text_target(self) -> tuple[int, ...] | None:
        """Return the target present when recording begins."""
        return self.target

    def is_same_text_target(self, target: tuple[int, ...]) -> bool:
        """Report whether the captured target still holds focus."""
        return self.unchanged and target == self.target


class FakeInjector:
    """Record delivery requests without touching the Windows clipboard or keyboard."""

    def __init__(self) -> None:
        self.deliveries: list[tuple[str, bool]] = []

    def inject(self, text: str) -> None:
        """Reject the old character typing path."""
        raise AssertionError(f"character typing was called with {text!r}")

    def deliver(self, text: str, paste: bool) -> bool:
        """Record final clipboard delivery and its paste decision."""
        self.deliveries.append((text, paste))
        return paste


def output(kind: TranscriptionOutputType, status: TranscriptionStatus, text: str) -> RealtimeTranscriptionOutput:
    """Build a provider event with a stable final chunk."""
    return RealtimeTranscriptionOutput(
        type=kind,
        chunks=[text] if text else [],
        latest_transcription=text,
        status=status,
        final_transcription=text if status == TranscriptionStatus.COMPLETE else "",
    )


class DeliveryTests(unittest.TestCase):
    """Exercise final delivery through the session's public start flow."""

    def make_session(self, target: tuple[int, ...] | None, unchanged: bool = True) -> tuple[RecordingSession, FakeInjector]:
        """Start a session with controlled dependencies."""
        self.assertIn("focus_detector", inspect.signature(RecordingSession).parameters)
        injector = FakeInjector()
        session = RecordingSession(recorder=None, provider=None, focus_detector=FakeDetector(target, unchanged), text_injector=injector)
        with patch("src.core.session.RecordingWorker", FakeWorker):
            session.start()
        return session, injector

    def test_cumulative_final_pastes_once(self) -> None:
        """A confirmed target receives the completed cumulative result once."""
        session, injector = self.make_session((1, 2))
        session._on_text_update(output(TranscriptionOutputType.CUMULATIVE, TranscriptionStatus.IN_PROGRESS, "hello"))
        session._on_text_update(output(TranscriptionOutputType.CUMULATIVE, TranscriptionStatus.COMPLETE, "hello world"))
        session._on_recording_finished()
        self.assertEqual(injector.deliveries, [("hello world", True)])

    def test_no_target_copies_only(self) -> None:
        """Desktop focus leaves the transcript available without sending a shortcut."""
        session, injector = self.make_session(None)
        session._on_text_update(output(TranscriptionOutputType.CUMULATIVE, TranscriptionStatus.COMPLETE, "open window"))
        session._on_recording_finished()
        self.assertEqual(injector.deliveries, [("open window", False)])

    def test_incremental_final_pastes_once(self) -> None:
        """Progressive chunks never type or repeat the final chunk."""
        session, injector = self.make_session((4,))
        session._on_text_update(output(TranscriptionOutputType.INCREMENTAL, TranscriptionStatus.IN_PROGRESS, "hello"))
        session._on_text_update(output(TranscriptionOutputType.INCREMENTAL, TranscriptionStatus.IN_PROGRESS, "hello world"))
        session._on_text_update(output(TranscriptionOutputType.INCREMENTAL, TranscriptionStatus.COMPLETE, "hello world"))
        session._on_recording_finished()
        self.assertEqual(injector.deliveries, [("hello world", True)])

    def test_changed_target_copies_only(self) -> None:
        """Losing the captured text target prevents automatic paste."""
        session, injector = self.make_session((7,), unchanged=False)
        session._on_text_update(output(TranscriptionOutputType.CUMULATIVE, TranscriptionStatus.COMPLETE, "keep this"))
        session._on_recording_finished()
        self.assertEqual(injector.deliveries, [("keep this", False)])

    def test_empty_transcript_does_not_replace_clipboard(self) -> None:
        """Silence does not replace the user's previous clipboard content."""
        session, injector = self.make_session((7,))
        session._on_text_update(output(TranscriptionOutputType.CUMULATIVE, TranscriptionStatus.COMPLETE, ""))
        session._on_recording_finished()
        self.assertEqual(injector.deliveries, [])

    def test_error_without_complete_does_not_replace_clipboard(self) -> None:
        """A provider failure cannot publish unfinished partial text."""
        session, injector = self.make_session((7,))
        session._on_text_update(output(TranscriptionOutputType.CUMULATIVE, TranscriptionStatus.IN_PROGRESS, "unfinished"))
        session._on_text_update(output(TranscriptionOutputType.CUMULATIVE, TranscriptionStatus.ERROR, "unfinished"))
        session._on_recording_finished()
        self.assertEqual(injector.deliveries, [])

    def test_worker_error_does_not_become_synthetic_complete(self) -> None:
        """The worker must not convert a provider error into a completed transcript."""
        provider = Mock()
        provider.transcribe_realtime.return_value = [output(TranscriptionOutputType.CUMULATIVE, TranscriptionStatus.ERROR, "unfinished")]
        worker = RecordingWorker(recorder=None, provider=provider, silence_detector=None)
        statuses: list[TranscriptionStatus] = []
        worker.text_update.connect(lambda event: statuses.append(event.status))
        worker._run_realtime()
        self.assertEqual(statuses, [TranscriptionStatus.ERROR])


if __name__ == "__main__":
    unittest.main()
