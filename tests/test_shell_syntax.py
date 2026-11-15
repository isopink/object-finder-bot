"""bash -n on every .sh file in the repo (skipped when bash is not available)."""
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", ".venv", "venv", "build", "install", "log", "__pycache__"}


def _sh_files():
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(".sh"):
                out.append(os.path.join(dirpath, name))
    return sorted(out)


FILES = _sh_files()
BASH = shutil.which("bash")


@pytest.mark.skipif(BASH is None, reason="bash not available")
@pytest.mark.parametrize("path", FILES, ids=[os.path.relpath(p, ROOT) for p in FILES])
def test_bash_syntax(path):
    rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
    res = subprocess.run([BASH, "-n", rel], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert res.returncode == 0, res.stderr.decode("utf-8", "replace")
