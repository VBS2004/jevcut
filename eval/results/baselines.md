# Baselines (issue 013), pilot set

jevcut against five simpler ways of cutting the same eight videos: the same Lemonfox
transcripts, the same cut points, the same rubric-v2 labels, and every system shipping as
many clips per video as jevcut did (177). Built by
[`eval/experiments/baselines.py`](../experiments/baselines.py); written up in
[RESEARCH.md](../../RESEARCH.md), "Baselines (013)". 8 videos, not 013's 40.

| system | how it picks and cuts |
| --- | --- |
| jevcut | scan (6 rounds per window) → opening Choice → earliest clean ending → gate and ad check |
| dense | every sentence judged with the gate's questions; clips around the peaks of a 12s rolling average, ~40s |
| windows | 30s windows ending on sentence ends (capped 45s), each judged once, the best kept |
| naive | the top-scoring sentence ± 15s |
| offset | jevcut's own anchors, edges at a constant offset fitted leave-one-video-out on labeler A (start ~18s before, end ~12s after) |
| snap | jevcut's own anchors, grown a sentence at a time to ~40s; no model call for edges |

| system | labels | clips | found | both edges right | P | R (chance) | start err p50 / p90 | on a negative | length | mid-thought (judged) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| jevcut | v2 A | 177 | 30 | 10 | 0.24 | 0.54 (0.25) | 1.1s / 16.7s | 0.07 | 44s | 68% |
| jevcut | v2 B | 177 | 32 | 11 | 0.26 | 0.56 (0.24) | 1.9s / 19.1s | 0.06 | 44s | 68% |
| dense | v2 A | 177 | 25 | 1 | 0.19 | 0.45 (0.27) | 6.8s / 14.9s | 0.13 | 40s | 92% |
| dense | v2 B | 177 | 22 | 1 | 0.20 | 0.39 (0.26) | 7.9s / 15.0s | 0.14 | 40s | 92% |
| windows | v2 A | 177 | 25 | 1 | 0.21 | 0.45 (0.24) | 8.0s / 20.7s | 0.10 | 32s | 89% |
| windows | v2 B | 177 | 31 | 3 | 0.21 | 0.54 (0.23) | 7.0s / 17.8s | 0.10 | 32s | 89% |
| naive | v2 A | 177 | 24 | 3 | 0.18 | 0.43 (0.25) | 6.6s / 14.7s | 0.08 | 35s | 92% |
| naive | v2 B | 177 | 19 | 3 | 0.15 | 0.33 (0.24) | 4.5s / 15.1s | 0.12 | 35s | 92% |
| offset | v2 A | 177 | 19 | 1 | 0.14 | 0.34 (0.24) | 9.4s / 19.0s | 0.07 | 35s | 96% |
| offset | v2 B | 177 | 18 | 1 | 0.16 | 0.32 (0.24) | 7.0s / 17.7s | 0.07 | 35s | 96% |
| snap | v2 A | 177 | 21 | 0 | 0.16 | 0.38 (0.27) | 7.0s / 18.3s | 0.07 | 42s | 95% |
| snap | v2 B | 177 | 16 | 0 | 0.15 | 0.28 (0.26) | 4.3s / 19.2s | 0.07 | 42s | 95% |

"Mid-thought (judged)" is the share of shipped clips the gate's own questions read as
starting or ending mid-thought (either at 0.5 or more). The judge is the one jevcut's
search optimises against, so it favours jevcut; as a yardstick, the labelers' own clips
score 46% (A) and 42% (B) on it.

**Spread of the target around the anchor** (013's gotcha): the labeled start sits 18-22s
before jevcut's anchor with a standard deviation of 17-18s, and the end 9-12s after with
17-18s. A constant is nowhere near optimal by construction, so the comparison can tell
methods apart.

**Start error on moments both systems found** (p50 / p90, jevcut first):

| vs | labeler A | labeler B |
| --- | --- | --- |
| dense | 1.8 / 19.8s vs 9.4 / 16.1s | 1.5 / 17.8s vs 8.8 / 16.3s |
| naive | 1.8 / 17.7s vs 7.7 / 17.1s | 1.1 / 15.3s vs 4.1 / 22.1s |
| windows | 1.2 / 16.5s vs 5.9 / 29.4s | 1.3 / 20.0s vs 7.8 / 16.9s |
| offset | 0.6 / 20.9s vs 9.3 / 14.6s | 0.6 / 15.0s vs 5.0 / 14.1s |
| snap | 0.8 / 20.1s vs 5.8 / 17.0s | 0.9 / 15.8s vs 4.3 / 18.1s |

Requests: jevcut ~2,400 for the set (scan + search); dense and naive 4,118 (every
sentence); windows 505; offset and snap reuse jevcut's selection and spend nothing on edges.
