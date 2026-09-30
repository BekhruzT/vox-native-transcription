"""Windows speech transcription with final clipboard delivery and optional paste."""

__version__ = "0.1.0"

from .audio import AudioRecorder
from .providers import GenAIProvider, OpenAIProvider

# Core components
from .core import (
    HotkeyManager,
    RecordingSession,
    SessionState,
    SilenceDetector,
    TextInjector,
)

# Configuration
from .config import Settings

__all__ = [
    # Audio
    "AudioRecorder",
    # Providers
    "GenAIProvider", 
    "OpenAIProvider",
    # Core
    "HotkeyManager",
    "RecordingSession",
    "SessionState",
    "SilenceDetector",
    "TextInjector",
    # Config
    "Settings",
]

