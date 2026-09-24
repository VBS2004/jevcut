"""Issue 002 -- transcript ingest and sentence model.

Jev is text-only, so the transcript IS the state and its quality is the ceiling on
everything downstream. Two things matter here: correct sentence boundaries (the unit Jev
addresses) and correct word timings (what makes a cut point real).

Sources, in order of preference:

1. A platform transcript aligned to Whisper word timings -- platform transcripts have the
   proper nouns right, Whisper has the timings right, so take both (``align_to_reference``).
2. Whisper alone.
3. A pre-computed word list (``from_word_json``), which is what the tests use and what
   makes the pipeline runnable with no ASR installed.
"""

from __future__ import annotations

import ctypes
import difflib
import json
import logging
import re
from pathlib import Path

from jevcut.config import Config
from jevcut.models import Sentence, Transcript, Word
from jevcut.render import id_width, sentence_id

log = logging.getLogger(__name__)

# Trailing quote/bracket allowed after the terminator: 'he said "stop."' ends a sentence.
_SENTENCE_END = re.compile(r"[.!?…][\"')\]]*$")
_TOKEN = re.compile(r"\S+")


def _ends_sentence(text: str) -> bool:
    return bool(_SENTENCE_END.search(text.strip()))


def segment_words(words: list[Word], config: Config | None = None) -> list[Sentence]:
    """Group words into sentences.

    A break happens on terminal punctuation, on silence >= ``sentence_gap_s``, or on a
    speaker change. Sentences longer than ``max_sentence_words`` are then split at their
    largest internal pause -- an 80-word "sentence" is a useless addressing unit, because
    a Choice that points at it hasn't narrowed anything down.
    """
    config = config or Config()
    if not words:
        return []

    groups: list[list[Word]] = []
    current: list[Word] = []

    for i, w in enumerate(words):
        current.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None:
            break
        if (
            _ends_sentence(w.text)
            or (nxt.t0 - w.t1) >= config.sentence_gap_s
            or (w.speaker is not None and nxt.speaker is not None and w.speaker != nxt.speaker)
        ):
            groups.append(current)
            current = []
    if current:
        groups.append(current)

    split: list[list[Word]] = []
    for g in groups:
        split.extend(_split_long(g, config.max_sentence_words))

    width = id_width(len(split))
    return [
        Sentence(
            id=sentence_id(i, width),
            text=" ".join(w.text for w in g).strip(),
            t0=g[0].t0,
            t1=g[-1].t1,
            words=list(g),
            speaker=g[0].speaker,
        )
        for i, g in enumerate(split)
    ]


def _split_long(group: list[Word], max_words: int) -> list[list[Word]]:
    """Split at the largest internal pause, recursively, until short enough."""
    if len(group) <= max(max_words, 2):
        return [group]

    best_i, best_gap = None, -1.0
    # Keep at least a quarter of max_words on each side so we don't shave off one word.
    margin = max(1, max_words // 4)
    for i in range(margin, len(group) - margin):
        gap = group[i + 1].t0 - group[i].t1
        if gap > best_gap:
            best_i, best_gap = i, gap
    if best_i is None:
        best_i = len(group) // 2

    # Every split must shrink both halves, or the recursion never terminates. With a
    # small max_words the margin can push best_i onto the last index, making `left` the
    # whole group and `right` empty -- a RecursionError at max_sentence_words=1.
    best_i = min(max(best_i, 0), len(group) - 2)

    left, right = group[: best_i + 1], group[best_i + 1 :]
    return _split_long(left, max_words) + _split_long(right, max_words)


def align_to_reference(words: list[Word], reference: str) -> list[Word]:
    """Replace ASR word text with a reference transcript's wording, keeping ASR timings.

    difflib over the two token streams; only 'equal' and 'replace' runs of matching length
    are substituted. Anything else is left as the ASR heard it, because a wrong alignment
    is worse than a wrong word -- it moves text onto the wrong timestamp.
    """
    ref_tokens = _TOKEN.findall(reference)
    if not ref_tokens or not words:
        return words

    asr_tokens = [w.text for w in words]
    matcher = difflib.SequenceMatcher(
        a=[t.lower().strip(".,!?\"'") for t in asr_tokens],
        b=[t.lower().strip(".,!?\"'") for t in ref_tokens],
        autojunk=False,
    )

    out = list(words)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("equal", "replace") and (i2 - i1) == (j2 - j1):
            for offset in range(i2 - i1):
                w = out[i1 + offset]
                out[i1 + offset] = Word(
                    text=ref_tokens[j1 + offset], t0=w.t0, t1=w.t1, speaker=w.speaker
                )
    return out


def from_word_json(path: str | Path) -> list[Word]:
    """Load a pre-computed word list: ``[{"text","t0","t1","speaker"?}, ...]``."""
    raw = json.loads(Path(path).read_text())
    items = raw["words"] if isinstance(raw, dict) else raw
    return [
        Word(
            text=w["text"].strip(),
            t0=float(w["t0"] if "t0" in w else w["start"]),
            t1=float(w["t1"] if "t1" in w else w["end"]),
            speaker=w.get("speaker"),
        )
        for w in items
        if w.get("text", "").strip()
    ]


#: Segments faster-whisper samples before deciding what language it is hearing. Its
#: default is 1 -- about 30 seconds -- so a talk that opens on applause, music or a
#: greeting in another language gets the whole hour transcribed as that language, which
#: is a silent failure: fluent, confident, and wrong from the first word.
LANGUAGE_DETECTION_SEGMENTS = 6


#: The CUDA runtime libraries CTranslate2 opens by name at the first encode, as shipped in
#: NVIDIA's pip wheels (the `asr` extra): nvidia/cublas/lib, nvidia/cudnn/lib.
CUDA_WHEEL_LIBS = ("libcublasLt.so.*", "libcublas.so.*", "libcudnn*.so.*")


def _load_cuda_wheels() -> int:
    """Load the pip-installed CUDA runtime into this process; return how many loaded.

    The wheels put the libraries under site-packages, where the OS loader never looks,
    so CTranslate2's ``dlopen("libcublas.so.12")`` fails on a machine whose GPU works.
    A library already loaded with ``RTLD_GLOBAL`` satisfies a later dlopen of the same
    soname, so loading them here, by full path, is the whole fix -- no LD_LIBRARY_PATH
    wrapper around the CLI. They depend on one another, so load in passes until a pass
    makes no progress rather than hard-coding an order that moves between releases.
    """
    try:
        import nvidia  # namespace package from the nvidia-* wheels
    except ImportError:
        return 0
    pending = [
        lib
        for root in getattr(nvidia, "__path__", [])
        for pattern in CUDA_WHEEL_LIBS
        for lib in sorted(Path(root).glob(f"*/lib/{pattern}"))
    ]
    loaded = 0
    while pending:
        failed = []
        for lib in pending:
            try:
                ctypes.CDLL(str(lib), mode=ctypes.RTLD_GLOBAL)
                loaded += 1
            except OSError:
                failed.append(lib)
        if len(failed) == len(pending):
            log.debug("could not load CUDA wheel libraries: %s", [p.name for p in failed])
            break
        pending = failed
    return loaded


def _decode(
    WhisperModel, media: str, model_size: str, config: Config, language: str | None = None
) -> list:
    """Decode on the GPU if it actually works, else on the CPU, and say which.

    `device="auto"` asks CTranslate2 whether a CUDA device *exists*, not whether its
    libraries load. pip puts the CUDA runtime where the OS loader does not look, so a
    machine with a working GPU constructs the model happily and then raises
    `Library libcublas.so.12 is not found` at the first encode -- after the model has
    downloaded and the caller has waited. The constructor is the wrong place to catch
    that, so the decode itself is retried.

    Segments are materialised inside the try: faster-whisper returns a generator, so a
    device failure surfaces during iteration, not at the call.
    """
    _load_cuda_wheels()
    for device in ("auto", "cpu"):
        try:
            model = WhisperModel(model_size, device=device, compute_type="int8")
            segments, info = model.transcribe(
                media,
                language=language,
                language_detection_segments=LANGUAGE_DETECTION_SEGMENTS,
                word_timestamps=True,
                beam_size=1,
                temperature=0.0,
                condition_on_previous_text=False,
                vad_filter=True,
            )
            if language is None:
                log.info(
                    "detected language %s (p=%.2f) from %d segments; pass --language to pin it",
                    getattr(info, "language", "?"),
                    getattr(info, "language_probability", 0.0),
                    LANGUAGE_DETECTION_SEGMENTS,
                )
            return list(segments)
        except Exception as exc:
            if device == "cpu":
                raise
            log.warning(
                "GPU transcription failed (%s); falling back to CPU, which is slower. "
                "`uv sync --extra asr` installs the CUDA runtime the GPU needs.",
                str(exc).strip().splitlines()[-1][:120],
            )
    raise AssertionError("unreachable")


def transcribe_media(
    media: str | Path,
    config: Config | None = None,
    *,
    model_size: str = "base",
    language: str | None = None,
) -> list[Word]:
    """Whisper with word timestamps. Cached, so a re-run is byte-identical and free.

    Greedy decoding and ``condition_on_previous_text=False``: we want the same transcript
    every run, and we do not want an earlier hallucination steering a later segment.
    """
    config = config or Config()
    # The model size is part of the key: a `base` transcript must not be served to a
    # caller that asked for `large`. "Byte-identical re-run" means identical inputs, not
    # identical paths.
    cache = Path(f"{media}.words.{model_size}.json")
    if cache.exists():
        cached = from_word_json(cache)
        if cached:
            return cached
        # An empty cache is a failed decode, not a silent video. Writing it would poison
        # every future run with no symptom beyond "transcript is empty".
        log.warning("ignoring empty ASR cache %s; re-transcribing", cache)

    if model_size == LEMONFOX:
        words = lemonfox_words(media, language)
        if not words:
            raise RuntimeError(f"Lemonfox returned no words for {media}.")
        _write_words(cache, words)
        return words

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "faster-whisper is not installed. Install with `uv sync --extra asr`, "
            "or supply a word list with --from-json."
        ) from exc

    segments = _decode(WhisperModel, str(media), model_size, config, language)

    words: list[Word] = []
    for seg in segments:
        # Whisper hallucinates confident text over silence and music. Filler in the state
        # is a context-rot tax and a source of fake anchors, so drop it here.
        if getattr(seg, "no_speech_prob", 0.0) > config.no_speech_threshold:
            continue
        for w in seg.words or []:
            if w.word.strip():
                words.append(Word(text=w.word.strip(), t0=float(w.start), t1=float(w.end)))

    if not words:
        # Fail loudly rather than caching nothing: an empty result is a broken decode or
        # a too-aggressive no_speech_threshold, and both are worth seeing now.
        raise RuntimeError(
            f"ASR produced no words for {media}. Check the audio track, or lower "
            f"no_speech_threshold (currently {config.no_speech_threshold})."
        )

    _write_words(cache, words)
    return words


def _write_words(path: Path, words: list[Word]) -> None:
    rows = []
    for w in words:
        row = {"text": w.text, "t0": w.t0, "t1": w.t1}
        if w.speaker:
            row["speaker"] = w.speaker
        rows.append(row)
    path.write_text(json.dumps(rows, indent=2))


#: The hosted option: `--model lemonfox`. Whisper behind an API, with punctuation that
#: Whisper `small` drops and speaker labels that become speaker-change cuts. On the pilot
#: set it put a real boundary at 78% of labeled starts against small's 75%, and raised
#: recall on every label set (RESEARCH.md, "Lemonfox transcripts"). $0.50 per 3 hours of
#: audio; needs LEMONFOX_API_KEY. Everything else stays local.
LEMONFOX = "lemonfox"
LEMONFOX_URL = "https://api.lemonfox.ai/v1/audio/transcriptions"
LEMONFOX_TIMEOUT_S = 900.0  # a 97-minute debate took 112s; uploads are the slow part


def lemonfox_words(media: str | Path, language: str | None = None) -> list[Word]:
    """Transcribe with Lemonfox: word timings, punctuation and speaker labels.

    The audio is sent, not the video: mono 16kHz Opus at 32kbps keeps a 97-minute file
    near 23MB, well under the 100MB upload limit."""
    import os
    import subprocess
    import tempfile
    import urllib.error
    import urllib.request
    import uuid

    key = os.environ.get("LEMONFOX_API_KEY")
    if not key:
        raise RuntimeError("LEMONFOX_API_KEY is not set (put it in .env.local).")

    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "audio.ogg"
        subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(media),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "libopus",
                "-b:a",
                "32k",
                str(audio),
            ],
            check=True,
        )
        fields = {
            "response_format": "verbose_json",
            "timestamp_granularities[]": "word",
            "speaker_labels": "true",
        }
        if language:
            fields["language"] = language
        boundary = uuid.uuid4().hex
        body = b"".join(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
            for k, v in fields.items()
        )
        body += (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="audio.ogg"\r\nContent-Type: audio/ogg\r\n\r\n'
            ).encode()
            + audio.read_bytes()
            + f"\r\n--{boundary}--\r\n".encode()
        )

    request = urllib.request.Request(
        LEMONFOX_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=LEMONFOX_TIMEOUT_S) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise RuntimeError(f"Lemonfox HTTP {exc.code}: {detail}") from exc
    return words_from_lemonfox(data)


def words_from_lemonfox(data: dict) -> list[Word]:
    """Lemonfox's verbose_json -> words. A word without timings (rare: a token the aligner
    could not place) is dropped rather than given a guessed time."""
    return [
        Word(
            text=w["word"].strip(),
            t0=float(w["start"]),
            t1=float(w["end"]),
            speaker=w.get("speaker"),
        )
        for w in data.get("words", [])
        if w.get("word", "").strip() and "start" in w and "end" in w
    ]


def ingest(
    source: str | Path,
    config: Config | None = None,
    *,
    from_json: str | Path | None = None,
    reference: str | Path | None = None,
    model_size: str = "base",
    language: str | None = None,
) -> Transcript:
    config = config or Config()
    words = (
        from_word_json(from_json)
        if from_json
        else transcribe_media(source, config, model_size=model_size, language=language)
    )
    if reference:
        words = align_to_reference(words, Path(reference).read_text())
    sentences = segment_words(words, config)
    duration = sentences[-1].t1 if sentences else 0.0
    return Transcript(sentences=sentences, source=str(source), duration=duration)


def sanity_check(transcript: Transcript) -> list[str]:
    """Segmentation smells. Empty list means nothing looks wrong.

    The density band is issue 002's acceptance criterion: a 60-minute video should land
    at 400-800 sentences. Outside it, segmentation is wrong and every later pass inherits
    the problem.
    """
    problems: list[str] = []
    if not transcript.sentences:
        return ["transcript is empty"]

    minutes = transcript.duration / 60.0
    if minutes >= 5:
        per_hour = len(transcript) / (minutes / 60.0)
        if not 400 <= per_hour <= 800:
            problems.append(f"{per_hour:.0f} sentences/hour is outside the 400-800 sanity band")

    for s in transcript.sentences:
        if s.words:
            if abs(s.t0 - s.words[0].t0) > 0.1 or abs(s.t1 - s.words[-1].t1) > 0.1:
                problems.append(f"{s.id}: bounds drift >100ms from its words")
        if s.t1 < s.t0:
            problems.append(f"{s.id}: negative duration")
    return problems
