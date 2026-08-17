"""
Makes the pipeline package in src/ importable from tests.

The pipeline scripts are run directly (`python src/chunk.py`), which puts
src/ on the import path automatically. pytest runs from the repo root, so
it needs the same path added explicitly.
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
