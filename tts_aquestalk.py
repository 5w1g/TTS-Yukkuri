"""AquesTalk10 TTS engine — the authentic Yukkuri voice.

AquesTalk10 is the commercial speech synthesis engine by AQUEST Corp that
produces the classic "Yukkuri" voice (ゆっくり) familiar from Nico Nico Douga
and YouTube.  This module wraps ``libAquesTalk10.so`` with Python ctypes —
no additional pip dependencies required.

**Evaluation version**: The free evaluation SDK adds a minor watermark
(na/ma-row kana pronounced as "nu").  A development license key from AQUEST
removes this restriction.

**Setup**:
    1. Download the Linux evaluation SDK from:
       https://www.a-quest.com/products/aquestalk10.html
    2. Extract ``libAquesTalk10.so`` to ``~/TTS/aquestalk/`` or ``/usr/local/lib/``
    3. Optionally set ``AQUESTALK_LIB`` env var to the full .so path

**Input formats**: AquesTalk10 requires phonetic kana input.  This module
automatically converts several input forms to katakana:

* **English** — ``hello`` → ``ヘロー`` (requires e2k_)
* **Romaji** (Hepburn) — ``konnichiwa`` → ``コンニチワ`` (built-in, no deps)
* **Kanji + kana** — ``今日は`` → ``キョーワ`` (requires pyopenjtalk_)
* **Kana** — ``コンニチワ`` → ``コンニチワ`` (pass-through)

If ``pyopenjtalk`` or ``e2k`` are installed they will be used automatically.
Without them, just type romaji or kana directly.

.. _e2k: https://pypi.org/project/e2k/
.. _pyopenjtalk: https://pypi.org/project/pyopenjtalk/
"""

import ctypes
import ctypes.util
import os
import sys
import threading
from typing import Optional


# ---------------------------------------------------------------------------
# AquesTalk10 voice-parameter struct (AQTK_VOICE)
# ---------------------------------------------------------------------------

class AQTK_VOICE(ctypes.Structure):
    """Voice quality parameters for AquesTalk10.

    Fields match the C struct from AquesTalk.h::

        typedef struct _AQTK_PARAM_ {
            int bas;  // base phoneme  (0=F1E, 1=F2E, 2=M1E)
            int spd;  // speed         50–300  (default 100)
            int vol;  // volume        0–300   (default 100)
            int pit;  // pitch         20–200  (default voice-dependent)
            int acc;  // accent        0–200   (default voice-dependent)
            int lmd;  // tone mod 1    0–200   (default 100)
            int fsc;  // tone mod 2    50–200  (default 100)
        } AQTK_VOICE;
    """
    _fields_ = [
        ("bas", ctypes.c_int),   # base voice type: 0=F1E, 1=F2E, 2=M1E
        ("spd", ctypes.c_int),   # speed 50–300
        ("vol", ctypes.c_int),   # volume 0–300
        ("pit", ctypes.c_int),   # pitch 20–200
        ("acc", ctypes.c_int),   # accent 0–200
        ("lmd", ctypes.c_int),   # tone modulation 1  (0–200)
        ("fsc", ctypes.c_int),   # tone modulation 2  (50–200, affects sample rate)
    ]


# Base voice type enum (from AquesTalk.h)
_F1E = 0   # Female 1 — the classic Yukkuri voice
_F2E = 1   # Female 2
_M1E = 2   # Male 1


# ---------------------------------------------------------------------------
# Voice presets  (from AquesTalk.h — gVoice_* constants)
# ---------------------------------------------------------------------------

VOICE_PRESETS: dict[str, AQTK_VOICE] = {
    # bas                 spd  vol  pit  acc  lmd  fsc
    "f1": AQTK_VOICE(_F1E, 100, 100, 100, 100, 100, 100),  # Female 1 (classic Yukkuri)
    "f2": AQTK_VOICE(_F2E, 100, 100,  77, 150, 100, 100),  # Female 2
    "f3": AQTK_VOICE(_F1E,  80, 100, 100, 100,  61, 148),  # Female 3
    "m1": AQTK_VOICE(_M1E, 100, 100,  30, 100, 100, 100),  # Male 1
    "m2": AQTK_VOICE(_M1E, 105, 100,  45, 130, 120, 100),  # Male 2
    "r1": AQTK_VOICE(_M1E, 100, 100,  30,  20, 190, 100),  # Robot 1
    "r2": AQTK_VOICE(_F2E,  70, 100,  50,  50,  50, 180),  # Robot 2
}

VOICE_PRESET_LABELS: dict[str, str] = {
    "f1": "Female 1  (classic Yukkuri / Reimu)",
    "f2": "Female 2  (Marisa-type)",
    "f3": "Female 3  (soft / high)",
    "m1": "Male 1",
    "m2": "Male 2",
    "r1": "Robot 1",
    "r2": "Robot 2",
}


# ---------------------------------------------------------------------------
# Quick-access voice map  (for CLI /voice and GUI dropdown)
# ---------------------------------------------------------------------------

POPULAR_VOICES: dict[str, str] = {
    "f1":      "f1",       # Classic Yukkuri ♀
    "f2":      "f2",       # Female 2
    "f3":      "f3",       # Female 3
    "m1":      "m1",       # Male 1
    "m2":      "m2",       # Male 2
    "r1":      "r1",       # Robot 1
    "r2":      "r2",       # Robot 2
}

DEFAULT_VOICE = "f1"

# AquesTalk10 error codes (negative integers returned as wave_size)
# Source: AquesTalk10 SDK documentation
_AQUESTALK_ERRORS: dict[int, str] = {
    -1: "Unknown error — synthesis failed for an unspecified reason",
    -2: "Invalid parameter — speed or voice value out of range",
    -3: "Memory allocation failed — text may be too long",
    -4: "Text too long (max ~1000 characters)",
    -5: ("Phonetic conversion failed — input must be valid kana text"
         " (install pyopenjtalk for automatic kanji→kana conversion)"),
    -6: "Internal engine error — unexpected state",
    -7: "SSML parse error — check SSML syntax",
}


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class AquesTalkError(Exception):
    """Base for all AquesTalk10 errors."""
    pass


class LibraryNotFound(AquesTalkError):
    """The AquesTalk10 shared library could not be found."""
    pass


class SynthesisError(AquesTalkError):
    """Synthesis request failed."""
    pass


# ---------------------------------------------------------------------------
# Text-to-Kana conversion
# ---------------------------------------------------------------------------
# AquesTalk10 requires phonetic kana input.  This pipeline converts several
# input forms to katakana:
#
#   1. pyopenjtalk (if installed) — handles kanji + kana mixed text
#   2. Built-in romaji→katakana  — Hepburn romanisation for ASCII input
#   3. e2k (if installed)        — English→katakana for non-romaji ASCII
#   4. Pass-through               — text that is already kana
#
# Users can type:
#   - Romaji:    "konnichiwa"        → コンニチワ
#   - English:   "hello"             → ヘロー     (via e2k)
#   - Kanji:     "今日は"             → キョーワ  (via pyopenjtalk)
#   - Kana:      "コンニチワ"         → コンニチワ  (pass-through)
#   - Mixed:     "私はgenkiです"      → ワタシハゲンキデス  (via pyopenjtalk)

import re


# ---------------------------------------------------------------------------
# Romaji → Katakana  (Hepburn romanisation, stdlib-only)
# ---------------------------------------------------------------------------

# Regex alternation ordered longest-first for greedy matching.
# Entries grouped by length so the compiled pattern is deterministic.
_ROMAJI_MAP: dict[str, str] = {
    # -- digraphs (youon), 3 chars --
    "kya": "キャ", "kyu": "キュ", "kyo": "キョ",
    "sha": "シャ", "shu": "シュ", "sho": "ショ",
    "cha": "チャ", "chu": "チュ", "cho": "チョ",
    "nya": "ニャ", "nyu": "ニュ", "nyo": "ニョ",
    "hya": "ヒャ", "hyu": "ヒュ", "hyo": "ヒョ",
    "mya": "ミャ", "myu": "ミュ", "myo": "ミョ",
    "rya": "リャ", "ryu": "リュ", "ryo": "リョ",
    "gya": "ギャ", "gyu": "ギュ", "gyo": "ギョ",
    "bya": "ビャ", "byu": "ビュ", "byo": "ビョ",
    "pya": "ピャ", "pyu": "ピュ", "pyo": "ピョ",
    # -- 3-char specials --
    "tsu": "ツ", "shi": "シ", "chi": "チ",
    # -- 2-char digraphs --
    "ja": "ジャ", "ju": "ジュ", "jo": "ジョ",
    # -- 2-char mora (basic + voiced + semi-voiced) --
    "ka": "カ", "ki": "キ", "ku": "ク", "ke": "ケ", "ko": "コ",
    "sa": "サ",              "su": "ス", "se": "セ", "so": "ソ",
    "ta": "タ",              "te": "テ", "to": "ト",
    "na": "ナ", "ni": "ニ", "nu": "ヌ", "ne": "ネ", "no": "ノ",
    "ha": "ハ", "hi": "ヒ", "fu": "フ", "he": "ヘ", "ho": "ホ",
    "ma": "マ", "mi": "ミ", "mu": "ム", "me": "メ", "mo": "モ",
    "ya": "ヤ",              "yu": "ユ",              "yo": "ヨ",
    "ra": "ラ", "ri": "リ", "ru": "ル", "re": "レ", "ro": "ロ",
    "wa": "ワ", "wo": "ヲ",
    "ga": "ガ", "gi": "ギ", "gu": "グ", "ge": "ゲ", "go": "ゴ",
    "za": "ザ", "ji": "ジ", "zu": "ズ", "ze": "ゼ", "zo": "ゾ",
    "da": "ダ", "di": "ヂ", "du": "ヅ", "de": "デ", "do": "ド",
    "ba": "バ", "bi": "ビ", "bu": "ブ", "be": "ベ", "bo": "ボ",
    "pa": "パ", "pi": "ピ", "pu": "プ", "pe": "ペ", "po": "ポ",
    # -- vowels, 1 char --
    "a": "ア", "i": "イ", "u": "ウ", "e": "エ", "o": "オ",
}

# Build pattern: longest keys first, then syllabic-n, then any single char.
_ROMAJI_RE = re.compile(
    "|".join(re.escape(k) for k in sorted(_ROMAJI_MAP, key=len, reverse=True))
    + r"|n(?![aeiouy])"
    + r"|."
)


def _romaji_to_katakana(text: str) -> str:
    """Convert Hepburn romaji to katakana.

    Handles:
    - Basic gojuon (ka, ki, ku, …)
    - Voiced / semi-voiced (ga, za, ba, pa, …)
    - Digraphs (kya, sha, cha, …)
    - Syllabic n (ン) before consonants or word-final
    - Geminate consonant (kk, ss, tt, … → ッ)

    Non-romaji characters (punctuation, numbers, unknown letters) are
    passed through unchanged so they survive into the AquesTalk input.
    """
    # Pre-process: doubled consonants → small-tsu marker
    # "kka" → "ッka", "ssa" → "ッsa", "tto" → "ッto", etc.
    # Note: "n" is excluded — "nn" before a vowel is syllabic ン + na/ni/…
    # (e.g. konnichiwa → コンニチワ), not geminate ッニ (which never occurs).
    text = re.sub(r"([bcdfghjklmpqrstvwxyz])\1", r"ッ\1", text.lower().strip())

    def _replace(m: re.Match[str]) -> str:
        token = m.group(0)
        if token == "n":
            return "ン"  # syllabic n
        return _ROMAJI_MAP.get(token, token)

    return _ROMAJI_RE.sub(_replace, text)


def _english_to_katakana(text: str) -> Optional[str]:
    """Convert English text to katakana using the e2k library.

    Returns katakana string on success, ``None`` if e2k is not installed
    or conversion fails.
    """
    try:
        from e2k import C2K  # type: ignore[import-untyped]
    except ImportError:
        return None

    try:
        c2k = C2K()
        result = c2k(text.strip())
        if result and result != text.strip():
            return result
    except Exception:
        pass
    return None


# Regex for detecting non-katakana characters in converted output.
# Katakana block U+30A0–U+30FF, plus some punctuation that's safe.
_NON_KATAKANA_RE = re.compile(r"[^ァ-ヴーッ 　]")


def _is_valid_kana(text: str) -> bool:
    """Return True if *text* contains only katakana (and spaces)."""
    return not _NON_KATAKANA_RE.search(text)


def _text_to_kana(text: str) -> tuple[str, bool]:
    """Convert arbitrary Japanese text to phonetic katakana.

    Routes input through the appropriate converter:

    1. Text containing kanji/kana → pyopenjtalk (best quality)
    2. ASCII / romaji text → built-in Hepburn→katakana converter
    3. Everything else → pass-through

    Returns ``(converted_text, used_converter)`` where *used_converter* is
    ``True`` when a converter was applied (so the caller can suppress
    redundant "install pyopenjtalk" hints).
    """
    # Detect Japanese characters in the input
    has_japanese = any(
        "぀" <= c <= "ゟ"   # Hiragana
        or "゠" <= c <= "ヿ"  # Katakana
        or "一" <= c <= "鿿"  # Kanji (CJK Unified Ideographs)
        for c in text
    )

    if has_japanese:
        # Strategy 1: pyopenjtalk handles kanji + kana → phonetic kana
        try:
            import pyopenjtalk  # type: ignore[import-untyped]

            result = pyopenjtalk.g2p(text, kana=True)
            cleaned = result.replace(" ", "").replace("　", "")
            if cleaned:
                return cleaned, True
        except ImportError:
            pass
        except Exception:
            pass  # pyopenjtalk may raise RuntimeError, ValueError on bad input

    # Strategy 2: ASCII text → romaji first, then English→katakana
    if all(c.isascii() or c.isspace() for c in text):
        romaji_result = _romaji_to_katakana(text)
        if _is_valid_kana(romaji_result):
            return romaji_result, True

        # Romaji converter left ASCII chars — probably English, try e2k
        english_result = _english_to_katakana(text)
        if english_result and _is_valid_kana(english_result):
            return english_result, True

        # If we got something usable from romaji (even slightly broken),
        # return it — AquesTalk might still pronounce it
        if romaji_result != text.strip():
            return romaji_result, True

    # Strategy 3: pass-through (already kana, or couldn't convert)
    return text, False


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class AquesTalkEngine:
    """AquesTalk10 synthesis client.

    Usage::

        engine = AquesTalkEngine()
        if engine.is_available():
            wav = engine.synthesize("コンニチワ", voice="f1", speed=0.7)
            router.play_wav(wav)

    Args:
        lib_path: Path to ``libAquesTalk10.so``.  If ``None``, the library
                  is discovered automatically (see module docstring).
    """

    # Known search paths for libAquesTalk10.so
    _SEARCH_PATHS = [
        "/usr/local/lib/libAquesTalk10.so",
        os.path.expanduser("~/TTS/aquestalk/libAquesTalk10.so"),
        "/usr/lib/libAquesTalk10.so",
    ]

    def __init__(self, lib_path: Optional[str] = None):
        self._lib = None
        self._lib_lock = threading.Lock()

        if lib_path is not None:
            self._load_lib(lib_path)
        else:
            discovered = self._discover_library()
            if discovered:
                self._load_lib(discovered)

    # -- library discovery ---------------------------------------------------

    @staticmethod
    def _discover_library() -> Optional[str]:
        """Search for ``libAquesTalk10.so`` on the system.

        Priority order:
        1. ``AQUESTALK_LIB`` environment variable
        2. ``ctypes.util.find_library("AquesTalk10")``
        3. Well-known paths (see ``_SEARCH_PATHS``)
        """
        # 1. Environment variable
        env_path = os.environ.get("AQUESTALK_LIB", "").strip()
        if env_path and os.path.isfile(env_path):
            return env_path

        # 2. System library search
        system_lib = ctypes.util.find_library("AquesTalk10")
        if system_lib and os.path.isfile(system_lib):
            return system_lib

        # 3. Well-known paths
        for path in AquesTalkEngine._SEARCH_PATHS:
            if os.path.isfile(path):
                return path

        return None

    def _load_lib(self, path: str) -> None:
        """Load the shared library and set up ctypes function signatures."""
        if not os.path.isfile(path):
            raise LibraryNotFound(
                f"AquesTalk10 library not found at: {path}\n"
                f"Download the evaluation SDK from:\n"
                f"  https://www.a-quest.com/products/aquestalk10.html\n"
                f"Extract libAquesTalk10.so to ~/TTS/aquestalk/ or /usr/local/lib/"
            )

        try:
            # AquesTalk10 is a C++ library — preload libstdc++ with
            # RTLD_GLOBAL so symbols (__gxx_personality_v0) are visible.
            try:
                ctypes.CDLL("libstdc++.so.6", mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass

            lib = ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
        except OSError as exc:
            raise LibraryNotFound(
                f"Failed to load AquesTalk10 library from {path}: {exc}\n"
                f"Make sure the library matches your system architecture (x86_64)."
            ) from exc

        # Verify required symbols exist before setting up signatures
        try:
            _synthe = lib.AquesTalk_Synthe_Utf8
            _free = lib.AquesTalk_FreeWave
        except AttributeError as exc:
            raise LibraryNotFound(
                f"Library at {path} is missing required symbols "
                f"({exc}).  It may be a different version of AquesTalk."
            ) from exc

        # AquesTalk_Synthe_Utf8(const AQTK_VOICE *pParam, const char *koe,
        #                       int *pSize)
        #   → returns pointer to WAV PCM buffer (caller must free via
        #     AquesTalk_FreeWave)
        #   → pSize receives size in bytes, or negative error code on failure
        _synthe.argtypes = [
            ctypes.POINTER(AQTK_VOICE),   # voice params struct
            ctypes.c_char_p,              # kana text  (UTF-8, NUL-terminated)
            ctypes.POINTER(ctypes.c_int), # out: wave size / error code
        ]
        _synthe.restype = ctypes.POINTER(ctypes.c_ubyte)

        # AquesTalk_FreeWave(void* wav)
        _free.argtypes = [ctypes.POINTER(ctypes.c_ubyte)]
        _free.restype = None

        # Optional: AquesTalk_SetDevKey(const char* key)
        # Removes evaluation limitations.
        try:
            lib.AquesTalk_SetDevKey.argtypes = [ctypes.c_char_p]
            lib.AquesTalk_SetDevKey.restype = ctypes.c_int
        except AttributeError:
            pass  # not all builds expose SetDevKey

        self._lib = lib

    # -- health check --------------------------------------------------------

    def is_available(self) -> bool:
        """Return ``True`` if the AquesTalk10 library was loaded successfully."""
        return self._lib is not None

    # -- voice listing -------------------------------------------------------

    def list_voices(self) -> list[dict]:
        """Return available voice presets.

        Seven presets are available: F1 (classic Yukkuri female),
        F2/F3 (other female), M1/M2 (male), R1/R2 (robot).
        """
        return [
            {"id": vid, "name": VOICE_PRESET_LABELS.get(vid, vid)}
            for vid in VOICE_PRESETS
        ]

    # -- synthesis -----------------------------------------------------------

    def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
        pitch: Optional[float] = None,
        intonation: Optional[float] = None,
    ) -> bytes:
        """Synthesise speech and return WAV PCM audio bytes.

        Args:
            text: Japanese text to speak.  Should be phonetic kana
                  (e.g. コンニチワ).  If pyopenjtalk is installed, kanji
                  input is automatically converted to kana.
            voice: Voice preset ID — ``"f1"``, ``"f2"``, ``"f3"``, ``"m1"``,
                   ``"m2"``, ``"r1"``, ``"r2"``.  Defaults to ``"f1"``
                   (classic Yukkuri / Reimu).
            speed: Speaking speed multiplier (0.5–2.0, 1.0 = normal).
                   Mapped to AquesTalk's ``spd`` field (50–300).
                   ``None`` preserves the voice preset's native speed.
            pitch: Pitch multiplier (0.5–2.0, 1.0 = voice default).
                   Mapped to AquesTalk's ``pit`` field (20–200).
            intonation: Intonation / expressiveness multiplier
                        (0.0–2.0, 1.0 = voice default).
                        Mapped to AquesTalk's ``acc`` field (0–200).

        Returns:
            WAV PCM audio bytes (16 kHz, 16-bit, mono).

        Raises:
            LibraryNotFound: The .so was never loaded (is_available → False).
            SynthesisError: Synthesis failed (invalid text, engine error, etc.).
        """
        if self._lib is None:
            raise LibraryNotFound(
                "AquesTalk10 library not loaded.  "
                "Make sure libAquesTalk10.so is installed."
            )

        # Validate input
        if not text or not text.strip():
            raise SynthesisError("Cannot synthesise empty text")

        # Text → kana conversion (kanji, romaji, or pass-through)
        kana_text, used_converter = _text_to_kana(text.strip())
        if not kana_text or not kana_text.strip():
            raise SynthesisError(
                "Text converted to empty kana string.  "
                "Try typing kana directly (e.g. コンニチワ)."
            )

        # Resolve voice preset
        voice_id = voice or DEFAULT_VOICE
        if voice_id not in VOICE_PRESETS:
            raise SynthesisError(
                f"Unknown voice: {voice_id!r}.  "
                f"Valid presets: {', '.join(VOICE_PRESETS)}"
            )

        base = VOICE_PRESETS[voice_id]

        # Build the voice-param struct — copy the preset then override
        param = AQTK_VOICE()
        ctypes.memmove(ctypes.byref(param), ctypes.byref(base), ctypes.sizeof(AQTK_VOICE))

        # Map project speed (0.5–2.0) → AquesTalk spd (50–300)
        if speed is not None:
            param.spd = max(50, min(300, int(speed * 100)))

        # Map project pitch (0.5–2.0) → AquesTalk pit (20–200)
        if pitch is not None:
            param.pit = max(20, min(200, int(base.pit * pitch)))

        # Map intonation (0.0–2.0) → AquesTalk acc (0–200)
        if intonation is not None:
            param.acc = max(0, min(200, int(base.acc * intonation)))

        # Synthesise (thread-safe: guard C library access)
        text_bytes = kana_text.encode("utf-8")
        wave_size = ctypes.c_int()

        with self._lib_lock:
            wav_ptr = self._lib.AquesTalk_Synthe_Utf8(
                ctypes.byref(param),
                text_bytes,
                ctypes.byref(wave_size),
            )

            try:
                # Check for error (negative wave_size or NULL pointer).
                # ctypes wraps NULL C pointers in a non-None Python object
                # where bool(wav_ptr) is False — "is None" never catches NULL.
                if not wav_ptr or wave_size.value < 0:
                    err_code = wave_size.value if wave_size.value < 0 else -1
                    err_msg = _AQUESTALK_ERRORS.get(
                        err_code, f"Unknown error (code {err_code})"
                    )

                    # Add helpful hint for common errors
                    hint = ""
                    if err_code == -5 and not used_converter:
                        hint = (
                            "\n\nTip: AquesTalk10 needs phonetic kana input.\n"
                            "Type romaji (e.g. konnichiwa) or kana directly.\n"
                            "For best results, install pyopenjtalk:\n"
                            "  pip install --break-system-packages pyopenjtalk"
                        )
                    elif err_code == -2 and used_converter:
                        hint = (
                            "\n\nTip: The kana conversion may have produced "
                            "characters AquesTalk10 doesn't understand. "
                            "Try typing kana directly."
                        )
                    elif err_code == -4:
                        hint = (
                            "\n\nTip: Try breaking longer text into shorter "
                            "segments (max ~1000 chars)."
                        )

                    raise SynthesisError(err_msg + hint)

                if wave_size.value == 0:
                    raise SynthesisError(
                        "AquesTalk10 produced zero-length audio"
                    )

                # Validate minimum WAV header size
                if wave_size.value < 44:
                    raise SynthesisError(
                        f"AquesTalk10 returned {wave_size.value} bytes "
                        f"(expected at least 44 for a valid WAV header)"
                    )

                # Copy PCM data from C buffer before freeing
                try:
                    wav_data = bytes(
                        (ctypes.c_ubyte * wave_size.value).from_address(
                            ctypes.addressof(wav_ptr.contents)
                        )
                    )
                except (ValueError, MemoryError) as exc:
                    raise SynthesisError(
                        f"Failed to copy audio data from AquesTalk10 "
                        f"buffer: {exc}"
                    ) from exc

                return wav_data

            finally:
                # Always free the C buffer — even if we failed to copy
                if wav_ptr:
                    self._lib.AquesTalk_FreeWave(wav_ptr)


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    engine = AquesTalkEngine()

    if not engine.is_available():
        print("AquesTalk10 library not found.", file=sys.stderr)
        print("Download the evaluation SDK from:", file=sys.stderr)
        print("  https://www.a-quest.com/products/aquestalk10.html", file=sys.stderr)
        print(
            "Extract libAquesTalk10.so to ~/TTS/aquestalk/ or /usr/local/lib/",
            file=sys.stderr,
        )
        print(
            "Or set AQUESTALK_LIB=/path/to/libAquesTalk10.so",
            file=sys.stderr,
        )
        sys.exit(1)

    print("AquesTalk10 library loaded ✓")
    voices = engine.list_voices()
    print(f"Available voices: {len(voices)}")
    for v in voices:
        print(f"  {v['id']:6s}  {v['name']}")

    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
    else:
        text = "コンニチワ"

    print(f'\nSynthesising: "{text}" (voice=f1, speed=1.0)')
    try:
        audio = engine.synthesize(text)
        print(f"Got {len(audio)} bytes of WAV audio.")

        # Write to file for testing
        out_path = "/tmp/aquestalk_test.wav"
        with open(out_path, "wb") as f:
            f.write(audio)
        print(f"Wrote {out_path} — play with: pw-play {out_path}")

    except AquesTalkError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
