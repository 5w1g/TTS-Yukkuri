"""VOICEVOX TTS Engine client.

Talks to a local VOICEVOX engine over its HTTP API.
VOICEVOX runs on http://127.0.0.1:50021 by default.

API flow:
  POST /audio_query?text=...&speaker=N  -> returns accent/phrasing JSON
  POST /synthesis?speaker=N             -> returns WAV audio (with query as body)
"""

import http.client
import json
import urllib.parse


class VoicevoxError(Exception):
    """Base error for VOICEVOX communication failures."""
    pass


class EngineNotRunning(VoicevoxError):
    """VOICEVOX engine is not running or unreachable."""
    pass


class SynthesisError(VoicevoxError):
    """TTS synthesis failed (bad text, invalid speaker, etc.)."""
    pass


class VoicevoxEngine:
    """Client for the VOICEVOX TTS engine HTTP API.

    Usage:
        engine = VoicevoxEngine()
        if not engine.is_running():
            print("Start VOICEVOX first!")
            sys.exit(1)
        wav_bytes = engine.synthesize("こんにちは", speaker=1)
        # wav_bytes is a WAV file in memory (24000 Hz, 16-bit, mono PCM)
    """

    def __init__(self, host="127.0.0.1", port=50021, timeout=30):
        self.host = host
        self.port = port
        self.timeout = timeout

    @property
    def base_url(self):
        return f"http://{self.host}:{self.port}"

    def _request(self, method, path, body=None, headers=None):
        """Low-level HTTP request. Returns (body_bytes, content_type)."""
        conn = http.client.HTTPConnection(
            self.host, self.port, timeout=self.timeout
        )
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            data = response.read()

            if response.status == 422:
                # 422 = unprocessable entity (bad text, usually no Japanese chars)
                detail = data.decode("utf-8", errors="replace")[:300]
                raise SynthesisError(
                    f"VOICEVOX rejected the text (HTTP 422). "
                    f"Detail: {detail}"
                )
            elif response.status == 404:
                raise SynthesisError(
                    f"VOICEVOX endpoint not found (HTTP 404). "
                    f"Check engine version compatibility."
                )
            elif response.status == 500:
                raise SynthesisError(
                    f"VOICEVOX internal error (HTTP 500). "
                    f"The engine may need to be restarted."
                )
            elif response.status != 200:
                detail = data.decode("utf-8", errors="replace")[:300]
                raise SynthesisError(
                    f"VOICEVOX returned HTTP {response.status}: {detail}"
                )

            return data, response.getheader("Content-Type", "")
        except (ConnectionRefusedError, ConnectionResetError, OSError) as e:
            if isinstance(e, ConnectionRefusedError) or (
                isinstance(e, OSError) and "Connection refused" in str(e)
            ):
                raise EngineNotRunning(
                    f"VOICEVOX engine is not running at {self.base_url}. "
                    f"Start it with: ~/voicevox/voicevox_engine-linux-cpu-x64/run"
                )
            raise VoicevoxError(f"Cannot reach VOICEVOX: {e}")
        except http.client.HTTPException as e:
            raise VoicevoxError(f"HTTP protocol error: {e}")
        finally:
            conn.close()

    def is_running(self):
        """Check if the VOICEVOX engine is reachable and responding."""
        try:
            self._request("GET", "/version")
            return True
        except (VoicevoxError, OSError):
            return False

    def get_version(self):
        """Get the VOICEVOX engine version string."""
        data, _ = self._request("GET", "/version")
        version = json.loads(data)
        # /version returns a bare string like "0.25.2", not an object
        if isinstance(version, str):
            return version
        return version.get("version", "unknown")

    def get_speakers(self):
        """Get list of available speakers and their styles.

        Returns:
            list of dicts with keys: name, speaker_uuid, styles
        """
        data, _ = self._request("GET", "/speakers")
        return json.loads(data)

    def synthesize(self, text, speaker=1, speed_scale=1.0,
                   pitch_scale=1.0, intonation_scale=1.0):
        """Convert text to WAV audio bytes.

        Args:
            text: Japanese (or any) text to synthesize.
            speaker: Speaker/style ID (default 1 = Zundamon normal).
            speed_scale: Speech speed (1.0 = normal, <1 = slower).
            pitch_scale: Pitch adjustment (1.0 = normal).
            intonation_scale: Intonation strength (1.0 = normal).

        Returns:
            bytes containing a WAV file (24000 Hz, 16-bit, mono PCM).

        Raises:
            EngineNotRunning: VOICEVOX is not reachable.
            SynthesisError: TTS processing failed.
        """
        # Step 1: Build the audio query (accent/phrasing)
        encoded_text = urllib.parse.quote(text)
        query_data, _ = self._request(
            "POST",
            f"/audio_query?text={encoded_text}&speaker={speaker}",
        )
        query = json.loads(query_data)

        # Apply voice modulation settings
        if speed_scale != 1.0:
            query["speedScale"] = speed_scale
        if pitch_scale != 1.0:
            query["pitchScale"] = pitch_scale
        if intonation_scale != 1.0:
            query["intonationScale"] = intonation_scale

        # Step 2: Synthesize audio from the query
        wav_data, _ = self._request(
            "POST",
            f"/synthesis?speaker={speaker}",
            body=json.dumps(query),
            headers={"Content-Type": "application/json"},
        )

        return wav_data

    def synthesize_mora(self, text, speaker=1):
        """Synthesize and return mora timing info alongside audio.

        Returns:
            tuple of (wav_bytes, mora_list) where mora_list has
            timing information for lip-sync / visual feedback.
        """
        encoded_text = urllib.parse.quote(text)
        query_data, _ = self._request(
            "POST",
            f"/audio_query?text={encoded_text}&speaker={speaker}",
        )
        query = json.loads(query_data)

        # Get mora data from the query (returned alongside audio query)
        mora_data = []
        for phrase in query.get("accent_phrases", []):
            for mora in phrase.get("moras", []):
                mora_data.append({
                    "text": mora.get("text", ""),
                    "consonant_length": mora.get("consonant_length", 0),
                    "vowel_length": mora.get("vowel_length", 0),
                    "pitch": mora.get("pitch", 0),
                })

        wav_data, _ = self._request(
            "POST",
            f"/synthesis?speaker={speaker}",
            body=json.dumps(query),
            headers={"Content-Type": "application/json"},
        )

        return wav_data, mora_data
