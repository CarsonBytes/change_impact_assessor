"""End-to-end test that the corpus passes its own consistency checks."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_corpus_is_consistent():
    """Calls eval/validate_corpus.py — fails if cross-references are broken."""
    result = subprocess.run(
        [sys.executable, "-m", "eval.validate_corpus"],
        cwd=ROOT,
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Corpus inconsistent:\n{result.stdout}\n{result.stderr}"
