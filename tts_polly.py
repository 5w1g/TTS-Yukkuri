"""Amazon Polly TTS client — the real Ivona Brian voice.

Amazon acquired Ivona in 2013 and its voices (Brian, Joey, Amy, Emma, etc.)
are available exclusively through Polly.  This is NOT the Microsoft "Brian"
— this is the one Twitch streamers actually use.

Credentials are read from the standard AWS credential chain, never from
the project config.  Use ONE of:

  1. ``~/.aws/credentials``::

        [default]
        aws_access_key_id = AKIA...
        aws_secret_access_key = ...

  2. Environment variables: ``AWS_ACCESS_KEY_ID`` + ``AWS_SECRET_ACCESS_KEY``

"""


import threading
from typing import Optional
from xml.sax.saxutils import escape as _xml_escape

import boto3
from botocore.exceptions import BotoCoreError, ClientError





# ---------------------------------------------------------------------------
# Quick-access voice map (short name → Polly VoiceId)
# ---------------------------------------------------------------------------

POPULAR_VOICES: dict[str, str] = {
    # ── Standard (Ivona-era) voices ──────────────────────────────────
    "brian":       "Brian",        # ♂ en-GB — THE real Ivona Brian
    "joey":        "Joey",         # ♂ en-US — Ivona Joey (also on Twitch)
    "amy":         "Amy",          # ♀ en-GB — Ivona Amy
    "emma":        "Emma",         # ♀ en-GB — Ivona Emma
    "salli":       "Salli",        # ♀ en-US — Ivona Salli
    "kendra":      "Kendra",       # ♀ en-US — Ivona Kendra
    "kimberly":    "Kimberly",     # ♀ en-US — Ivona Kimberly
    "justin":      "Justin",       # ♂ en-US — Ivona Justin (child voice)
    "ivy":         "Ivy",          # ♀ en-US — Ivona Ivy (child voice)
    # ── Neural voices (higher quality, more natural) ─────────────────
    "ruth":        "Ruth",         # ♀ en-US Neural
    "matthew":     "Matthew",      # ♂ en-US Neural
    "joanna":      "Joanna",       # ♀ en-US Neural
    "stephen":     "Stephen",      # ♂ en-US Neural
    "danielle":    "Danielle",     # ♀ en-US Neural
    "gregory":     "Gregory",      # ♂ en-US Neural
    "kevin":       "Kevin",        # ♂ en-US Neural (child)
    # ── UK / AU neural voices ────────────────────────────────────────
    "ruth-uk":     "Ruth",         # ♀ en-GB Neural (different from US Ruth)
    "arthur":      "Arthur",       # ♂ en-GB Neural
    "olivia":      "Olivia",       # ♀ en-AU Neural
}


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class PollyError(Exception):
    """Base for all Polly errors."""
    pass


class PollyAuthError(PollyError):
    """Credentials are missing or invalid."""
    pass


class PollySynthesisError(PollyError):
    """Synthesis request failed."""
    pass


class PollyEngine:
    """Amazon Polly synthesis client.

    Usage::

        engine = PollyEngine(region_name="us-east-1")
        audio = engine.synthesize("Hello from the real Brian!")
        router.play_wav(audio)

    Args:
        region_name: AWS region (default ``us-east-1``).
        profile_name: Named AWS config profile (default ``None`` → default).
    """

    def __init__(
        self,
        region_name: str = "us-east-1",
        profile_name: Optional[str] = None,
    ):
        self._region = region_name
        self._profile = profile_name
        self._client = None
        self._client_lock = threading.Lock()

    # -- client (lazy init) ------------------------------------------------

    @property
    def client(self):
        """Boto3 Polly client (created on first access, thread-safe)."""
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    try:
                        session = boto3.Session(
                            region_name=self._region,
                            profile_name=self._profile,
                        )
                        self._client = session.client("polly")
                    except (BotoCoreError, ClientError) as exc:
                        raise PollyAuthError(
                            f"Failed to create Polly client: {exc}\n"
                            f"Make sure your AWS credentials are configured.\n"
                            f"See: https://docs.aws.amazon.com/cli/latest/"
                            f"userguide/cli-configure-files.html"
                        ) from exc
        return self._client

    # -- voice listing -----------------------------------------------------

    def list_voices(self, engine: Optional[str] = None) -> list[dict]:
        """Return all available voices.

        Args:
            engine: Filter by engine (``"standard"``, ``"neural"``,
                    ``"generative"``, ``"long-form"``).  ``None`` returns all.

        Returns:
            List of voice dicts with keys: ``Id``, ``Name``, ``Gender``,
            ``LanguageName``, ``LanguageCode``, ``SupportedEngines``.
        """
        try:
            kwargs = {}
            if engine:
                kwargs["Engine"] = engine
            all_voices = []
            while True:
                result = self.client.describe_voices(**kwargs)
                all_voices.extend(result.get("Voices", []))
                next_token = result.get("NextToken")
                if not next_token:
                    break
                kwargs["NextToken"] = next_token
            return all_voices
        except (BotoCoreError, ClientError) as exc:
            raise PollyError(f"Failed to list voices: {exc}") from exc

    # -- synthesis ---------------------------------------------------------

    def synthesize(
        self,
        text: str,
        voice: str = "Brian",
        engine: str = "standard",
        rate: str = "medium",
        volume: str = "medium",
        pitch: Optional[str] = None,
        output_format: str = "mp3",
        sample_rate: str = "24000",
        use_ssml: bool = False,
    ) -> bytes:
        """Synthesise speech and return audio bytes.

        Args:
            text: Text to speak (or SSML if *use_ssml* is True).
            voice: Polly VoiceId (e.g. ``"Brian"``, ``"Joanna"``).
            engine: ``"standard"``, ``"neural"``, ``"generative"``,
                    or ``"long-form"``.
            rate: Speaking rate — ``"x-slow"``, ``"slow"``, ``"medium"``,
                  ``"fast"``, ``"x-fast"``, or a percentage like ``"+10%"``.
            volume: Volume — ``"x-soft"``, ``"soft"``, ``"medium"``,
                    ``"loud"``, ``"x-loud"``, or a dB value like ``"+5dB"``.
            pitch: Pitch shift — percentage like ``"+10%"`` or semitones
                   like ``"+2st"``.  ``None`` means default pitch.
            output_format: ``"mp3"``, ``"ogg_vorbis"``, or ``"pcm"``.
            sample_rate: Sample rate for PCM output (ignored for mp3/ogg).
            use_ssml: If True, *text* is treated as SSML (no wrapping).

        Returns:
            Audio bytes (MP3 by default — ``pw-play`` handles it natively).

        Raises:
            PollySynthesisError: Synthesis failed.
            PollyAuthError: Credentials are invalid or missing.
        """
        # Validate input
        if not text or not text.strip():
            raise PollySynthesisError("Cannot synthesise empty text")

        # Determine whether we need SSML for prosody control
        has_prosody = (
            rate != "medium" or volume != "medium" or pitch is not None
        )
        should_use_ssml = use_ssml or has_prosody

        try:
            if should_use_ssml and not use_ssml:
                # Wrap plain text in SSML with <prosody> tag
                escaped_text = _xml_escape(text, {'"': "&quot;"})
                prosody_attrs = f'rate="{rate}"'
                if volume != "medium":
                    prosody_attrs += f' volume="{volume}"'
                if pitch is not None:
                    prosody_attrs += f' pitch="{pitch}"'
                text = (
                    f'<speak><prosody {prosody_attrs}>'
                    f'{escaped_text}'
                    f'</prosody></speak>'
                )
                use_ssml = True

            kwargs: dict = {
                "Engine": engine,
                "OutputFormat": output_format,
                "Text": text,
                "TextType": "ssml" if use_ssml else "text",
                "VoiceId": voice,
            }
            if output_format == "pcm":
                kwargs["SampleRate"] = sample_rate

            response = self.client.synthesize_speech(**kwargs)

            # read() can raise I/O errors on streaming body
            try:
                audio_stream = response["AudioStream"]
                audio: bytes = audio_stream.read()
            except (OSError, ConnectionError, TimeoutError) as exc:
                raise PollySynthesisError(
                    f"Failed to read audio stream: {exc}"
                ) from exc
            except KeyError:
                raise PollySynthesisError(
                    "Polly response missing AudioStream — unexpected API format"
                )
            except AttributeError as exc:
                raise PollySynthesisError(
                    f"AudioStream object malformed: {exc}"
                ) from exc

            # If Polly returned a fault (e.g. invalid voice), the "audio"
            # is actually XML. boto3 doesn't raise on its own for this.
            # Strip BOM and leading whitespace before checking.
            stripped = audio.lstrip(b"\xef\xbb\xbf").lstrip()
            if stripped.startswith(b"<?xml") or stripped.startswith(b"<ErrorResponse"):
                # Decode the full XML (error responses are never large)
                try:
                    err_text = audio.decode("utf-8", errors="replace")
                except Exception:
                    err_text = repr(audio[:500])
                raise PollySynthesisError(
                    f"Polly returned an error: {err_text[:500]}"
                )

            # Sanity check: non-empty audio
            if len(audio) == 0:
                raise PollySynthesisError(
                    "Polly returned zero-length audio"
                )

            return audio

        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            msg = exc.response["Error"]["Message"]
            if code in ("UnrecognizedClientException", "InvalidClientTokenId",
                        "ExpiredToken", "AccessDeniedException",
                        "AccessDenied"):
                raise PollyAuthError(
                    f"AWS auth failed ({code}): {msg}\n"
                    f"Check your credentials in ~/.aws/credentials or "
                    f"the AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY env vars."
                ) from exc
            raise PollySynthesisError(
                f"Polly synthesis failed ({code}): {msg}"
            ) from exc
        except BotoCoreError as exc:
            raise PollyError(f"Polly request failed: {exc}") from exc

# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    engine = PollyEngine()
    try:
        voices = engine.list_voices()
        print(f"Available voices: {len(voices)}")
        en_voices = [v for v in voices if v["LanguageCode"].startswith("en-")]
        for v in en_voices:
            engines = ", ".join(v.get("SupportedEngines", ["?"]))
            print(f"  {v['Id']:20s}  {v['Gender']:6s}  "
                  f"{v['LanguageCode']:6s}  [{engines}]")

        if len(sys.argv) > 1:
            text = " ".join(sys.argv[1:])
        else:
            text = "Hello, this is Brian from Amazon Polly, the real Ivona voice."

        print(f"\nSynthesising: \"{text}\"")
        audio = engine.synthesize(text)
        print(f"Got {len(audio)} bytes of MP3 audio.")

        # Write to file for testing
        with open("/tmp/polly_test.mp3", "wb") as f:
            f.write(audio)
        print("Wrote /tmp/polly_test.mp3 — play with: pw-play /tmp/polly_test.mp3")

    except PollyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
