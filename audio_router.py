"""Audio routing via PipeWire virtual sink.

Manages the virtual audio sink and plays WAV audio into it so that
the sink's monitor output can be captured by Discord as a microphone.
"""

import json
import os
import struct
import subprocess
import sys
import tempfile
import threading
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
        self._temp_lock = threading.Lock()

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
        self._boost_source_volume()
        return True

    def _boost_source_volume(self):
        """Boost the virtual microphone source volume so TTS audio is
        comparable to a real microphone level in Discord.

        TTS engines produce audio at typical media-playback levels (~-23 LUFS),
        which is much quieter than a microphone signal.  Boosting the source
        volume compensates so the other person in voice chat hears TTS at a
        normal speaking volume without needing to crank their Discord input.
        """
        source_name = self.sink_name.replace("_sink", "_source")
        try:
            result = subprocess.run(
                ["pactl", "set-source-volume", source_name, "300%"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                print(f"Warning: Failed to boost {source_name} volume: "
                      f"{result.stderr.strip()}", file=sys.stderr)
        except FileNotFoundError:
            print("Warning: pactl not found — source volume boost skipped.",
                  file=sys.stderr)
        except (subprocess.TimeoutExpired, OSError) as e:
            print(f"Warning: Could not boost {source_name} volume: {e}",
                  file=sys.stderr)

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
                    capture_output=True, timeout=5, check=False,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError,
                    OSError):
                pass

        for out_port, in_port in links_needed:
            # Check if link already exists
            link_exists = False
            try:
                result = subprocess.run(
                    ["pw-link", "-l"], capture_output=True,
                    text=True, timeout=5,
                )
                if result.returncode == 0:
                    link_exists = f"{out_port}\n  |-> {in_port}" in result.stdout
            except (subprocess.TimeoutExpired, FileNotFoundError,
                    OSError):
                pass

            if link_exists:
                continue

            # Create the link
            try:
                result = subprocess.run(
                    ["pw-link", out_port, in_port],
                    capture_output=True, timeout=5, check=False,
                )
                if result.returncode != 0:
                    # Non-fatal — link may already exist or ports may not be ready
                    pass
            except (subprocess.TimeoutExpired, FileNotFoundError,
                    OSError):
                pass

    def _sink_exists(self):
        """Check if the sink node exists in PipeWire."""
        try:
            result = subprocess.run(
                ["pw-dump"],
                capture_output=True, text=True, timeout=10,
            )
            try:
                nodes = json.loads(result.stdout)
                for node in nodes:
                    props = node.get("info", {}).get("props", {})
                    if props.get("node.name") == self.sink_name:
                        return True
                return False
            except (json.JSONDecodeError, KeyError, TypeError):
                # Fall back to simple string match
                return f'"node.name": "{self.sink_name}"' in result.stdout
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

    def play_wav(self, wav_data, volume=1.0):
        """Play WAV audio through the virtual sink. Blocks until complete.

        Args:
            wav_data: bytes of a WAV file (or MP3/Ogg).
            volume: Output gain (0.0+). 1.0 = normal, 2.0 = 2× amplification.
                    Passed directly to pw-play --volume, which applies gain
                    in PipeWire for all formats uniformly.

        Returns:
            True on success.

        Raises:
            AudioRouterError: Playback failed.
        """
        # Re-apply source volume boost before each playback (PipeWire may
        # reset it on state transitions — this keeps it pinned at 300%).
        self._boost_source_volume()

        tmp_path = self._write_temp_wav(wav_data)

        try:
            result = subprocess.run(
                ["pw-play", "--target", self.sink_name,
                 "--volume", str(volume), tmp_path],
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

    def play_wav_async(self, wav_data, volume=1.0):
        """Play WAV audio asynchronously. Returns immediately.

        Args:
            wav_data: bytes of a WAV file (or MP3/Ogg).
            volume: Output gain (0.0+). 1.0 = normal, 2.0 = 2× amplification.

        Returns:
            tuple of (Popen, temp_path) — caller can .wait() on the Popen
            to check the exit code and read stderr from proc.stderr.
            Caller should eventually clean up the temp file.
        """
        self._boost_source_volume()

        tmp_path = self._write_temp_wav(wav_data)

        proc = subprocess.Popen(
            ["pw-play", "--target", self.sink_name,
             "--volume", str(volume), tmp_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
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
        elif data[:3] == b"ID3":
            # ID3-tagged MP3
            suffix = ".mp3"
        elif data[:4] == b"OggS":
            # Ogg Vorbis/Opus container
            suffix = ".ogg"
        elif len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
            # Raw MPEG audio frame sync (0xFFE0-0xFFF7)
            suffix = ".mp3"
        else:
            suffix = ".wav"  # default

        fd, tmp_path = tempfile.mkstemp(
            suffix=suffix, prefix="yukkuri_"
        )
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        with self._temp_lock:
            self._temp_files.append(tmp_path)
        return tmp_path

    def _cleanup_file(self, path):
        """Remove a temp WAV file."""
        try:
            if os.path.exists(path):
                os.unlink(path)
        except OSError:
            pass
        with self._temp_lock:
            try:
                self._temp_files.remove(path)
            except ValueError:
                pass

    def cleanup(self):
        """Remove all temporary WAV files."""
        with self._temp_lock:
            paths = list(self._temp_files)
        for path in paths:
            self._cleanup_file(path)

    @staticmethod
    def _apply_gain(data, gain):
        """Apply linear gain to audio samples.  Returns modified bytes.

        For WAV (RIFF) data, directly scales 16-bit or 32-bit PCM samples.
        For MP3/Ogg (compressed) data, returns unchanged — gain is applied
        via pw-play --volume instead.
        """
        if data[:4] != b"RIFF":
            return data  # MP3/Ogg — can't modify compressed samples safely

        # Parse minimal RIFF/WAV header to find the data chunk
        if len(data) < 44:
            return data

        # "fmt " chunk: 16 or 18 or 40 bytes of format info
        fmt_size = struct.unpack_from("<I", data, 16)[0]
        bits_per_sample = struct.unpack_from("<H", data, 34)[0]
        bytes_per_sample = bits_per_sample // 8
        num_channels = struct.unpack_from("<H", data, 22)[0]

        if bits_per_sample not in (16, 32):
            return data  # float or 8-bit — don't touch

        # Find "data" chunk (starts after 12 + 8 + fmt_size bytes from "fmt " offset)
        fmt_offset = 12  # "fmt " is at byte 12 in RIFF
        data_offset = fmt_offset + 8 + fmt_size  # after "fmt " + size + chunk

        # "data" may not immediately follow "fmt " — scan for it
        pos = data_offset
        while pos + 8 <= len(data):
            chunk_id = data[pos:pos + 4]
            chunk_size = struct.unpack_from("<I", data, pos + 4)[0]
            if chunk_id == b"data":
                samples_start = pos + 8
                samples_end = samples_start + chunk_size
                samples_end = min(samples_end, len(data))

                # Modify in-place: build new bytes
                raw = bytearray(data[samples_start:samples_end])

                if bits_per_sample == 16:
                    fmt_char = "h"
                else:
                    fmt_char = "i"

                frame_size = num_channels * bytes_per_sample
                n_frames = len(raw) // frame_size

                for i in range(n_frames):
                    for ch in range(num_channels):
                        offset = i * frame_size + ch * bytes_per_sample
                        sample = struct.unpack_from(f"<{fmt_char}", raw, offset)[0]
                        sample = int(sample * gain)
                        # Clamp to 16/32-bit range
                        if bits_per_sample == 16:
                            sample = max(-32768, min(32767, sample))
                        else:
                            sample = max(-2147483648, min(2147483647, sample))
                        struct.pack_into(f"<{fmt_char}", raw, offset, sample)

                # Reassemble the file
                result = bytearray(data[:samples_start]) + raw + bytearray(data[samples_end:])
                # Update data chunk size if needed
                return bytes(result)

            pos += 8 + chunk_size
            if pos >= len(data):
                break

        return data  # No "data" chunk found — return unchanged

    def __del__(self):
        self.cleanup()
