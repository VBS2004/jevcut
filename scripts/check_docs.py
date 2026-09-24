"""Do the docs still describe the code?

Written after a sweep found the README announcing a research pause that had ended, the
gate spec in QUESTIONS.md showing wording that rejected every clip, issues for built code
with no status, and the main CLI command missing from the run instructions. Each check
below is a kind of drift that actually happened. It checks facts, not prose: it cannot
tell whether an explanation is still true, only whether the names it relies on exist.

Exit 0 when clean; exit 1 with one line per problem otherwise. Run by `tests/test_docs.py`
and by a Claude Code Stop hook, so drift shows up before a session ends.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

#: Shared plumbing with no issue of its own; every other module must be claimed by one.
UNOWNED_OK = {"__init__", "backends", "models"}


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def table_names(text: str, heading: str) -> set[str]:
    """Backticked names in the first column of the first table under `heading`."""
    start = text.find(heading)
    if start < 0:
        return set()
    names, in_table = set(), False
    for line in text[start:].splitlines()[1:]:
        if line.startswith("|"):
            in_table = True
            first = line.split("|")[1]
            names |= set(re.findall(r"`([a-z_]+)`", first))
        elif in_table:
            break
        elif line.startswith("#"):
            break
    return names


def _flat(text: str) -> str:
    """Whitespace, implicit string concatenation and dash style normalised away, so a
    copy is compared on its words, not on how it was wrapped."""
    text = re.sub(r'"\s*\n\s*"', "", text)
    return re.sub(r"\s+", " ", text.replace("\u2014", "--")).strip()


def check_questions(problems: list[str]) -> None:
    from jevcut.questions import (
        opening_questions,
        promotion_questions,
        scan_questions,
        verify_questions,
    )

    everything = {
        **scan_questions(["L000"]),
        **opening_questions(["C00"]),
        **promotion_questions(),
        **verify_questions(),
    }
    gate = set(verify_questions())
    questions_md = read("docs/QUESTIONS.md")
    flat_doc = _flat(questions_md)
    for name, q in sorted(everything.items()):
        if f"`{name}`" not in questions_md and f'"{name}"' not in questions_md:
            problems.append(f"docs/QUESTIONS.md never mentions question `{name}`")
        # A doc that copies a question's wording must copy the current wording. The Pass E
        # copy drifted this way and showed a gate that rejected every clip for two days.
        if re.search(rf'"{name}":\s*(Noul|Choice|Score)\(', questions_md):
            wording = q.instructions if isinstance(q.instructions, str) else str(q.instructions)
            if _flat(wording) not in flat_doc:
                problems.append(
                    f"docs/QUESTIONS.md copies the wording of `{name}` and the copy no longer "
                    "matches src/jevcut/questions.py"
                )
    for doc, heading in (
        ("docs/QUESTIONS.md", "## Pass E"),
        ("docs/ARCHITECTURE.md", "### E. Verify"),
    ):
        listed = table_names(read(doc), heading)
        if not listed:
            problems.append(f"{doc}: no question table under '{heading}'")
        for name in sorted(listed - gate):
            problems.append(f"{doc} lists gate question `{name}`, which no longer exists")
        for name in sorted(gate - listed):
            problems.append(f"{doc} gate table is missing `{name}`")


def check_cli(problems: list[str]) -> None:
    commands = re.findall(r'add_parser\("([a-z]+)"', read("src/jevcut/cli.py"))
    readme = read("README.md")
    for name in commands:
        if f"jevcut {name}" not in readme:
            problems.append(f"README.md never shows `jevcut {name}`")


def check_issue_status(problems: list[str]) -> None:
    status_lines = [
        line
        for f in sorted((ROOT / "issues").glob("*.md"))
        for line in read(f"issues/{f.name}").splitlines()
        if line.startswith("| **Status** |")
    ]
    claimed = " ".join(status_lines)
    for module in sorted((ROOT / "src/jevcut").glob("*.py")):
        if module.stem in UNOWNED_OK:
            continue
        # The full path, not the bare filename: "gate.py" is a substring of
        # "tests/test_gate.py", which let a deleted module reference go unnoticed.
        if f"src/jevcut/{module.name}" not in claimed:
            problems.append(
                f"src/jevcut/{module.name} is not named in any issue's Status line "
                "(built but not recorded as built?)"
            )


def main() -> int:
    problems: list[str] = []
    for check in (check_questions, check_cli, check_issue_status):
        check(problems)
    for p in problems:
        print(p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
