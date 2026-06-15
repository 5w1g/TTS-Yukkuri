"""Microsoft Edge TTS engine client.

Uses the free Edge TTS API (via edge-tts library) to access Microsoft's
neural voices — including Brian, the popular Twitch donation voice.

Install: pip install --break-system-packages edge-tts
"""

import asyncio
import os
import subprocess
import tempfile
import threading


# ── Popular voices for quick reference ──────────────────────────────────────

POPULAR_VOICES = {
    # Twitch classics
    "brian":          "en-US-BrianNeural",
    "guy":            "en-US-GuyNeural",
    "eric":           "en-US-EricNeural",
    "roger":          "en-US-RogerNeural",
    "steffan":        "en-US-SteffanNeural",
    "christopher":    "en-US-ChristopherNeural",
    # Female popular
    "aria":           "en-US-AriaNeural",
    "jenny":          "en-US-JennyNeural",
    "ana":            "en-US-AnaNeural",
    "michelle":       "en-US-MichelleNeural",
    "emma":           "en-US-EmmaNeural",
    "ava":            "en-US-AvaNeural",
    # Japanese
    "nanami":         "ja-JP-NanamiNeural",
    "keita":          "ja-JP-KeitaNeural",
}

DEFAULT_VOICE = "en-US-BrianNeural"


class EdgeTTSError(Exception):
    """Edge TTS failure."""
    pass


class EdgeTTSEngine:
    """TTS engine using Microsoft Edge's free TTS API.

    Provides access to hundreds of neural voices including the famous
    Brian voice used by Twitch streamers for donation TTS.

    Usage:
        engine = EdgeTTSEngine()
        voices = engine.list_voices()        # list available voices
        wav = engine.synthesize("Hello!", voice="en-US-BrianNeural")
    """

    def __init__(self):
        self._voices = None
        self._voice_list = None

    def is_available(self):
        """Check if edge-tts is installed and working."""
        try:
            import edge_tts
            return True
        except ImportError:
            return False

    def list_voices(self):
        """Get list of available voices.

        Returns:
            list of dicts with ShortName, FriendlyName, Gender, Locale.
        """
        if self._voice_list is not None:
            return self._voice_list

        async def _fetch():
            import edge_tts
            mgr = await edge_tts.VoicesManager.create()
            return [
                {
                    "short_name": v["ShortName"],
                    "name": v.get("FriendlyName", v["ShortName"]),
                    "gender": v.get("Gender", "?"),
                    "locale": v.get("Locale", "?"),
                }
                for v in mgr.voices
            ]

        self._voice_list = self._run_async(_fetch())
        return self._voice_list

    def synthesize(self, text, voice=DEFAULT_VOICE, rate="+0%", pitch="+0Hz"):
        """Synthesize text to MP3 bytes (pw-play handles MP3 natively).

        Args:
            text: Text to speak (English, Japanese, or any supported language).
            voice: Voice short name (e.g. "en-US-BrianNeural").
            rate: Speaking rate ("-50%" to "+100%").
            pitch: Pitch shift ("-20Hz" to "+20Hz").

        Returns:
            bytes containing an MP3 file.
        """
        import edge_tts

        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            out_path = f.name

        try:
            self._run_async(communicate.save(out_path))
            with open(out_path, "rb") as f:
                return f.read()
        finally:
            try:
                os.unlink(out_path)
            except OSError:
                pass

    def synthesize_to_file(self, text, voice=DEFAULT_VOICE,
                           output_path=None, rate="+0%", pitch="+0Hz"):
        """Synthesize and save directly to a file."""
        import edge_tts

        if output_path is None:
            output_path = tempfile.mktemp(suffix=".mp3")

        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        self._run_async(communicate.save(output_path))
        return output_path

    def _run_async(self, coro):
        """Run an async coroutine in a way that works even if an event
        loop is already running (e.g. inside a tkinter thread)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop — use asyncio.run()
            return asyncio.run(coro)

        # A loop is already running — run the coroutine in a new thread
        result = None
        error = None

        def _runner():
            nonlocal result, error
            try:
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                result = new_loop.run_until_complete(coro)
                new_loop.close()
            except Exception as e:
                error = e

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join()

        if error:
            raise error
        return result
