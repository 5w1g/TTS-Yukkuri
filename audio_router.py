"""Audio routing via PipeWire virtual sink.

Manages the virtual audio sink and plays WAV audio into it so that
the sink's monitor output can be captured by Discord as a microphone.
"""

import os
import subprocess
import tempfile
import time


class AudioRouterError(Exception):
    """Audio routing or playback failure."""
    pass


class AudioRouter:
    """Routes audio playback to a PipeWire virtual sink.

    The virtual sink (created by PipeWire config) accepts audio playback.
    Its monitor output is available as a capture source that Discord
    can select as a microphone input.

    Usage:
        router = AudioRouter(sink_name="yukkuri_sink")
        router.ensure_sink_exists()
        router.play_wav(wav_bytes)
    """

    def __init__(self, sink_name="yukkuri_sink", sample_rate=48000, channels=2):
        self.sink_name = sink_name
        self.sample_rate = sample_rate
        self.channels = channels
        self._temp_files = []

    def ensure_sink_exists(self):
        """Check if the virtual sink and source exist. Create links if needed.

        The sink and source are expected to be created persistently via
        ~/.config/pipewire/pipewire.conf.d/99-yukkuri.conf

        Links from sink monitor → source input are auto-created so that
        audio played into the sink appears on the virtual microphone.
        """
        if not self._sink_exists():
            raise AudioRouterError(
                f"Virtual sink '{self.sink_name}' not found.\n"
                f"Make sure ~/.config/pipewire/pipewire.conf.d/99-yukkuri.conf "
                f"is configured and PipeWire has been restarted.\n"
                f"Run: systemctl --user restart pipewire pipewire-pulse"
            )
        self._ensure_links()
        return True

    def _ensure_links(self):
        """Ensure monitor→source links exist for the virtual mic."""
        source_name = self.sink_name.replace("_sink", "_source")
        links_needed = [
            (f"{self.sink_name}:monitor_FL", f"{source_name}:input_FL"),
            (f"{self.sink_name}:monitor_FR", f"{source_name}:input_FR"),
        ]
        # Also remove any spurious auto-links from source inputs to sink playback
        bad_links = [
            (f"{source_name}:input_FL", f"{self.sink_name}:playback_FL"),
            (f"{source_name}:input_FR", f"{self.sink_name}:playback_FR"),
        ]

        for out_port, in_port in bad_links:
            try:
                subprocess.run(
                    ["pw-link", "-d", out_port, in_port],
                    capture_output=True, timeout=5,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        for out_port, in_port in links_needed:
            # Check if link already exists
            try:
                result = subprocess.run(
                    ["pw-link", "-l"], capture_output=True,
                    text=True, timeout=5,
                )
                if f"{out_port}\n  |-> {in_port}" in result.stdout:
                    continue  # Link already exists
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
            # Create the link
            try:
                subprocess.run(
                    ["pw-link", out_port, in_port],
                    capture_output=True, timeout=5,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

    def _sink_exists(self):
        """Check if the sink node exists in PipeWire."""
        try:
            result = subprocess.run(
                ["pw-dump"],
                capture_output=True, text=True, timeout=10,
            )
            # Quick check — more thorough would be to parse JSON
            return f'"node.name","{self.sink_name}"' in result.stdout or \
                   f'"node.name": "{self.sink_name}"' in result.stdout or \
                   f'"node.name":"{self.sink_name}"' in result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def list_sinks(self):
        """List available PipeWire sinks (for debugging)."""
        try:
            result = subprocess.run(
                ["pw-cli", "list-objects"],
                capture_output=True, text=True, timeout=10,
            )
            sinks = []
            for line in result.stdout.split("\n"):
                if "node.name" in line or "media.class" in line:
                    sinks.append(line.strip())
            return sinks
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

    def play_wav(self, wav_data):
        """Play WAV audio through the virtual sink. Blocks until complete.

        Args:
            wav_data: bytes of a WAV file.

        Returns:
            True on success.

        Raises:
            AudioRouterError: Playback failed.
        """
        tmp_path = self._write_temp_wav(wav_data)

        try:
            result = subprocess.run(
                ["pw-play", "--target", self.sink_name, tmp_path],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                stderr = result.stderr.strip()
                raise AudioRouterError(
                    f"pw-play failed (exit {result.returncode}): {stderr}"
                )
            return True
        except subprocess.TimeoutExpired:
            raise AudioRouterError("Playback timed out after 120 seconds")
        except FileNotFoundError:
            raise AudioRouterError(
                "pw-play not found. Is pipewire-bin installed?"
            )
        finally:
            self._cleanup_file(tmp_path)

    def play_wav_async(self, wav_data):
        """Play WAV audio asynchronously. Returns immediately.

        Args:
            wav_data: bytes of a WAV file.

        Returns:
            tuple of (Popen, temp_path) — caller can .wait() on the Popen
            and should eventually clean up the temp file.
        """
        tmp_path = self._write_temp_wav(wav_data)

        proc = subprocess.Popen(
            ["pw-play", "--target", self.sink_name, tmp_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return proc, tmp_path

    def _write_temp_wav(self, data):
        """Write audio bytes to a temp file. Returns the path.

        Detects format from header bytes to use the right extension
        so pw-play can identify the codec correctly.
        """
        # Detect format
        if data[:4] == b"RIFF":
            suffix = ".wav"
        elif data[:3] == b"ID3" or data[:2] == b"\xff\xfb" or data[:2] == b"\xff\xf3":
            suffix = ".mp3"
        else:
            suffix = ".wav"  # default

        fd, tmp_path = tempfile.mkstemp(
            suffix=suffix, prefix="yukkuri_"
        )
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        self._temp_files.append(tmp_path)
        return tmp_path

    def _cleanup_file(self, path):
        """Remove a temp WAV file."""
        try:
            if os.path.exists(path):
                os.unlink(path)
            if path in self._temp_files:
                self._temp_files.remove(path)
        except OSError:
            pass

    def cleanup(self):
        """Remove all temporary WAV files."""
        for path in list(self._temp_files):
            self._cleanup_file(path)

    def __del__(self):
        self.cleanup()
