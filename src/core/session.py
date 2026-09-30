"""Coordinate recording, transcription, and final clipboard delivery."""

import io
import wave
from enum import Enum, auto
from typing import Any, Optional

from PySide6.QtCore import QObject, Signal, QThread

from ..providers.base import (
    GenAIProvider,
    RealtimeTranscriptionOutput,
    TranscriptionOutputType,
    TranscriptionStatus,
)
from .focus_detector import FocusDetector
from .text_injector import TextInjector


class SessionState(Enum):
    """Recording session states."""
    IDLE = auto()
    RECORDING = auto()
    PROCESSING = auto()


class RecordingWorker(QThread):
    """Record audio and stream transcription events off the UI thread."""
    
    # Signals
    audio_chunk = Signal(bytes)   # Emitted for each audio chunk
    text_update = Signal(object)  # Emits RealtimeTranscriptionOutput
    finished_recording = Signal() # Emitted when recording stops
    error = Signal(str)           # Emitted on error
    
    def __init__(
        self,
        recorder: Any,
        provider: GenAIProvider,
        silence_detector: Any,
        language: Optional[str] = None,
        realtime_mode: bool = True,
        parent: Optional[QObject] = None,
    ) -> None:
        """Store recording dependencies and options."""
        super().__init__(parent)
        self._recorder = recorder
        self._provider = provider
        self._silence_detector = silence_detector
        self._language = language
        self._realtime_mode = realtime_mode
        
        self._stop_requested = False
        self._audio_buffer: list[bytes] = []
    
    def run(self) -> None:
        """Main worker thread execution."""
        try:
            self._stop_requested = False
            self._audio_buffer = []
            self._silence_detector.reset()
            
            # Start recording
            self._recorder.start()
            
            if self._realtime_mode:
                self._run_realtime()
            else:
                self._run_batch()
            
        except Exception as e:
            print(f"[WORKER] Error: {e}")
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))
        finally:
            # Ensure recorder is stopped
            try:
                self._recorder.stop()
            except Exception:
                pass
            self.finished_recording.emit()
    
    def _run_realtime(self) -> None:
        """Run real-time transcription mode."""
        try:
            # Create a generator that yields audio chunks
            def audio_generator():
                for chunk in self._recorder.record():
                    if self._stop_requested:
                        break
                    
                    # Emit chunk for other listeners (e.g., silence detector)
                    self.audio_chunk.emit(chunk)
                    
                    # Check for silence
                    if self._silence_detector.feed(chunk):
                        self._stop_requested = True
                        break
                    
                    yield chunk
            
            # Run transcription - provider now yields RealtimeTranscriptionOutput
            last_output = None
            for output in self._provider.transcribe_realtime(
                audio_generator(),
                language=self._language,
                chunk_duration=1.5,  # Faster feedback (every 1.5 seconds)
            ):
                last_output = output
                
                # Always emit the output for UI/session to process
                self.text_update.emit(output)
                
                # Stop after receiving COMPLETE
                if output.status == TranscriptionStatus.COMPLETE:
                    break
                    
                # If stop requested and not complete, break
                if self._stop_requested:
                    break
            
            # If we never got COMPLETE, emit one now with the last known text
            if last_output and last_output.status == TranscriptionStatus.IN_PROGRESS:
                final_output = RealtimeTranscriptionOutput(
                    type=last_output.type,
                    chunks=last_output.chunks.copy(),
                    latest_transcription=last_output.latest_transcription,
                    status=TranscriptionStatus.COMPLETE,
                    final_transcription=last_output.latest_transcription,
                )
                self.text_update.emit(final_output)
                
        except Exception as e:
            print(f"[WORKER] Real-time error: {e}")
            import traceback
            traceback.print_exc()
            self.error.emit(f"Real-time transcription error: {e}")
    
    def _run_batch(self) -> None:
        """Run batch transcription mode (record first, transcribe after)."""
        try:
            # Collect all audio
            for chunk in self._recorder.record():
                if self._stop_requested:
                    break
                
                self.audio_chunk.emit(chunk)
                self._audio_buffer.append(chunk)
                
                # Check for silence
                if self._silence_detector.feed(chunk):
                    self._stop_requested = True
                    break
            
            # Transcribe collected audio
            if self._audio_buffer:
                wav_data = self._create_wav(b"".join(self._audio_buffer))
                
                # Use batch transcription via temp file approach
                # For simplicity, write to temp file
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    f.write(wav_data)
                    temp_path = f.name
                
                try:
                    text = self._provider.transcribe_batch(temp_path, self._language)
                    # Wrap in RealtimeTranscriptionOutput for consistent handling
                    output = RealtimeTranscriptionOutput(
                        type=TranscriptionOutputType.CUMULATIVE,
                        chunks=[text] if text else [],
                        latest_transcription=text,
                        status=TranscriptionStatus.COMPLETE,
                        final_transcription=text,
                    )
                    self.text_update.emit(output)
                finally:
                    import os
                    try:
                        os.unlink(temp_path)
                    except Exception:
                        pass
                        
        except Exception as e:
            self.error.emit(f"Batch transcription error: {e}")
    
    def _create_wav(self, pcm_data: bytes) -> bytes:
        """Convert PCM16 data to WAV format."""
        wav_buffer = io.BytesIO()
        
        with wave.open(wav_buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(pcm_data)
        
        wav_buffer.seek(0)
        return wav_buffer.getvalue()
    
    def request_stop(self) -> None:
        """Request the worker to stop recording."""
        self._stop_requested = True
        self._recorder.stop()


class RecordingSession(QObject):
    """Coordinate recording, provider output, focus, and final text delivery."""
    
    # Signals
    state_changed = Signal(SessionState)
    text_chunk = Signal(object)  # Emits RealtimeTranscriptionOutput
    transcription_complete = Signal(str)
    error = Signal(str)
    
    def __init__(
        self,
        recorder: Any,
        provider: GenAIProvider,
        focus_detector: Optional[FocusDetector] = None,
        text_injector: Optional[TextInjector] = None,
        language: Optional[str] = None,
        silence_threshold_db: float = -40.0,
        silence_duration: float = 2.0,
        realtime_mode: bool = True,
        parent: Optional[QObject] = None,
    ) -> None:
        """Store dependencies and initialize recording state."""
        super().__init__(parent)
        
        self._recorder = recorder
        self._provider = provider
        self._focus_detector = focus_detector
        self._text_injector = text_injector
        self._language = language
        self._realtime_mode = realtime_mode
        
        # Create silence detector
        from .silence_detector import SilenceDetector
        self._silence_detector = SilenceDetector(
            threshold_db=silence_threshold_db,
            silence_duration=silence_duration,
            grace_period=1.5,  # Don't trigger on first 1.5 seconds of silence
        )
        
        # State
        self._state = SessionState.IDLE
        self._worker: Optional[RecordingWorker] = None
        self._last_text = ""
        self._final_text = ""
        self._text_target: Optional[tuple[int, ...]] = None
    
    @property
    def state(self) -> SessionState:
        """Get the current session state."""
        return self._state
    
    @property
    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._state == SessionState.RECORDING
    
    def toggle(self) -> None:
        """Start an idle recording or stop an active one."""
        if self._state == SessionState.IDLE:
            self.start()
        elif self._state == SessionState.RECORDING:
            self.stop()
    
    def start(self) -> None:
        """Start recording after capturing the focused text target."""
        if self._state != SessionState.IDLE:
            return

        self._text_target = self._focus_detector.capture_text_target() if self._focus_detector else None
        
        # Reset state
        self._last_text = ""
        self._final_text = ""
        self._silence_detector.reset()
        
        # Create and start worker
        self._worker = RecordingWorker(
            recorder=self._recorder,
            provider=self._provider,
            silence_detector=self._silence_detector,
            language=self._language,
            realtime_mode=self._realtime_mode,
        )
        
        # Connect signals
        self._worker.text_update.connect(self._on_text_update)
        self._worker.finished_recording.connect(self._on_recording_finished)
        self._worker.error.connect(self._on_error)
        
        # Update state and start
        self._set_state(SessionState.RECORDING)
        self._worker.start()
    
    def stop(self) -> None:
        """Stop the current recording session."""
        if self._state != SessionState.RECORDING:
            return
        
        if self._worker:
            self._worker.request_stop()
            # State will change to PROCESSING when worker emits finished
    
    def cancel(self) -> None:
        """Cancel the current recording without processing."""
        if self._worker:
            self._worker.request_stop()
        
        self._set_state(SessionState.IDLE)
        self._worker = None
    
    def _set_state(self, new_state: SessionState) -> None:
        """Update the session state and emit signal."""
        if self._state != new_state:
            self._state = new_state
            self.state_changed.emit(new_state)
    
    def _on_text_update(self, output: RealtimeTranscriptionOutput) -> None:
        """Handle transcription output from worker."""
        self._last_text = output.latest_transcription
        
        # Emit for UI (toast updates)
        self.text_chunk.emit(output)
        
        # Track completion
        if output.status == TranscriptionStatus.COMPLETE:
            # Use final_transcription if available, otherwise latest_transcription
            self._final_text = output.final_transcription or output.latest_transcription or ""
    
    def _on_recording_finished(self) -> None:
        """Handle recording completion."""
        # Brief processing state
        self._set_state(SessionState.PROCESSING)
        
        # Use final_text if available, otherwise last_text
        final_text = self._final_text or self._last_text or ""

        if self._final_text and self._text_injector:
            paste = self._text_target is not None and self._focus_detector is not None and self._focus_detector.is_same_text_target(self._text_target)
            self._text_injector.deliver(final_text, paste=paste)
        
        # Always emit completion (even if empty - UI will show "No Audio Detected")
        self.transcription_complete.emit(final_text)
        
        # Clean up
        self._worker = None
        self._final_text = ""
        self._text_target = None
        self._set_state(SessionState.IDLE)
    
    def _on_error(self, message: str) -> None:
        """Handle error from worker."""
        self.error.emit(message)
        self._set_state(SessionState.IDLE)
        self._worker = None


