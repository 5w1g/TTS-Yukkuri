#!/usr/bin/env python3
"""Yukkuri TTS — GUI application.

A clean tkinter interface for text-to-speech through VOICEVOX or Microsoft
Edge TTS into a PipeWire virtual microphone for Discord.

Requires: python3-tk (sudo apt install python3-tk)
          edge-tts (pip install --break-system-packages edge-tts) for Brian/etc.
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from config import load, save as save_config
from tts_engine import VoicevoxEngine, EngineNotRunning, SynthesisError, VoicevoxError
from audio_router import AudioRouter, AudioRouterError

# Edge TTS is optional
try:
    from tts_edge import EdgeTTSEngine, POPULAR_VOICES as EDGE_QUICK, DEFAULT_VOICE
    HAS_EDGE = True
except ImportError:
    HAS_EDGE = False
    EDGE_QUICK = {}
    DEFAULT_VOICE = "en-US-BrianNeural"

# Amazon Polly (real Ivona Brian) is optional
try:
    from tts_polly import PollyEngine, POPULAR_VOICES as POLLY_QUICK
    HAS_POLLY = True
except ImportError:
    HAS_POLLY = False
    POLLY_QUICK = {}
    PollyEngine = None

# ── Colours & Theme ──────────────────────────────────────────────────────────

BG = "#1e1e2e"
FG = "#cdd6f4"
ACCENT = "#cba6f7"
ACCENT_HOVER = "#b4befe"
SURFACE = "#313244"
SURFACE_RAISED = "#45475a"
RED = "#f38ba8"
GREEN = "#a6e3a1"
YELLOW = "#f9e2af"
BLUE = "#89b4fa"
FONT = ("Sans", 11)
FONT_BOLD = ("Sans", 11, "bold")
FONT_SMALL = ("Sans", 9)
FONT_TITLE = ("Sans", 14, "bold")

# ── Voice Presets ────────────────────────────────────────────────────────────

PRESETS = {
    "Normal":      {"speed": 1.0, "pitch": 1.0, "intonation": 1.0},
    "Yukkuri":     {"speed": 0.7, "pitch": 1.2, "intonation": 1.0},
    "Fast":        {"speed": 1.5, "pitch": 1.0, "intonation": 1.0},
    "High Pitch":  {"speed": 1.0, "pitch": 1.5, "intonation": 1.0},
    "Whisper":     {"speed": 0.8, "pitch": 0.9, "intonation": 0.5},
    "Energetic":   {"speed": 1.2, "pitch": 1.3, "intonation": 1.5},
}

# ── Main Application ─────────────────────────────────────────────────────────

class YukkuriApp:
    """Main GUI application window."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Yukkuri TTS")
        self.root.geometry("620x620")
        self.root.configure(bg=BG)
        self.root.resizable(True, True)
        self.root.minsize(500, 500)

        # Load config
        self.cfg = load()
        vv = self.cfg["voicevox"]
        audio = self.cfg["audio"]
        app_cfg = self.cfg["app"]

        # Backend
        self.engine = VoicevoxEngine(
            host=vv["host"], port=vv["port"],
            timeout=vv.get("timeout_seconds", 30),
        )
        self.edge_engine = None
        if HAS_EDGE:
            try:
                self.edge_engine = EdgeTTSEngine()
            except Exception:
                pass

        self.polly_engine = None
        if HAS_POLLY:
            try:
                self.polly_engine = PollyEngine()
            except Exception:
                pass

        self.router = AudioRouter(sink_name=audio["sink_name"])

        # Engine mode: "voicevox", "edge", or "polly"
        self.engine_type = app_cfg.get("engine", "voicevox")
        if self.engine_type == "edge" and not self.edge_engine:
            self.engine_type = "voicevox"
        if self.engine_type == "polly" and not self.polly_engine:
            self.engine_type = "voicevox"

        # Current voice settings
        self.speaker_id = tk.StringVar(value=str(vv["speaker"]))
        # Ensure correct default if starting in non-VOICEVOX mode
        if self.engine_type == "edge":
            saved_voice = app_cfg.get("voice", DEFAULT_VOICE)
            self.speaker_id.set(saved_voice)
        elif self.engine_type == "polly":
            saved_voice = app_cfg.get("voice", "Brian")
            self.speaker_id.set(saved_voice)

        self.speed = tk.DoubleVar(value=app_cfg.get("speed_scale", 1.0))
        self.pitch = tk.DoubleVar(value=app_cfg.get("pitch_scale", 1.0))
        self.intonation = tk.DoubleVar(value=app_cfg.get("intonation_scale", 1.0))

        # Voice dropdown data
        self.speakers_list = []
        self.speaker_map = {}      # "Name — Style" -> style_id  (VOICEVOX)
        self.edge_voice_map = {}   # "Brian (en-US-BrianNeural)" -> short_name

        # Remember voice selection per engine type
        self._voice_memory = {
            "voicevox": str(vv["speaker"]),
            "edge": app_cfg.get("voice", DEFAULT_VOICE),
            "polly": app_cfg.get("voice", "Brian"),
        }

        # Playback lock
        self._speaking = False
        self._pending = False

        # Background voice-loading thread handle
        self._voice_loader = None

        # Build UI
        self._build_ui()
        self._refresh_voices()

        # Startup checks
        self.root.after(100, self._startup_check)

    # ── UI Construction ──────────────────────────────────────────────────

    def _build_ui(self):
        """Construct all UI elements."""
        # -- Title bar --
        title_frame = tk.Frame(self.root, bg=BG)
        title_frame.pack(fill="x", padx=16, pady=(14, 0))

        tk.Label(
            title_frame, text="Yukkuri TTS", font=FONT_TITLE,
            bg=BG, fg=ACCENT,
        ).pack(side="left")

        self.status_dot = tk.Canvas(
            title_frame, width=10, height=10, bg=BG, highlightthickness=0,
        )
        self.status_dot.pack(side="right", padx=(8, 0))
        self._draw_dot(GREEN)

        self.status_label = tk.Label(
            title_frame, text="Starting...", font=FONT_SMALL, bg=BG, fg=FG,
        )
        self.status_label.pack(side="right")

        # -- Engine toggle --
        engine_row = tk.Frame(self.root, bg=BG)
        engine_row.pack(fill="x", padx=16, pady=(10, 0))

        tk.Label(
            engine_row, text="Engine:", font=FONT_SMALL, bg=BG, fg=FG,
        ).pack(side="left", padx=(0, 8))

        self.btn_vv = tk.Button(
            engine_row, text="VOICEVOX", font=FONT_SMALL,
            bg=ACCENT if self.engine_type == "voicevox" else SURFACE_RAISED,
            fg=BG if self.engine_type == "voicevox" else FG,
            activebackground=ACCENT, activeforeground=BG,
            relief="flat", padx=12, pady=3, cursor="hand2",
            command=lambda: self._switch_engine("voicevox"),
        )
        self.btn_vv.pack(side="left", padx=(0, 4))

        self.btn_edge = tk.Button(
            engine_row, text="Edge TTS", font=FONT_SMALL,
            bg=ACCENT if self.engine_type == "edge" else SURFACE_RAISED,
            fg=BG if self.engine_type == "edge" else FG,
            activebackground=ACCENT, activeforeground=BG,
            relief="flat", padx=12, pady=3, cursor="hand2",
            command=lambda: self._switch_engine("edge"),
        )
        self.btn_edge.pack(side="left", padx=(0, 4))
        if not HAS_EDGE or self.edge_engine is None:
            reason = "not installed" if not HAS_EDGE else "init failed"
            self.btn_edge.config(
                state="disabled", text=f"Edge TTS ({reason})",
                bg=SURFACE, fg=SURFACE_RAISED,
            )

        self.btn_polly = tk.Button(
            engine_row, text="Polly", font=FONT_SMALL,
            bg=ACCENT if self.engine_type == "polly" else SURFACE_RAISED,
            fg=BG if self.engine_type == "polly" else FG,
            activebackground=ACCENT, activeforeground=BG,
            relief="flat", padx=12, pady=3, cursor="hand2",
            command=lambda: self._switch_engine("polly"),
        )
        self.btn_polly.pack(side="left")
        if not HAS_POLLY or self.polly_engine is None:
            reason = "not installed" if not HAS_POLLY else "init failed"
            self.btn_polly.config(
                state="disabled", text=f"Polly ({reason})",
                bg=SURFACE, fg=SURFACE_RAISED,
            )

        self.engine_footer = tk.Label(
            engine_row, text="", font=FONT_SMALL, bg=BG, fg=SURFACE_RAISED,
        )
        self.engine_footer.pack(side="right")

        # -- Text input --
        input_frame = tk.Frame(self.root, bg=SURFACE, padx=4, pady=4)
        input_frame.pack(fill="x", padx=16, pady=(10, 4))

        self.text_entry = tk.Entry(
            input_frame, font=FONT,
            bg=SURFACE, fg=FG,
            insertbackground=ACCENT,
            relief="flat", highlightthickness=0,
        )
        self.text_entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(8, 4))
        self.text_entry.bind("<Return>", lambda e: self._do_speak())
        self.text_entry.focus_set()

        self.speak_btn = tk.Button(
            input_frame, text="Speak", font=FONT_BOLD,
            bg=ACCENT, fg=BG,
            activebackground=ACCENT_HOVER, activeforeground=BG,
            relief="flat", padx=20, pady=6,
            cursor="hand2",
            command=self._do_speak,
        )
        self.speak_btn.pack(side="right", padx=(4, 4))

        # -- Voice settings section --
        settings_label = tk.Label(
            self.root, text="Voice Settings", font=FONT_BOLD, bg=BG, fg=ACCENT,
        )
        settings_label.pack(anchor="w", padx=20, pady=(14, 4))

        settings_frame = tk.Frame(self.root, bg=SURFACE)
        settings_frame.pack(fill="x", padx=16, ipady=8)

        # Voice dropdown
        self.voice_list_label = tk.Label(
            settings_frame, text="Voice", font=FONT_SMALL,
            bg=SURFACE, fg=FG,
        )
        self.voice_list_label.pack(anchor="w", padx=14, pady=(10, 2))

        voice_frame = tk.Frame(settings_frame, bg=SURFACE)
        voice_frame.pack(fill="x", padx=14, pady=(0, 4))

        self.voice_combo = ttk.Combobox(
            voice_frame, font=FONT, state="readonly",
        )
        self.voice_combo.pack(fill="x", ipady=2)
        self.voice_combo.bind("<<ComboboxSelected>>", self._on_voice_changed)

        # Sliders
        self._build_slider(settings_frame, "Speed", self.speed, 0.5, 2.0, 0.05)
        self._build_slider(settings_frame, "Pitch", self.pitch, 0.5, 2.0, 0.05)
        self._build_slider(settings_frame, "Intonation", self.intonation, 0.0, 2.0, 0.05)

        # -- Presets --
        presets_label = tk.Label(
            self.root, text="Presets", font=FONT_BOLD, bg=BG, fg=ACCENT,
        )
        presets_label.pack(anchor="w", padx=20, pady=(12, 4))

        presets_frame = tk.Frame(self.root, bg=BG)
        presets_frame.pack(fill="x", padx=16)

        for name, vals in PRESETS.items():
            btn = tk.Button(
                presets_frame, text=name, font=FONT_SMALL,
                bg=SURFACE_RAISED, fg=FG,
                activebackground=ACCENT, activeforeground=BG,
                relief="flat", padx=12, pady=4,
                cursor="hand2",
                command=lambda n=name, v=vals: self._apply_preset(n, v),
            )
            btn.pack(side="left", padx=(0, 6), pady=2)

        # -- History --
        history_label = tk.Label(
            self.root, text="Recent", font=FONT_BOLD, bg=BG, fg=ACCENT,
        )
        history_label.pack(anchor="w", padx=20, pady=(12, 4))

        self.history_list = tk.Listbox(
            self.root, font=FONT_SMALL,
            bg=SURFACE, fg=FG,
            selectbackground=ACCENT, selectforeground=BG,
            relief="flat", highlightthickness=0,
            height=4,
        )
        self.history_list.pack(fill="x", padx=16)
        self.history_list.bind("<Double-Button-1>", self._on_history_double_click)

        self._history = self._load_history()
        for phrase in reversed(self._history[-20:]):
            self.history_list.insert("end", phrase)

        # -- Footer --
        self.footer_label = tk.Label(
            self.root, text="", font=FONT_SMALL, bg=BG, fg=SURFACE_RAISED,
        )
        self.footer_label.pack(side="bottom", pady=(8, 6))
        self._update_footer()

    def _build_slider(self, parent, label, variable, min_val, max_val, step):
        """Build a labeled slider row."""
        row = tk.Frame(parent, bg=SURFACE)
        row.pack(fill="x", padx=14, pady=2)

        tk.Label(
            row, text=label, font=FONT_SMALL, bg=SURFACE, fg=FG,
            width=10, anchor="w",
        ).pack(side="left")

        value_label = tk.Label(
            row, text="1.0", font=FONT_SMALL, bg=SURFACE, fg=ACCENT, width=5,
        )

        def _update_label(*_):
            value_label.config(text=f"{variable.get():.2f}")

        variable.trace_add("write", _update_label)
        _update_label()

        scale = ttk.Scale(
            row, from_=min_val, to=max_val, variable=variable,
            orient="horizontal",
        )
        scale.pack(side="left", fill="x", expand=True, padx=(0, 8))
        value_label.pack(side="right")

    # ── Engine Switching ──────────────────────────────────────────────────

    def _switch_engine(self, engine_type):
        """Switch between VOICEVOX, Edge TTS, and Amazon Polly."""
        if engine_type == self.engine_type:
            return
        if engine_type == "edge" and not self.edge_engine:
            messagebox.showwarning(
                "Edge TTS not available",
                "Install edge-tts first:\n"
                "pip install --break-system-packages edge-tts",
            )
            return
        if engine_type == "polly" and not self.polly_engine:
            messagebox.showwarning(
                "Amazon Polly not available",
                "Install boto3 and configure AWS credentials:\n"
                "pip install --break-system-packages boto3\n"
                "aws configure",
            )
            return

        self.engine_type = engine_type

        # Reset all buttons to inactive (skip disabled buttons)
        for btn in [self.btn_vv, self.btn_edge, self.btn_polly]:
            if btn.cget("state") != "disabled":
                btn.config(bg=SURFACE_RAISED, fg=FG)

        # Highlight active button and restore saved voice for this engine
        if engine_type == "voicevox":
            self.btn_vv.config(bg=ACCENT, fg=BG)
            self.speaker_id.set(self._voice_memory.get("voicevox",
                                str(self.cfg["voicevox"]["speaker"])))
        elif engine_type == "edge":
            self.btn_edge.config(bg=ACCENT, fg=BG)
            self.speaker_id.set(self._voice_memory.get("edge", DEFAULT_VOICE))
        elif engine_type == "polly":
            self.btn_polly.config(bg=ACCENT, fg=BG)
            self.speaker_id.set(self._voice_memory.get("polly", "Brian"))

        self._refresh_voices()
        self._update_footer()
        self._startup_check()

    def _update_footer(self):
        """Update footer text based on current engine."""
        if self.engine_type == "edge":
            self.footer_label.config(text="Edge TTS (Brian, Guy…) → Virtual Mic → Discord")
        elif self.engine_type == "polly":
            self.footer_label.config(text="Amazon Polly (real Ivona Brian) → Virtual Mic → Discord")
        else:
            v = "?"
            try:
                v = self.engine.get_version()
            except Exception:
                pass
            self.footer_label.config(text=f"VOICEVOX {v} → Virtual Mic → Discord")

    # ── Voice Dropdown ────────────────────────────────────────────────────

    def _refresh_voices(self):
        """Populate the voice dropdown for the current engine.

        For polly and edge, voice lists are fetched in a background
        thread to avoid freezing the UI on slow networks.
        """
        if self.engine_type == "voicevox":
            self.voice_list_label.config(text="Speaker")
            self._populate_vv_speakers()
        elif self.engine_type == "edge":
            self.voice_list_label.config(text="Voice")
            self.voice_combo.config(values=["Loading voices..."])
            self.voice_combo.set("Loading voices...")
            self._load_edge_voices_async()
        elif self.engine_type == "polly":
            self.voice_list_label.config(text="Voice")
            self.voice_combo.config(values=["Loading voices..."])
            self.voice_combo.set("Loading voices...")
            self._load_polly_voices_async()

    def _load_edge_voices_async(self):
        """Fetch Edge TTS voice list in a background thread."""
        eng = self.edge_engine
        current_voice = self.speaker_id.get()

        def _worker():
            names = []
            voice_map = {}
            current_name = None
            # Quick-access popular voices
            for friendly, short in EDGE_QUICK.items():
                label = f"{friendly} ({short})"
                names.append(label)
                voice_map[label] = short
                if short == current_voice:
                    current_name = label
            # Full en-US list from API
            try:
                if eng:
                    voices = eng.list_voices()
                    en_us = [v for v in voices if v['locale'] == 'en-US']
                    for v in en_us:
                        short = v['short_name']
                        if short in EDGE_QUICK.values():
                            continue
                        g = {'Male': '♂', 'Female': '♀'}.get(v['gender'], '?')
                        label = f"{g} {v['name'].split(' - ')[0].replace('Microsoft ','')} ({short})"
                        names.append(label)
                        voice_map[label] = short
                        if short == current_voice:
                            current_name = label
            except Exception:
                pass
            self.root.after(0, lambda: self._on_voices_loaded(
                names, voice_map, current_name
            ))

        threading.Thread(target=_worker, daemon=True).start()

    def _load_polly_voices_async(self):
        """Fetch Polly voice list in a background thread."""
        eng = self.polly_engine
        current_voice = self.speaker_id.get()

        def _worker():
            names = []
            voice_map = {}
            current_name = None
            # Quick-access popular voices
            for friendly, voice_id in POLLY_QUICK.items():
                label = f"{friendly} ({voice_id})"
                names.append(label)
                voice_map[label] = voice_id
                if voice_id == current_voice:
                    current_name = label
            # Full English voice list from API
            try:
                if eng:
                    voices = eng.list_voices()
                    en_voices = [v for v in voices if v["LanguageCode"].startswith("en-")]
                    for v in sorted(en_voices, key=lambda x: x["Id"]):
                        vid = v["Id"]
                        if vid in POLLY_QUICK.values():
                            continue
                        engines_str = ", ".join(v.get("SupportedEngines", ["?"]))
                        g = {"Male": "♂", "Female": "♀"}.get(v.get("Gender", "?"), "?")
                        label = f"{g} {vid} ({v['LanguageCode']}) [{engines_str}]"
                        names.append(label)
                        voice_map[label] = vid
                        if vid == current_voice:
                            current_name = label
            except Exception:
                pass
            self.root.after(0, lambda: self._on_voices_loaded(
                names, voice_map, current_name
            ))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_voices_loaded(self, names, voice_map, current_name):
        """Callback: update voice dropdown after background fetch."""
        self.edge_voice_map = voice_map
        self.voice_combo.config(values=names)
        if current_name:
            self.voice_combo.set(current_name)
        elif names:
            self.voice_combo.set(names[0])

    def _populate_vv_speakers(self):
        """Populate dropdown with VOICEVOX speakers."""
        try:
            if not self.engine.is_running():
                self.voice_combo.config(values=["VOICEVOX not running..."])
                self.voice_combo.set("VOICEVOX not running...")
                return
            self.speakers_list = self.engine.get_speakers()
            self.speaker_map.clear()
            names = []
            current_name = None
            current_id = int(self.speaker_id.get()) if self.speaker_id.get().isdigit() else 1
            for sp in self.speakers_list:
                sp_name = sp.get("name", "?")
                for style in sp.get("styles", []):
                    label = f"{sp_name} — {style['name']} (ID {style['id']})"
                    names.append(label)
                    self.speaker_map[label] = style["id"]
                    if style["id"] == current_id:
                        current_name = label
            self.voice_combo.config(values=names)
            if current_name:
                self.voice_combo.set(current_name)
            elif names:
                self.voice_combo.set(names[0])
                # Set to first voice's ID
                first_key = names[0]
                self.speaker_id.set(str(self.speaker_map[first_key]))
        except VoicevoxError:
            self.voice_combo.config(values=["Failed to load speakers"])
            self.voice_combo.set("Failed to load speakers")

    def _on_voice_changed(self, event=None):
        """Handle voice dropdown selection."""
        selection = self.voice_combo.get()
        if self.engine_type in ("edge", "polly"):
            if selection in self.edge_voice_map:
                voice_id = self.edge_voice_map[selection]
                self.speaker_id.set(voice_id)
                self._voice_memory[self.engine_type] = voice_id
            elif selection != "Loading voices...":
                self.status_label.config(
                    text=f"Unknown voice: {selection}", fg=YELLOW)
        else:
            if selection in self.speaker_map:
                sid = str(self.speaker_map[selection])
                self.speaker_id.set(sid)
                self._voice_memory["voicevox"] = sid

    # ── Speak ─────────────────────────────────────────────────────────────

    def _do_speak(self):
        """Synthesize and speak the current text."""
        if self._speaking:
            self._pending = True
            return

        text = self.text_entry.get().strip()
        if not text:
            return

        # Add to history
        if text not in self._history:
            self._history.append(text)
            self._save_history()
            self.history_list.insert(0, text)
            while self.history_list.size() > 20:
                self.history_list.delete("end")

        self.text_entry.delete(0, "end")
        self._speaking = True
        self.speak_btn.config(state="disabled", text="Speaking...")
        self.status_label.config(text="Synthesizing...", fg=YELLOW)

        engine_type = self.engine_type
        voice = self.speaker_id.get()
        speed = self.speed.get()
        pitch = self.pitch.get()
        intonation = self.intonation.get()

        # Capture engine references for the worker thread
        vv_engine = self.engine
        edge_eng = self.edge_engine
        polly_eng = self.polly_engine

        def _worker():
            try:
                if engine_type == "edge":
                    # Convert speed/pitch to edge-tts format
                    rate_str = f"{int((speed - 1.0) * 100):+.0f}%"
                    pitch_hz = f"{int((pitch - 1.0) * 12):+d}Hz"
                    audio = edge_eng.synthesize(
                        text, voice=voice, rate=rate_str, pitch=pitch_hz,
                    )
                elif engine_type == "polly":
                    # Convert speed → Polly rate
                    if speed <= 0.6:
                        polly_rate = "x-slow"
                    elif speed <= 0.85:
                        polly_rate = "slow"
                    elif speed <= 1.25:
                        polly_rate = "medium"
                    elif speed <= 1.7:
                        polly_rate = "fast"
                    else:
                        polly_rate = "x-fast"
                    # Pass pitch if non-default, intonation maps to volume
                    kwargs = {"rate": polly_rate}
                    if pitch != 1.0:
                        kwargs["pitch"] = f"{int((pitch - 1.0) * 100):+d}%"
                    if intonation != 1.0:
                        if intonation < 1.0:
                            kwargs["volume"] = "soft" if intonation < 0.7 else "x-soft"
                        else:
                            kwargs["volume"] = "loud" if intonation > 1.3 else "x-loud"
                    audio = polly_eng.synthesize(
                        text, voice=voice, **kwargs,
                    )
                else:
                    sid = int(voice) if voice.isdigit() else 1
                    audio = vv_engine.synthesize(
                        text, speaker=sid,
                        speed_scale=speed, pitch_scale=pitch,
                        intonation_scale=intonation,
                    )
                self.root.after(0, lambda: self.status_label.config(
                    text="Playing...", fg=YELLOW,
                ))
                self.router.play_wav(audio)
                self.root.after(0, self._on_speak_done)
            except EngineNotRunning:
                self.root.after(0, lambda: self._on_speak_error(
                    "VOICEVOX not running. Start the engine first."
                ))
            except SynthesisError as e:
                self.root.after(0, lambda: self._on_speak_error(str(e)))
            except AudioRouterError as e:
                self.root.after(0, lambda: self._on_speak_error(str(e)))
            except Exception as e:
                self.root.after(0, lambda: self._on_speak_error(
                    f"Error: {e}"
                ))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_speak_done(self):
        """Called when speech completes successfully."""
        self._speaking = False
        self.speak_btn.config(state="normal", text="Speak")
        self.status_label.config(text="Ready", fg=GREEN)
        self._draw_dot(GREEN)
        self.text_entry.focus_set()
        if self._pending:
            self._pending = False
            self._do_speak()

    def _on_speak_error(self, msg):
        """Called when speech fails."""
        self._speaking = False
        self.speak_btn.config(state="normal", text="Speak")
        self.status_label.config(text=msg[:80], fg=RED)
        self._draw_dot(RED)
        messagebox.showerror("TTS Error", msg)
        self.text_entry.focus_set()

    def _apply_preset(self, name, values):
        """Apply a voice preset."""
        self.speed.set(values["speed"])
        self.pitch.set(values["pitch"])
        self.intonation.set(values["intonation"])
        self.status_label.config(text=f"Preset: {name}", fg=ACCENT)

    def _on_history_double_click(self, event=None):
        """Replay a history item on double click."""
        idx = self.history_list.curselection()
        if idx:
            self.text_entry.delete(0, "end")
            self.text_entry.insert(0, self.history_list.get(idx[0]))
            self._do_speak()

    # ── Startup & Refresh ─────────────────────────────────────────────────

    def _startup_check(self):
        """Check engine and sink status on startup."""
        engine_ok = False
        sink_ok = False

        if self.engine_type == "edge":
            engine_ok = self.edge_engine is not None
            if engine_ok:
                self.root.title("Yukkuri TTS — Edge TTS")
                self.engine_footer.config(text="☁ Online (no local engine needed)")
            else:
                self.engine_footer.config(text="Not installed")
        elif self.engine_type == "polly":
            engine_ok = self.polly_engine is not None
            if engine_ok:
                self.root.title("Yukkuri TTS — Amazon Polly")
                self.engine_footer.config(text="☁ Online (real Ivona Brian)")
            else:
                self.engine_footer.config(text="Not installed")
        else:
            if self.engine.is_running():
                engine_ok = True
                try:
                    version = self.engine.get_version()
                    self.root.title(f"Yukkuri TTS — VOICEVOX {version}")
                except Exception:
                    self.root.title("Yukkuri TTS — VOICEVOX")
                self.engine_footer.config(text="● Connected")
            else:
                self.root.title("Yukkuri TTS — VOICEVOX (offline)")
                self.status_label.config(
                    text="VOICEVOX not running — start the engine first", fg=RED,
                )
                self._draw_dot(RED)
                self.engine_footer.config(text="○ Not connected")

        try:
            sink_ok = self.router.ensure_sink_exists()
        except AudioRouterError:
            pass

        if engine_ok and sink_ok:
            self.status_label.config(text="Ready — type and press Enter", fg=GREEN)
            self._draw_dot(GREEN)
        elif engine_ok and not sink_ok:
            self.status_label.config(
                text="Virtual mic missing — restart PipeWire", fg=YELLOW,
            )
            self._draw_dot(YELLOW)
        else:
            self.status_label.config(
                text=f"{'Polly' if self.engine_type == 'polly' else 'Edge TTS'} "
                     f"not available — check credentials or install",
                fg=RED,
            )
            self._draw_dot(RED)

    # ── History Persistence ───────────────────────────────────────────────

    def _load_history(self):
        hist_path = os.path.expanduser(
            self.cfg["app"].get("history_file", "~/.yukkuri_history"))
        try:
            if os.path.exists(hist_path):
                with open(hist_path) as f:
                    return [line.rstrip("\n") for line in f if line.strip()]
        except OSError:
            pass
        return []

    def _save_history(self):
        hist_path = os.path.expanduser(
            self.cfg["app"].get("history_file", "~/.yukkuri_history"))
        try:
            os.makedirs(os.path.dirname(hist_path) or ".", exist_ok=True)
            with open(hist_path, "w") as f:
                for phrase in self._history[-200:]:
                    f.write(phrase + "\n")
        except OSError:
            pass

    # ── Helpers ───────────────────────────────────────────────────────────

    def _draw_dot(self, color):
        self.status_dot.delete("all")
        self.status_dot.create_oval(0, 0, 10, 10, fill=color, outline="")

    def run(self):
        def _on_close():
            if self.engine_type == "voicevox" and self.speaker_id.get().isdigit():
                self.cfg["voicevox"]["speaker"] = int(self.speaker_id.get())
            # Save voice selection for polly/edge too
            if self.engine_type != "voicevox":
                self.cfg["app"]["voice"] = self.speaker_id.get()
            self.cfg["app"]["speed_scale"] = self.speed.get()
            self.cfg["app"]["pitch_scale"] = self.pitch.get()
            self.cfg["app"]["intonation_scale"] = self.intonation.get()
            self.cfg["app"]["engine"] = self.engine_type
            save_config(self.cfg)
            self.router.cleanup()
            self.root.destroy()

        self.root.protocol("WM_DELETE_WINDOW", _on_close)
        self.root.mainloop()


def main():
    app = YukkuriApp()
    app.run()


if __name__ == "__main__":
    main()
