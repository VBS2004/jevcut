"""Build the benchmark web page from the saved versions in eval/benchmarks/.

The same numbers as `jevcut bench` / BENCHMARKS.md, drawn as charts: every version and
every 013 baseline against both labelers of both label sets. The page is
eval/benchmarks/page.template.html with the data filled in; publish the output as is.

    uv run python scripts/bench_page.py out.html
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jevcut import evaluate

SETS = (
    ("v2A", "eval/labels-v2"),
    ("v2B", "eval/labels-v2-b"),
    ("v1A", "eval/labels"),
    ("v1B", "eval/labels-b"),
)
TEMPLATE = Path("eval/benchmarks/page.template.html")


def data() -> dict:
    out: dict = {"versions": [], "scores": {}}
    for d, about in evaluate.benchmarks():
        out["versions"].append(
            {k: about.get(k) for k in ("commit", "what", "gate_requests")} | {"id": about["name"]}
        )
        for key, labels in SETS:
            scores, _ = evaluate.score_set(labels, edl_dir=d)
            s = evaluate.summary(scores)
            out["scores"][f"{about['name']}|{key}"] = {
                "clips": s["predicted"],
                "hit": s["matched"],
                "labeled": s["labeled"],
                "both_right": sum(v.in_range for v in scores),
                "precision": round(s["precision"], 3),
                "recall": round(s["recall"], 3),
                "chance": round(s["chance_recall"], 3),
                "start_err": round(s["start_err_median"], 1),
                "end_err": round(s["end_err_median"], 1),
                "negative": round(s["negative_rate"], 3),
                "length": round(s["duration_median"], 1),
                "label_length": round(s["label_duration_median"], 1),
            }
    return out


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "benchmarks.html")
    out.write_text(TEMPLATE.read_text().replace("__DATA__", json.dumps(data())))
    print(f"wrote {out}")
