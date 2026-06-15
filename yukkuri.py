#!/usr/bin/env python3
"""Yukkuri TTS — CLI entry point.

Speaks Japanese or English text through VOICEVOX or Microsoft Edge TTS
into a PipeWire virtual audio sink for Discord. Runs in three modes:

  1. REPL:        yukkuri.py                (interactive shell)
  2. One-shot:    yukkuri.py "text here"    (speaks then exits)
  3. Pipe:        echo text | yukkuri.py    (speaks then exits)
"""

import atexit
import os
import readline
import signal
import sys

from config import load
from tts_engine import (
    VoicevoxEngine,
    EngineNotRunning as VVNotRunning,
    SynthesisError,
    VoicevoxError,
)
from audio_router import AudioRouter, AudioRouterError

# Edge TTS is optional
try:
    from tts_edge import EdgeTTSEngine, POPULAR_VOICES as EDGE_POPULAR
    HAS_EDGE = True
except ImportError:
    HAS_EDGE = False
    EdgeTTSEngine = None
    EDGE_POPULAR = {}

# Amazon Polly (real Ivona Brian) is optional
try:
    from tts_polly import PollyEngine, POPULAR_VOICES as POLLY_POPULAR
    HAS_POLLY = True
except ImportError:
    HAS_POLLY = False
    PollyEngine = None
    POLLY_POPULAR = {}

# AquesTalk10 (authentic Yukkuri voice) is optional
try:
    from tts_aquestalk import AquesTalkEngine, POPULAR_VOICES as AQUESTALK_POPULAR
    from tts_aquestalk import AquesTalkError
    HAS_AQUESTALK = True
except ImportError:
    HAS_AQUESTALK = False
    AquesTalkEngine = None
    AQUESTALK_POPULAR = {}
    class AquesTalkError(Exception): pass  # dummy — never raised


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_speaker_label(engine, speaker_id):
    """Return a human-readable ``Name – Style`` label for a speaker ID."""
    try:
        speakers = engine.get_speakers()
    except VoicevoxError:
        return str(speaker_id)
    for sp in speakers:
        for style in sp.get("styles", []):
            if style.get("id") == speaker_id:
                return f'{sp["name"]} – {style["name"]}'
    return str(speaker_id)


def _setup_readline(history_file):
    """Configure readline with history persistence."""
    histpath = os.path.expanduser(history_file)
    try:
        readline.read_history_file(histpath)
    except (FileNotFoundError, OSError):
        pass
    atexit.register(readline.write_history_file, histpath)


def _speak(text, engine, engine_type, router, speaker, speed, pitch, intonation):
    """Synthesise *text* and play it.  Return ``True`` on success."""
    text = text.strip()
    if not text:
        return True
    try:
        if engine_type == "edge":
            wav = engine.synthesize(
                text, voice=speaker,
                rate=f"{int((speed - 1.0) * 100):+.0f}%",
                pitch=f"{int((pitch - 1.0) * 12):+d}Hz",
            )
        elif engine_type == "polly":
            # Convert speed → Polly rate string
            if speed <= 0.6:
                rate = "x-slow"
            elif speed <= 0.85:
                rate = "slow"
            elif speed <= 1.25:
                rate = "medium"
            elif speed <= 1.7:
                rate = "fast"
            else:
                rate = "x-fast"
            # Map pitch/intonation to Polly prosoidium
            if pitch != 1.0:
                pct = f"{int((pitch - 1.0) * 100):+d}%"
                wav = engine.synthesize(text, voice=speaker, rate=rate,
                                        pitch=pct)
            else:
                wav = engine.synthesize(text, voice=speaker, rate=rate)
        elif engine_type == "aquestalk":
            wav = engine.synthesize(
                text, voice=speaker, speed=speed,
                pitch=pitch, intonation=intonation,
            )
        else:
            wav = engine.synthesize(
                text, speaker=speaker,
                speed_scale=speed, pitch_scale=pitch,
                intonation_scale=intonation,
            )
        router.play_wav(wav)
        return True
    except SynthesisError as exc:
        print(f"  Synthesis error: {exc}", file=sys.stderr)
    except VVNotRunning as exc:
        print(f"  Engine error: {exc}", file=sys.stderr)
    except AudioRouterError as exc:
        print(f"  Playback error: {exc}", file=sys.stderr)
    except VoicevoxError as exc:
        print(f"  VOICEVOX error: {exc}", file=sys.stderr)
    except AquesTalkError as exc:
        print(f"  AquesTalk error: {exc}", file=sys.stderr)
    except Exception as exc:
        print(f"  Error: {exc}", file=sys.stderr)
    return False


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

def _print_header(engine, engine_type, speaker_id, speed, pitch, intonation):
    """Show a friendly banner on REPL start."""
    engine_name = "VOICEVOX"
    label = str(speaker_id)
    if engine_type == "edge":
        engine_name = "Edge TTS"
    elif engine_type == "polly":
        engine_name = "Amazon Polly"
    elif engine_type == "aquestalk":
        engine_name = "AquesTalk10"
        label = f"Yukkuri ({speaker_id})"
    else:
        try:
            version = engine.get_version()
            engine_name = f"VOICEVOX {version}"
        except Exception:
            pass
        label = _resolve_speaker_label(engine, speaker_id)

    width = 62
    bar = "=" * width
    print(bar)
    print(f"  Yukkuri TTS  —  {engine_name}")
    print(f"  Speaker: {label}  |  Speed: {speed}  Pitch: {pitch}  "
          f"Intonation: {intonation}")
    print(bar)
    print("  Type text and press Enter to speak it.")
    print("  Commands: /help, /engine, /voice, /speaker, /speakers, "
          "/speed, /pitch, /intonation, /status, /quit")
    print()


def _show_help(engine_type="voicevox"):
    print("  Commands:")
    print("    /engine voicevox|edge|polly|aquestalk   Switch TTS engine")
    if engine_type == "edge" and HAS_EDGE:
        print("    /voice NAME             Set voice (e.g. /voice brian)")
        print("    /voices                 List Edge TTS voices")
    elif engine_type == "polly" and HAS_POLLY:
        print("    /voice NAME             Set voice (e.g. /voice brian)")
        print("    /voices                 List Amazon Polly voices")
    elif engine_type == "aquestalk" and HAS_AQUESTALK:
        print("    /voice NAME             Set voice (f1, f2, f3, m1, m2, r1, r2)")
        print("    /voices                 List AquesTalk10 voice presets")
    else:
        print("    /speaker N              Change speaker ID")
        print("    /speakers               List all available speakers")
    print("    /speed N                Set speed scale (0.5–2.0, 1.0=normal)")
    print("    /pitch N                Set pitch scale (0.5–2.0, 1.0=normal)")
    print("    /intonation N           Set intonation scale (0.0–2.0, 1.0=normal)")
    print("    /status                 Show current settings and engine health")
    print("    /help                   Show this help")
    print("    /quit, /exit            Exit")
    print()
    print("  Anything else is synthesised and spoken aloud.")


def _show_status(engine, engine_type, router, speaker_id, speed, pitch, intonation):
    """Print current state."""
    label = str(speaker_id)
    if engine_type == "edge":
        running = "EDGE ONLINE" if (HAS_EDGE and engine is not None) else "NOT AVAILABLE"
        print(f"  Engine:     Microsoft Edge TTS")
    elif engine_type == "polly":
        running = "POLLY ONLINE" if (HAS_POLLY and engine is not None) else "NOT AVAILABLE"
        print(f"  Engine:     Amazon Polly")
    elif engine_type == "aquestalk":
        running = "AQUESTALK ONLINE" if (HAS_AQUESTALK and engine is not None) else "NOT AVAILABLE"
        print(f"  Engine:     AquesTalk10 (Yukkuri)")
        label = f"Yukkuri ({speaker_id})"
    else:
        try:
            version = engine.get_version()
        except Exception:
            version = "?"
        label = _resolve_speaker_label(engine, speaker_id)
        running = "RUNNING" if engine.is_running() else "NOT RESPONDING"
        print(f"  Engine:     VOICEVOX {version}")
    print(f"  Status:     {running}")
    print(f"  Voice:      {label}")
    print(f"  Speed:      {speed}")
    print(f"  Pitch:      {pitch}")
    print(f"  Intonation: {intonation}")
    print(f"  Sink:       {router.sink_name}")


def _show_speakers(engine):
    """Print every speaker and their style IDs."""
    try:
        speakers = engine.get_speakers()
    except Exception as exc:
        print(f"  Could not fetch speaker list: {exc}")
        return

    for sp in speakers:
        name = sp.get("name", "?")
        styles = sp.get("styles", [])
        if styles:
            items = ", ".join(
                f'{s.get("name", "?")} (ID {s.get("id", "?")})' for s in styles
            )
            print(f"  {name}: {items}")
        else:
            print(f"  {name}")


def repl(engine, edge_engine, polly_engine, aq_engine, engine_type, router, speaker_id,
         speed, pitch, intonation, history_file="~/.yukkuri_history"):
    """Interactive read-eval-speak loop."""

    _setup_readline(history_file)
    _print_header(engine, engine_type, speaker_id, speed, pitch, intonation)

    # Graceful exit on Ctrl+C and Ctrl+D
    def _sigint_handler(sig, frame):
        print()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint_handler)

    def _active():
        """Return the active engine instance for the current type."""
        if engine_type == "edge":
            return edge_engine
        elif engine_type == "polly":
            return polly_engine
        elif engine_type == "aquestalk":
            return aq_engine
        return engine

    while True:
        try:
            raw = input("> ").strip()
        except EOFError:  # Ctrl+D
            print()
            break

        if not raw:
            continue

        # -- command dispatch ------------------------------------------
        if raw.startswith("/"):
            parts = raw.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""

            if cmd in ("/quit", "/exit"):
                break

            elif cmd == "/help":
                _show_help(engine_type)

            elif cmd == "/status":
                _show_status(_active(), engine_type, router, speaker_id,
                             speed, pitch, intonation)

            elif cmd == "/engine":
                if not arg:
                    print(f"  Current engine: {engine_type}")
                elif arg == "edge" and HAS_EDGE:
                    if edge_engine is None:
                        try:
                            edge_engine = EdgeTTSEngine()
                        except Exception as exc:
                            print(f"  Failed to create Edge TTS engine: {exc}")
                            continue
                    engine_type = "edge"
                    speaker_id = "en-US-BrianNeural"
                    print("  Switched to Edge TTS (Brian)")
                elif arg == "polly" and HAS_POLLY:
                    if polly_engine is None:
                        try:
                            polly_engine = PollyEngine()
                        except Exception as exc:
                            print(f"  Failed to create Polly engine: {exc}")
                            print("  Check your AWS credentials.")
                            continue
                    engine_type = "polly"
                    speaker_id = "Brian"
                    print("  Switched to Amazon Polly (Brian — real Ivona)")
                elif arg == "aquestalk" and HAS_AQUESTALK:
                    if aq_engine is None:
                        try:
                            aq_engine = AquesTalkEngine()
                        except Exception as exc:
                            print(f"  Failed to create AquesTalk10 engine: {exc}")
                            print("  Ensure libAquesTalk10.so is available.")
                            continue
                    engine_type = "aquestalk"
                    speaker_id = "f1"
                    print("  Switched to AquesTalk10 (authentic Yukkuri voice)")
                elif arg == "voicevox":
                    engine_type = "voicevox"
                    speaker_id = 1
                    print("  Switched to VOICEVOX (Zundamon)")
                else:
                    print(f"  Unknown or unavailable engine: {arg}. "
                          f"Use 'voicevox', 'edge', 'polly', or 'aquestalk'")

            elif cmd == "/voice" and engine_type in ("edge", "polly", "aquestalk"):
                if engine_type == "edge":
                    voices_map = EDGE_POPULAR
                elif engine_type == "polly":
                    voices_map = POLLY_POPULAR
                else:
                    voices_map = AQUESTALK_POPULAR
                if not arg:
                    print(f"  Current voice: {speaker_id}")
                elif arg in voices_map:
                    speaker_id = voices_map[arg]
                    print(f"  Voice set to: {arg} → {speaker_id}")
                else:
                    speaker_id = arg
                    print(f"  Voice set to: {speaker_id}")

            elif cmd == "/voices":
                if engine_type == "edge" and HAS_EDGE and edge_engine:
                    print("  Quick voices: " + ", ".join(EDGE_POPULAR.keys()))
                    print("  Full names (use with /voice):")
                    try:
                        voices = edge_engine.list_voices()
                        en_us = [v for v in voices if v['locale'] == 'en-US']
                        for v in en_us:
                            g = {'Male': '♂', 'Female': '♀'}.get(v['gender'], '?')
                            print(f"    {g} {v['short_name']}")
                    except Exception as e:
                        print(f"  Could not list voices: {e}")
                elif engine_type == "polly" and HAS_POLLY and polly_engine:
                    print("  Quick voices: " + ", ".join(POLLY_POPULAR.keys()))
                    print("  All English voices:")
                    try:
                        voices = polly_engine.list_voices()
                        en_voices = [v for v in voices if v["LanguageCode"].startswith("en-")]
                        for v in sorted(en_voices, key=lambda x: x["Id"]):
                            engines = ", ".join(v.get("SupportedEngines", ["?"]))
                            print(f"    {v['Id']:20s} {v['Gender']:6s} "
                                  f"{v['LanguageCode']:6s} [{engines}]")
                    except Exception as e:
                        print(f"  Could not list voices: {e}")
                elif engine_type == "aquestalk" and HAS_AQUESTALK and aq_engine:
                    print("  AquesTalk10 voice presets:")
                    try:
                        for v in aq_engine.list_voices():
                            print(f"    {v['id']:6s}  {v['name']}")
                    except Exception as e:
                        print(f"    {', '.join(AQUESTALK_POPULAR.keys())}")
                else:
                    print("  No voice list available for current engine.")

            elif cmd == "/speakers" and engine_type == "voicevox":
                _show_speakers(engine)

            elif cmd == "/speaker" and engine_type == "voicevox":
                if not arg:
                    print(f"  Current speaker ID: {speaker_id}")
                else:
                    try:
                        new_id = int(arg.split()[0])
                    except ValueError:
                        print(f"  Invalid speaker ID: {arg.split()[0]}")
                        continue
                    # Validate against available speakers
                    try:
                        speakers = engine.get_speakers()
                        all_ids = {
                            s["id"]
                            for sp in speakers
                            for s in sp.get("styles", [])
                        }
                        if new_id not in all_ids:
                            print(f"  Speaker ID {new_id} not found. "
                                  f"Use /speakers to list available IDs.")
                            continue
                    except Exception:
                        pass  # Can't validate; let the engine reject if bad
                    speaker_id = new_id
                    label = _resolve_speaker_label(engine, speaker_id)
                    print(f"  Speaker set to {label} (ID {speaker_id})")

            elif cmd == "/speed":
                if not arg:
                    print(f"  Current speed: {speed}")
                else:
                    try:
                        val = float(arg.split()[0])
                        if 0.5 <= val <= 2.0:
                            speed = val
                            print(f"  Speed set to {speed}")
                        else:
                            print("  Speed must be between 0.5 and 2.0")
                    except ValueError:
                        print(f"  Invalid value: {arg.split()[0]}")

            elif cmd == "/pitch":
                if not arg:
                    print(f"  Current pitch: {pitch}")
                else:
                    try:
                        val = float(arg.split()[0])
                        if 0.5 <= val <= 2.0:
                            pitch = val
                            print(f"  Pitch set to {pitch}")
                        else:
                            print("  Pitch must be between 0.5 and 2.0")
                    except ValueError:
                        print(f"  Invalid value: {arg.split()[0]}")

            elif cmd == "/intonation":
                if not arg:
                    print(f"  Current intonation: {intonation}")
                else:
                    try:
                        val = float(arg.split()[0])
                        if 0.0 <= val <= 2.0:
                            intonation = val
                            print(f"  Intonation set to {intonation}")
                        else:
                            print("  Intonation must be between 0.0 and 2.0")
                    except ValueError:
                        print(f"  Invalid value: {arg.split()[0]}")

            else:
                # If it looks like a misspelled command, give a hint.
                token = cmd.lstrip("/")
                if token.isalpha():
                    print(f"  Unknown command: {cmd}.  Type /help for "
                          f"available commands.")
                else:
                    # Someone typed e.g. "/usr/bin" — speak it.
                    _speak(raw, _active(), engine_type, router, speaker_id,
                           speed, pitch, intonation)

        # -- text to speak ---------------------------------------------
        else:
            _speak(raw, _active(), engine_type, router, speaker_id,
                   speed, pitch, intonation)

    print("Goodbye!")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    cfg = load()

    vv_cfg = cfg["voicevox"]
    audio_cfg = cfg["audio"]
    app_cfg = cfg["app"]

    speaker_id = vv_cfg["speaker"]
    speed = float(app_cfg.get("speed_scale", 1.0))
    pitch = float(app_cfg.get("pitch_scale", 1.0))
    intonation = float(app_cfg.get("intonation_scale", 1.0))
    engine_type = app_cfg.get("engine", "voicevox")

    # Instantiate router ------------------------------------------------
    router = AudioRouter(
        sink_name=audio_cfg["sink_name"],
        sample_rate=audio_cfg.get("sample_rate", 48000),
        channels=audio_cfg.get("channels", 2),
    )

    try:
        router.ensure_sink_exists()
    except AudioRouterError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Instantiate engines ------------------------------------------------
    engine = None
    edge_engine = None
    polly_engine = None
    aq_engine = None

    if engine_type == "voicevox":
        engine = VoicevoxEngine(
            host=vv_cfg["host"], port=vv_cfg["port"],
            timeout=vv_cfg.get("timeout_seconds", 30),
        )
        if not engine.is_running():
            print(
                f"Error: Cannot reach VOICEVOX engine at "
                f"http://{vv_cfg['host']}:{vv_cfg['port']}",
                file=sys.stderr,
            )
            print("Make sure VOICEVOX is running.  E.g.:", file=sys.stderr)
            print("  ~/voicevox/voicevox_engine-linux-cpu-x64/run",
                  file=sys.stderr)
            sys.exit(1)
    elif engine_type == "edge" and HAS_EDGE:
        edge_engine = EdgeTTSEngine()
        speaker_id = "en-US-BrianNeural"
    elif engine_type == "polly" and HAS_POLLY:
        polly_engine = PollyEngine()
        speaker_id = "Brian"
    elif engine_type == "aquestalk" and HAS_AQUESTALK:
        aq_engine = AquesTalkEngine()
        speaker_id = "f1"
    else:
        # Default — try VOICEVOX first, then Polly, then Edge
        engine = VoicevoxEngine(
            host=vv_cfg["host"], port=vv_cfg["port"],
            timeout=vv_cfg.get("timeout_seconds", 30),
        )
        if engine.is_running():
            engine_type = "voicevox"
        elif HAS_POLLY:
            try:
                polly_engine = PollyEngine()
                engine_type = "polly"
                speaker_id = "Brian"
            except Exception:
                if HAS_AQUESTALK:
                    try:
                        aq_engine = AquesTalkEngine()
                        engine_type = "aquestalk"
                        speaker_id = "f1"
                    except Exception:
                        if HAS_EDGE:
                            try:
                                edge_engine = EdgeTTSEngine()
                                engine_type = "edge"
                                speaker_id = "en-US-BrianNeural"
                            except Exception as exc:
                                print(f"Error: No TTS engine available: {exc}",
                                      file=sys.stderr)
                                sys.exit(1)
                        else:
                            print("Error: No TTS engine available.", file=sys.stderr)
                            sys.exit(1)
                elif HAS_EDGE:
                    try:
                        edge_engine = EdgeTTSEngine()
                        engine_type = "edge"
                        speaker_id = "en-US-BrianNeural"
                    except Exception as exc:
                        print(f"Error: No TTS engine available: {exc}",
                              file=sys.stderr)
                        sys.exit(1)
                else:
                    print("Error: No TTS engine available.", file=sys.stderr)
                    sys.exit(1)
        elif HAS_AQUESTALK:
            try:
                aq_engine = AquesTalkEngine()
                engine_type = "aquestalk"
                speaker_id = "f1"
            except Exception as exc:
                if HAS_EDGE:
                    try:
                        edge_engine = EdgeTTSEngine()
                        engine_type = "edge"
                        speaker_id = "en-US-BrianNeural"
                    except Exception as exc2:
                        print(f"Error: No TTS engine available: {exc}, {exc2}",
                              file=sys.stderr)
                        sys.exit(1)
                else:
                    print(f"Error: No TTS engine available: {exc}", file=sys.stderr)
                    sys.exit(1)
        elif HAS_EDGE:
            try:
                edge_engine = EdgeTTSEngine()
                engine_type = "edge"
                speaker_id = "en-US-BrianNeural"
            except Exception as exc:
                print(f"Error: No TTS engine available: {exc}", file=sys.stderr)
                sys.exit(1)
        else:
            print("Error: No TTS engine available.", file=sys.stderr)
            sys.exit(1)

    def _active_engine():
        """Return the active engine instance for the current type."""
        if engine_type == "edge":
            return edge_engine
        elif engine_type == "polly":
            return polly_engine
        elif engine_type == "aquestalk":
            return aq_engine
        return engine

    # Mode dispatch -------------------------------------------------------
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
        if text.strip():
            _speak(text, _active_engine(), engine_type, router, speaker_id,
                   speed, pitch, intonation)

    elif not sys.stdin.isatty():
        text = sys.stdin.read()
        if text.strip():
            _speak(text, _active_engine(), engine_type, router, speaker_id,
                   speed, pitch, intonation)

    else:
        repl(engine, edge_engine, polly_engine, aq_engine, engine_type, router,
             speaker_id, speed, pitch, intonation,
             history_file=app_cfg.get("history_file", "~/.yukkuri_history"))


if __name__ == "__main__":
    main()
