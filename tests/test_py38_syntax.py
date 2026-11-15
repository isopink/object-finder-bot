"""Every .py file in the repo must parse as Python 3.8 (the Jetson runs 3.8)."""
import ast
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", ".venv", "venv", "build", "install", "log", "__pycache__", ".pytest_cache"}


def _py_files():
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.endswith(".egg-info")]
        for name in filenames:
            if name.endswith(".py"):
                out.append(os.path.join(dirpath, name))
    return sorted(out)


FILES = _py_files()


def test_found_files():
    assert FILES


@pytest.mark.parametrize("path", FILES, ids=[os.path.relpath(p, ROOT) for p in FILES])
def test_parses_as_python38(path):
    with open(path, "r", encoding="utf-8") as fh:
        source = fh.read()
    ast.parse(source, filename=path, feature_version=(3, 8))
