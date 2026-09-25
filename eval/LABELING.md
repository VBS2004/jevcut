# Labeling brief

Instructions for a labeler (human or agent) adding videos to the eval set. The spec a
label encodes is [RUBRIC.md](RUBRIC.md): read it first, in full, and follow it exactly --
open on the hook but keep the setup the payoff needs, stop as soon as the payoff lands,
prefer the shorter of two working cuts.

## Hard rules

- **Blind.** Your only inputs are RUBRIC.md, this brief and the transcripts. Do not run
  any `jevcut` command. Never open, list, grep or read: any label directory other than
  the one you write to, any `edl.json`, `index.html`, `anchors.json` or `.mp4`,
  `eval/benchmarks/`, `eval/results/`, `RESEARCH.md`, `BENCHMARKS.md`, or git history.
- Write only the label files named in your task. Do not commit or push.
- Read the whole transcript before deciding anything.

## Reading a transcript

```
cd /home/vbs2004/jevcut && .venv/bin/python -c "
from jevcut.models import Transcript
t = Transcript.from_json('eval/media/asr-lemonfox/<slug>.json')
for s in t.sentences: print(f'{s.id} {s.t0:7.1f}-{s.t1:7.1f} {s.text}')
"
```

Times are seconds in the source video. The transcript is Lemonfox (hosted Whisper): good
punctuation, but proper nouns can be misheard. When the right start or end is inside a
printed line, give that word's time: `for w in s.words: print(w.t0, w.t1, w.text)`.
Speaker labels, where present, are on each word (`w.speaker`); infer speakers from the
text when they matter, and say so in `why`.
sha256 prefix: `sha256sum eval/media/<slug>.mp4 | cut -c1-16`.
Duration: `ffprobe -v error -show_entries format=duration -of csv=p=0 eval/media/<slug>.mp4`.

Much of some videos is narration of what is on screen (deals, charts, gameplay, a demo).
That is not a clip, however lively it sounds -- label the tempting parts as negatives.
Comedy counts: a bit with a setup and a punchline is a clip, even when the laugh is the
payoff.

## Format -- `eval/<label dir>/<youtube id>.json`, exactly this shape

```json
{
  "video": {"url": "https://www.youtube.com/watch?v=<id>", "title": "...", "channel": "...",
            "genre": "...", "duration_s": 0.0, "sha256_prefix": "...",
            "local_path": "eval/media/<slug>.mp4"},
  "protocol": {
    "status": "<given in your task>",
    "rubric": "eval/RUBRIC.md v2",
    "labeled_blind": true,
    "note": "Drafted from the transcript alone, without seeing any jevcut output or other labels.",
    "reviewed_by": null,
    "times_from": "Lemonfox transcript; seconds in the source, so labels survive re-transcription"
  },
  "clips": [
    {"id": "short-slug", "start": 0.0, "start_range": [0.0, 0.0], "end": 0.0, "end_range": [0.0, 0.0],
     "why": "what the clip is, what its hook is, and where the payoff lands", "over_band": false}
  ],
  "also_ok": [ "same shape as a clip" ],
  "negatives": [ {"start": 0.0, "end": 0.0, "why": "..."} ]
}
```

Use the genre you were given, word for word: the eval reports results per genre. Validate
every file parses (`python -m json.tool`), that start <= end, and that each preferred time
is inside its range.

## Report back

Per video: file written, clip / also_ok / negative counts, median clip length, and one line
on anything hard to call. Keep it short.
