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
        "engine_path": "~/TTS/voicevox/voicevox_engine-linux-cpu-x64/run",
        "auto_start": True,
    },
    "edge": {
        "voice": "en-US-BrianNeural",
    },
    "polly": {
        "voice": "Brian",
    },
    "aquestalk": {
        "lib_path": "",
        "voice": "f1",
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
        path: Optional config file path. Defaults to
              ``$XDG_CONFIG_HOME/yukkuri/config.json`` or
              ``~/.config/yukkuri/config.json``.

    Returns:
        dict with validated configuration values.
    """
    if path is None:
        xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        path = os.path.join(xdg, "yukkuri", "config.json")

    config = copy.deepcopy(DEFAULT_CONFIG)

    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                user_config = json.load(f)
            if isinstance(user_config, dict):
                config = _deep_merge(config, user_config)
            else:
                print(f"Warning: Config at {path} is not a dict "
                      f"(got {type(user_config).__name__}), using defaults.")
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: Could not read config at {path}: {e}")
            print("Using defaults.")

    # Ensure config directory exists
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Write back merged config if file doesn't exist
    if not os.path.exists(path):
        save(config, path)

    # Type coercion and validation
    try:
        config["voicevox"]["port"] = _validate_port(config["voicevox"]["port"])
        config["voicevox"]["speaker"] = int(config["voicevox"]["speaker"])
        config["voicevox"]["timeout_seconds"] = _validate_positive(
            config["voicevox"]["timeout_seconds"], "timeout_seconds")
        config["audio"]["sample_rate"] = _validate_positive(
            config["audio"]["sample_rate"], "sample_rate")
        config["audio"]["channels"] = _validate_range(
            config["audio"]["channels"], 1, 8, "channels")
    except (ValueError, TypeError) as e:
        print(f"Warning: Invalid config value: {e}. Using default.")
        return copy.deepcopy(DEFAULT_CONFIG)

    # Expand ~ in paths
    if "history_file" in config.get("app", {}):
        config["app"]["history_file"] = os.path.expanduser(
            config["app"]["history_file"])

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


def _validate_port(value):
    """Validate and cast a TCP port number."""
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError(f"port must be 1-65535, got {port}")
    return port


def _validate_positive(value, name):
    """Validate and cast a positive integer."""
    num = int(value)
    if num < 1:
        raise ValueError(f"{name} must be positive, got {num}")
    return num


def _validate_range(value, lo, hi, name):
    """Validate and cast an integer in [lo, hi]."""
    num = int(value)
    if not lo <= num <= hi:
        raise ValueError(f"{name} must be {lo}-{hi}, got {num}")
    return num
