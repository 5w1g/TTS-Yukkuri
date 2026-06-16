# Yukkuri TTS — Project Overview

Text-to-speech virtual microphone for Discord. Type text → TTS engine synthesises audio → PipeWire virtual sink → Discord sees it as microphone input.

## Architecture

```
User types text (GUI or CLI)
    ↓
TTS Engine (VOICEVOX / Edge TTS / Amazon Polly / AquesTalk10)
    ↓ audio bytes (WAV or MP3)
audio_router.py → pw-play --target=yukkuri_sink
    ↓
PipeWire Null Sink (yukkuri_sink) → monitor passthrough
    ↓
Virtual Source (yukkuri_source, Audio/Source/Virtual)
    ↓
Discord Voice Chat (select as Input Device)
```

## Files

| File | Purpose |
|------|---------|
| `yukkuri.py` | CLI entry point — REPL, one-shot, pipe modes |
| `yukkuri_gui.py` | tkinter GUI with dark Catppuccin theme |
| `tts_engine.py` | VOICEVOX HTTP API client (port 50021, Japanese voices) |
| `tts_edge.py` | Microsoft Edge TTS client (Brian, Guy, Aria, etc.) |
| `tts_polly.py` | Amazon Polly client (real Ivona Brian, Joey, etc.) |
| `tts_aquestalk.py` | AquesTalk10 client (authentic Yukkuri voice, ctypes wrapper) |
| `audio_router.py` | PipeWire virtual sink management + audio playback |
| `config.py` | JSON config loader with validation, supports XDG_CONFIG_HOME |
| `setup.sh` | One-shot idempotent setup script |
| `config.json` | Default config (committed — no secrets) |

## Four TTS Engines

### 1. VOICEVOX (local, free)
- Japanese TTS, 127 voice styles across 43 speakers
- Runs as local HTTP server on port 50021
- Download from GitHub releases, extract to `~/voicevox/`
- Speaker 1 = Zundamon (closest to classic Yukkuri)
- CLI: `/engine voicevox`, `/speaker N`, `/speakers`

### 2. Microsoft Edge TTS (cloud, free)
- Unofficial API via `edge-tts` pip package
- 14 quick-access English voices (brian, guy, eric, aria, jenny, etc.)
- Outputs MP3 — `pw-play` handles natively
- Requires: `pip install --break-system-packages edge-tts`
- CLI: `/engine edge`, `/voice brian`, `/voices`

### 3. Amazon Polly (cloud, AWS credentials required)
- **Real Ivona Brian voice** (Amazon acquired Ivona in 2013)
- 109+ voices, 18 quick-access (brian, joey, amy, emma, salli, etc.)
- Credentials from `~/.aws/credentials` or env vars — never in project
- Rate/volume/pitch control via SSML `<prosody>` wrapping
- Voice list fetched async in GUI to avoid UI freeze
- Requires: `pip install --break-system-packages boto3` + AWS IAM user
- CLI: `/engine polly`, `/voice brian`, `/voices`

### 4. AquesTalk10 (local, evaluation free)
- **Authentic Yukkuri voice** (ゆっくり) — the classic Nico Nico Douga / YouTube voice
- ctypes wrapper around ``libAquesTalk10.so`` (no pip dependency)
- Free evaluation version with minor limitation (na/ma-row kana → "nu")
- 7 voice presets: F1 (classic Yukkuri/Reimu), F2 (Marisa-type), F3 (soft/high), M1/M2 (male), R1/R2 (robot)
- Outputs WAV PCM (16 kHz, 16-bit, mono) — directly playable by ``pw-play``
- Speed (0.5–2.0 → spd 50–300), pitch (0.5–2.0 → pit 20–200), intonation (0.0–2.0 → acc 0–200)
- Requires kana input (hiragana/katakana). Install ``pyopenjtalk`` for automatic kanji→kana conversion
- Library discovery: ``AQUESTALK_LIB`` env var → ``~/aquestalk/libAquesTalk10.so`` → ``/usr/local/lib/``
- CLI: `/engine aquestalk`, `/voice f1|f2|f3|m1|m2|r1|r2`, `/voices`

## Audio Routing Details

**PipeWire config** at `~/.config/pipewire/pipewire.conf.d/99-yukkuri.conf`:
- `yukkuri_sink` — Audio/Sink null sink, accepts playback
- `yukkuri_source` — Audio/Source/Virtual, Discord captures this

**Link auto-creation** (in `audio_router.py._ensure_links()`):
- `yukkuri_sink:monitor_FL/FR` → `yukkuri_source:input_FL/FR`
- Also removes spurious auto-links from source inputs to sink playback (feedback prevention)

**Format detection** in `_write_temp_wav()`:
- RIFF → `.wav`, ID3 → `.mp3`, OggS → `.ogg`
- Raw MPEG sync (`0xFFE0-0xFFF7`) → `.mp3`

## Config

Default location: `$XDG_CONFIG_HOME/yukkuri/config.json` (falls back to `~/.config/yukkuri/config.json`)

```json
{
    "voicevox": {"host": "127.0.0.1", "port": 50021, "speaker": 1, "timeout_seconds": 30},
    "audio": {"sink_name": "yukkuri_sink", "sample_rate": 48000, "channels": 2},
    "app": {"history_file": "~/.yukkuri_history", "speed_scale": 1.0, "pitch_scale": 1.0, "intonation_scale": 1.0, "engine": "voicevox", "voice": "Brian"}
}
```

Secrets (AWS keys) go in `~/.aws/credentials`, never in config.json or the repo.

## GUI (yukkuri_gui.py)

- Dark Catppuccin theme (bg=#1e1e2e, accent=#cba6f7)
- Four engine toggle buttons: [VOICEVOX] [Edge TTS] [Polly] [AquesTalk10]
- Voice dropdown repopulates per engine (async for cloud engines)
- Speed/Pitch/Intonation sliders (0.5-2.0, Polly maps intonation → volume)
- 6 presets: Normal, Yukkuri, Fast, High Pitch, Whisper, Energetic
- History listbox with double-click replay
- Status dot (green/yellow/red) + engine footer
- Voice memory per engine type (survives engine switches)
- Background thread for synthesis keeps UI responsive

## CLI (yukkuri.py)

- REPL mode (default): interactive shell with `/commands`
- One-shot: `yukkuri.py "hello world"`
- Pipe: `echo "hello" | yukkuri.py`
- Commands: `/engine`, `/voice`, `/voices`, `/speaker`, `/speakers`, `/speed`, `/pitch`, `/intonation`, `/status`, `/help`, `/quit`

## Key Design Decisions

1. **Python stdlib-first** — Only http.client, json, subprocess, tempfile, ctypes for local engines
2. **No ffmpeg dependency** — `pw-play` handles MP3, WAV, Ogg natively
3. **Credentials external** — AWS keys in `~/.aws/credentials`, never in project
4. **Temp files for audio** — Write to `/tmp/`, play via `pw-play --target`, auto-cleanup
5. **Thread-safe audio** — Lock on `_temp_files` list, async playback option
6. **Config with validation** — Range checks on port/channels/sample rate, graceful fallback

## Git & Security

- Repo: `5w1g/TTS-Yukkuri` on GitHub (public)
- No secrets, tokens, or credentials in any committed file
- `.gitignore` excludes: `__pycache__/`, `*.wav`, `*.mp3`, `.claude/`, `voicevox_engine/`, test files

## Running

```bash
# Start VOICEVOX engine (for Japanese voices)
cd ~/voicevox/voicevox_engine-linux-cpu-x64/ && ./run

# Or place libAquesTalk10.so in ~/aquestalk/ for authentic Yukkuri voice

# CLI
python3 yukkuri.py

# GUI
python3 yukkuri_gui.py

# One-shot
python3 yukkuri.py "こんにちは"
```
