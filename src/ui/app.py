"""Coordinate Vox's providers, recording session, hotkeys, and tray UI."""

import sys
from typing import Optional

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal, Slot

from ..config.settings import Settings
from ..core.hotkey_manager import HotkeyManager
from ..core.focus_detector import FocusDetector
from ..core.session import RecordingSession, SessionState
from ..core.text_injector import TextInjector
from ..audio.recorder import AudioRecorder
from ..providers.openai_provider import OpenAIProvider
from ..providers.elevenlabs_provider import ElevenLabsProvider
from ..providers.base import RealtimeTranscriptionOutput, TranscriptionStatus

from .system_tray import SystemTray


class STTApplication(QObject):
    """Manage the desktop application's recording and UI lifecycle."""
    
    # Signals
    recording_started = Signal()
    recording_stopped = Signal()
    text_ready = Signal(str)
    
    def __init__(self, parent: Optional[QObject] = None) -> None:
        """Initialize the application."""
        super().__init__(parent)
        
        # Load settings
        self._settings = Settings()
        
        # Initialize components
        self._hotkey_manager: Optional[HotkeyManager] = None
        self._session: Optional[RecordingSession] = None
        self._system_tray: Optional[SystemTray] = None
        self._recorder: Optional[AudioRecorder] = None
        self._provider = None
        
        self._focus_detector = FocusDetector()
        self._text_injector = TextInjector()
        
        # Overlay windows (lazy initialization)
        self._mic_indicator = None
        self._toast = None
        
        # State
        self._is_initialized = False
    
    @property
    def settings(self) -> Settings:
        """Get the settings manager."""
        return self._settings
    
    @property
    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._session is not None and self._session.is_recording
    
    def initialize(self) -> bool:
        """Initialize providers, hotkeys, tray, and overlays."""
        if self._is_initialized:
            return True
        
        try:
            # Initialize audio recorder
            self._recorder = AudioRecorder()
            
            # Initialize STT provider - try ElevenLabs first, then OpenAI
            self._provider = None
            # Try ElevenLabs first (better real-time streaming)
            try:
                self._provider = ElevenLabsProvider()
            except Exception as e:
                print(f"ElevenLabs unavailable: {e}")

            # Fall back to OpenAI
            if not self._provider:
                try:
                    self._provider = OpenAIProvider()
                except ValueError as e:
                    print(f"Warning: No STT provider configured: {e}")
                    self._provider = None
            
            # Initialize hotkey manager
            self._hotkey_manager = HotkeyManager(self)
            self._hotkey_manager.triggered.connect(self._on_hotkey_triggered)
            
            # Register hotkey
            hotkey = self._settings.get("hotkey", "<cmd>+<alt>+j")
            if not self._hotkey_manager.register(hotkey):
                print(f"Warning: Failed to register hotkey '{hotkey}'")
            
            # Initialize system tray
            self._system_tray = SystemTray(self)
            self._system_tray.toggle_recording_requested.connect(self._on_toggle_recording)
            self._system_tray.settings_requested.connect(self._on_settings_requested)
            self._system_tray.exit_requested.connect(self._on_exit_requested)
            
            # Initialize overlays
            self._init_overlays()
            
            # Show system tray
            self._system_tray.show()
            
            self._is_initialized = True
            return True
            
        except Exception as e:
            print(f"Initialization failed: {e}")
            return False
    
    def _init_overlays(self) -> None:
        """Initialize overlay windows."""
        try:
            from .overlays.mic_indicator import MicIndicator
            from .overlays.toast import ToastNotification
            
            self._mic_indicator = MicIndicator()
            self._toast = ToastNotification()
            
        except ImportError as e:
            print(f"Warning: Could not load overlays: {e}")
    
    def _create_session(self) -> RecordingSession:
        """Create a new recording session."""
        if not self._provider:
            raise RuntimeError("STT provider not configured. Set OPENAI_API_KEY.")
        
        session = RecordingSession(
            recorder=self._recorder,
            provider=self._provider,
            focus_detector=self._focus_detector,
            text_injector=self._text_injector,
            language=self._settings.get("language", "en"),
            silence_threshold_db=-45.0,  # Less sensitive (was -40)
            silence_duration=4.0,        # 4 seconds of silence before auto-stop (was 2)
            realtime_mode=True,
            parent=self,
        )
        
        # Connect session signals
        session.state_changed.connect(self._on_session_state_changed)
        session.text_chunk.connect(self._on_text_chunk)
        session.transcription_complete.connect(self._on_transcription_complete)
        session.error.connect(self._on_session_error)
        
        return session
    
    @Slot()
    def _on_hotkey_triggered(self) -> None:
        """Handle hotkey press."""
        self._on_toggle_recording()
    
    @Slot()
    def _on_toggle_recording(self) -> None:
        """Toggle recording state."""
        if self._session and self._session.is_recording:
            self._stop_recording()
        else:
            self._start_recording()
    
    def _start_recording(self) -> None:
        """Start a new recording."""
        try:
            # Create new session
            self._session = self._create_session()
            
            # Capture focus before the toast appears.
            self._session.start()

            # Show "Listening..." toast
            if self._toast:
                self._toast.show_listening()
            
            # Update tray
            if self._system_tray:
                self._system_tray.set_recording_state(True)
            
            self.recording_started.emit()
            
        except Exception as e:
            print(f"[ERROR] Failed to start recording: {e}")
            import traceback
            traceback.print_exc()
            self._on_session_error(str(e))
    
    def _stop_recording(self) -> None:
        """Stop the current recording."""
        if self._session:
            self._session.stop()
    
    @Slot(SessionState)
    def _on_session_state_changed(self, state: SessionState) -> None:
        """Handle session state changes."""
        if self._system_tray:
            if state == SessionState.RECORDING:
                self._system_tray.set_recording_state(True)
            elif state == SessionState.PROCESSING:
                self._system_tray.set_processing_state(True)
            else:
                self._system_tray.set_recording_state(False)
                self._system_tray.set_processing_state(False)
        
        if state == SessionState.IDLE:
            # Hide toast if still showing "Listening..." but no transcription
            # (transcription_complete will show the result toast if needed)
            self.recording_stopped.emit()
    
    @Slot(object)
    def _on_text_chunk(self, output: RealtimeTranscriptionOutput) -> None:
        """Handle real-time transcription output."""
        # Update toast in real-time
        if self._toast:
            self._toast.update_transcription(output)
    
    @Slot(str)
    def _on_transcription_complete(self, text: str) -> None:
        """Handle transcription session completion."""
        # Emit for external listeners
        self.text_ready.emit(text)
        
    
    @Slot(str)
    def _on_session_error(self, message: str) -> None:
        """Handle session error."""
        print(f"[ERROR] Session error: {message}")
        
        # Hide toast
        if self._toast:
            self._toast.hide_toast()
        
        # Update tray
        if self._system_tray:
            self._system_tray.set_recording_state(False)
            self._system_tray.set_processing_state(False)
    
    @Slot()
    def _on_settings_requested(self) -> None:
        """Handle settings menu click."""
        try:
            from .settings_dialog import SettingsDialog
            
            dialog = SettingsDialog(self._settings, self._hotkey_manager)
            dialog.exec()
            
        except ImportError:
            print("Settings dialog not yet implemented")
    
    @Slot()
    def _on_exit_requested(self) -> None:
        """Handle exit request."""
        self.cleanup()
        QApplication.quit()
    
    def cleanup(self) -> None:
        """Clean up resources before exit."""
        # Cancel any active recording
        if self._session and self._session.is_recording:
            self._session.cancel()
        
        # Unregister hotkey
        if self._hotkey_manager:
            self._hotkey_manager.cleanup()
        
        # Hide overlays
        if self._mic_indicator:
            self._mic_indicator.hide()
        if self._toast:
            self._toast.hide()
        
        # Hide tray
        if self._system_tray:
            self._system_tray.hide()
        
        # Save settings
        self._settings.save()


def run_application() -> int:
    """Run the Vox Qt event loop and return its exit code."""
    # Create Qt application
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Keep running with just tray
    app.setApplicationName("Input-STT")
    app.setOrganizationName("InputSTT")
    
    # Create and initialize main application
    stt_app = STTApplication()
    
    if not stt_app.initialize():
        print("Failed to initialize application")
        return 1
    
    # Run event loop
    exit_code = app.exec()
    
    # Cleanup
    stt_app.cleanup()
    
    return exit_code


