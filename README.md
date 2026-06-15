# Yukkuri TTS — Virtual Mic for Discord

Type Japanese (or English) text and have it spoken through Discord as your
microphone input, using the [VOICEVOX](https://voicevox.jp/) TTS engine.

## How it works

```
Your typed text → VOICEVOX TTS → WAV audio → PipeWire virtual sink → Discord mic
```

## Quick Start

### 1. Run setup

```bash
cd ~/TTS
./setup.sh
```

This installs dependencies, downloads VOICEVOX (~1.7 GB), and configures the
virtual audio sink.

### 2. Start VOICEVOX engine

```bash
~/voicevox/voicevox_engine-linux-cpu-x64/run
```

The engine serves its API at `http://localhost:50021`. It takes 10–30 seconds
to load the voice models on first start.

### 3. Run the app

**GUI mode (recommended):**
```bash
python3 ~/TTS/yukkuri_gui.py
```
A clean graphical interface with speaker selection, voice sliders,
presets, and phrase history. Requires `python3-tk`:
```bash
sudo apt install -y python3-tk
```

**CLI mode:**
```bash
python3 ~/TTS/yukkuri.py
```

### 4. Configure Discord

In Discord → User Settings → Voice & Video → Input Device:
Select **"Yukkuri Virtual Sink"** (or its monitor).

Join a voice channel and start typing!

## Usage

### Interactive REPL (default)

```
$ yukkuri.py
==============================================================
  Yukkuri TTS  —  VOICEVOX 0.25.2
  Speaker: ずんだもん – ノーマル  |  Speed: 1.0  Pitch: 1.0  Intonation: 1.0
==============================================================
  Type text and press Enter to speak it.
  Commands: /help, /speaker, /speakers, /speed, /pitch, /intonation, /status, /quit

> こんにちは
[OK]

> /speaker 47
  Speaker set to もち子さん – ノーマル (ID 47)

> hello, nice to meet you
[OK]
```

### One-shot mode

```bash
python3 yukkuri.py "おはようございます"
```

### Pipe mode

```bash
echo "こんにちは" | python3 yukkuri.py
```

## Commands

| Command | Description |
|---------|-------------|
| `/speaker N` | Change speaker ID |
| `/speakers` | List all available speakers |
| `/speed N` | Set speed (0.5–2.0, lower = Yukkuri slower) |
| `/pitch N` | Set pitch (0.5–2.0) |
| `/intonation N` | Set intonation (0.0–2.0) |
| `/status` | Show engine status and settings |
| `/help` | Show help |
| `/quit` | Exit |

## Yukkuri Voice

For the classic "yukkuri" slow voice effect:
```
/speed 0.7
/pitch 1.2
```

## English Support

VOICEVOX can speak English text — it will use Japanese-accented English
pronunciation. This is intentional and part of the charm.

## Recommended Speakers

| ID | Name | Style |
|----|------|-------|
| 1 | ずんだもん (Zundamon) | Normal — cute, popular |
| 3 | ずんだもん (Zundamon) | Sad |
| 8 | 春日部つむぎ (Kasukabe Tsumugi) | Normal |
| 47 | もち子さん (Mochiko-san) | Normal — gentle, Yukkuri-like |

## Auto-start VOICEVOX on login

```bash
mkdir -p ~/.config/systemd/user
cp ~/TTS/voicevox.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now voicevox.service
```

## Files

| File | Purpose |
|------|---------|
| `yukkuri.py` | Main CLI entry point |
| `tts_engine.py` | VOICEVOX HTTP API client |
| `audio_router.py` | PipeWire virtual sink + audio playback |
| `config.py` | Configuration loader |
| `config.json` | Default settings |
| `setup.sh` | One-shot system setup script |

## Troubleshooting

**"Cannot reach VOICEVOX engine"**
Make sure the engine is running: `~/voicevox/voicevox_engine-linux-cpu-x64/run`

**Virtual sink not appearing in Discord**
Restart PipeWire: `systemctl --user restart pipewire pipewire-pulse`
Then restart Discord.

**Audio not being picked up by Discord**
- Check Discord's input device is set to "Yukkuri Virtual Sink"
- Lower Discord's voice activity threshold
- Test the sink: `pw-play --target=yukkuri_sink /usr/share/sounds/alsa/Front_Center.wav`

**"Synthesis error" or HTTP 422**
VOICEVOX needs at least some recognizable phonemes. Even English works,
but pure symbols/numbers may fail.
