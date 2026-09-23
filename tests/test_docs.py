"""The docs must keep describing the code. See scripts/check_docs.py for what "describe"
means here -- names and copied wording, not prose."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_the_docs_still_describe_the_code():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_docs.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, "docs have drifted from the code:\n" + result.stdout
