"""Params defaults must match config/default.yaml; unknown keys must raise."""
import os
from dataclasses import fields

import pytest
import yaml

from objmem.types import Params

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_YAML = os.path.join(ROOT, "config", "default.yaml")


def test_defaults_match_yaml():
    with open(DEFAULT_YAML, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    defaults = Params()
    names = {f.name for f in fields(Params)}
    assert set(data) == names
    for key, value in data.items():
        assert getattr(defaults, key) == value, key


def test_load_default_yaml_equals_defaults():
    assert Params.load(DEFAULT_YAML) == Params()


def test_load_none_gives_defaults():
    assert Params.load(None) == Params()


def test_unknown_key_raises(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("d: 0.9\nnot_a_key: 1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        Params.load(str(path))


def test_override(tmp_path):
    path = tmp_path / "ok.yaml"
    path.write_text("camera_mode: nodepth\ntop_k: 5\n", encoding="utf-8")
    params = Params.load(str(path))
    assert params.camera_mode == "nodepth"
    assert params.top_k == 5
