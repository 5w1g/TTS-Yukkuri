"""Configuration loader for Yukkuri TTS."""

import copy
import json
import os


DEFAULT_CONFIG = {
    "voicevox": {
        "host": "127.0.0.1",
        "port": 50021,
        "speaker": 1,
        "timeout_seconds": 30,
    },
    "audio": {
        "sink_name": "yukkuri_sink",
        "sample_rate": 48000,
        "channels": 2,
    },
    "app": {
        "history_file": "~/.yukkuri_history",
        "speed_scale": 1.0,
        "pitch_scale": 1.0,
        "intonation_scale": 1.0,
    },
}


def load(path=None):
    """Load configuration from file, creating with defaults if needed.

    Args:
        path: Optional config file path. Defaults to ~/.config/yukkuri/config.json

    Returns:
        dict with validated configuration values.
    """
    if path is None:
        path = os.path.expanduser("~/.config/yukkuri/config.json")

    config = copy.deepcopy(DEFAULT_CONFIG)

    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                user_config = json.load(f)
            config = _deep_merge(config, user_config)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: Could not read config at {path}: {e}")
            print("Using defaults.")

    # Ensure config directory exists
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Write back merged config if file doesn't exist
    if not os.path.exists(path):
        save(config, path)

    # Validate
    config["voicevox"]["port"] = int(config["voicevox"]["port"])
    config["voicevox"]["speaker"] = int(config["voicevox"]["speaker"])
    config["voicevox"]["timeout_seconds"] = int(config["voicevox"]["timeout_seconds"])
    config["audio"]["sample_rate"] = int(config["audio"]["sample_rate"])
    config["audio"]["channels"] = int(config["audio"]["channels"])

    return config


def save(config, path=None):
    """Save configuration to file."""
    if path is None:
        path = os.path.expanduser("~/.config/yukkuri/config.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


def _deep_merge(base, override):
    """Deep merge override into base dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
