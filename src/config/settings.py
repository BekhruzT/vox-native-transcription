"""
Settings management for Input-STT application.

Handles loading, saving, and accessing user configuration
stored in a JSON file in the user's APPDATA directory.
"""

import json
import os
from pathlib import Path
from typing import Any, Optional


class Settings:
    """
    Manages application settings with JSON file persistence.
    
    Settings are stored at %APPDATA%/InputSTT/settings.json on Windows.
    
    Default settings:
        - hotkey: "<cmd>+<alt>+j" (pynput format, <cmd> = Windows key)
        - audio_device: null (system default)
        - language: "en"
    
    Example:
        settings = Settings()
        hotkey = settings.get("hotkey")
        settings.set("hotkey", "ctrl+alt+s")
        settings.save()
    """
    
    DEFAULT_SETTINGS = {
        "hotkey": "<cmd>+<alt>+j",
        "audio_device": None,
        "language": "en",
        "save_history": True,
    }
    
    def __init__(self, config_dir: Optional[Path] = None):
        """
        Initialize settings manager.
        
        Args:
            config_dir: Optional custom config directory. 
                       Defaults to %APPDATA%/InputSTT on Windows.
        """
        if config_dir is None:
            appdata = os.getenv("APPDATA", os.path.expanduser("~"))
            self._config_dir = Path(appdata) / "InputSTT"
        else:
            self._config_dir = Path(config_dir)
        
        self._config_file = self._config_dir / "settings.json"
        self._settings: dict[str, Any] = {}
        
        # Ensure config directory exists
        self._config_dir.mkdir(parents=True, exist_ok=True)
        
        # Load existing settings or create defaults
        self.load()
    
    @property
    def config_file(self) -> Path:
        """Get the path to the settings file."""
        return self._config_file
    
    def load(self) -> dict[str, Any]:
        """
        Load settings from the JSON file.
        
        If the file doesn't exist or is invalid, uses default settings.
        
        Returns:
            The loaded settings dictionary.
        """
        self._settings = self.DEFAULT_SETTINGS.copy()
        
        if self._config_file.exists():
            try:
                with open(self._config_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    # Merge with defaults (loaded values override defaults)
                    self._settings.update(loaded)
            except (json.JSONDecodeError, IOError):
                # Invalid file - use defaults
                pass
        
        return self._settings
    
    def save(self) -> None:
        """
        Save current settings to the JSON file.
        
        Creates the file if it doesn't exist.
        """
        try:
            with open(self._config_file, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2)
        except IOError as e:
            raise IOError(f"Failed to save settings: {e}") from e
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a setting value.
        
        Args:
            key: The setting key to retrieve.
            default: Value to return if key doesn't exist.
                    If None, uses the default from DEFAULT_SETTINGS.
        
        Returns:
            The setting value, or the default.
        """
        if default is None:
            default = self.DEFAULT_SETTINGS.get(key)
        return self._settings.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """
        Set a setting value.
        
        Note: Call save() to persist changes to disk.
        
        Args:
            key: The setting key to set.
            value: The value to store.
        """
        self._settings[key] = value
    
    def reset(self) -> None:
        """
        Reset all settings to defaults.
        
        Note: Call save() to persist changes to disk.
        """
        self._settings = self.DEFAULT_SETTINGS.copy()
    
    def to_dict(self) -> dict[str, Any]:
        """
        Get all settings as a dictionary.
        
        Returns:
            A copy of the settings dictionary.
        """
        return self._settings.copy()


