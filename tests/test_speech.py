"""Tests for objmem.speech with the recorder and the Whisper model mocked."""
import io
import sys
import types

import numpy as np
import pytest

from objmem import speech
from objmem.speech import SAMPLE_RATE, FakeSTT, WhisperSTT, record_until_silence

CHUNK = SAMPLE_RATE // 10  # samples in 0.1 s


def pcm(level, n_chunks):
    """n_chunks * 0.1 s of a square wave with the given amplitude, as S16_LE bytes."""
    samples = np.full(CHUNK * n_chunks, int(level * 32767), dtype="<i2")
    samples[1::2] *= -1
    return samples.tobytes()


class FakeProc:
    def __init__(self, data, stderr=b""):
        self.stdout = io.BytesIO(data)
        self.stderr = io.BytesIO(stderr)
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.terminated = True


class FakePopen:
    def __init__(self, data, stderr=b""):
        self.proc = FakeProc(data, stderr)
        self.cmd = None

    def __call__(self, cmd, **kwargs):
        self.cmd = cmd
        return self.proc


class FakeWhisperModel:
    def __init__(self, text=" Where is the blue mug? ", device="cpu"):
        self.text = text
        self.device = device
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append((audio, kwargs))
        return {"text": self.text}


@pytest.fixture
def fake_whisper(monkeypatch):
    """Install a fake ``whisper`` module; returns it with .loads and .model."""
    module = types.ModuleType("whisper")
    module.loads = []
    module.model = FakeWhisperModel()

    def load_model(name, device=None):
        module.loads.append((name, device))
        return module.model

    module.load_model = load_model
    monkeypatch.setitem(sys.modules, "whisper", module)
    return module


# ------------------------------------------------------------------ FakeSTT
def test_fake_stt_fixed_text():
    stt = FakeSTT("where is the mug")
    assert stt.listen() == "where is the mug"
    assert stt.listen() == "where is the mug"
    assert stt.calls == 2


def test_fake_stt_sequence_repeats_last():
    stt = FakeSTT(["one", "two"])
    assert [stt.listen() for _ in range(3)] == ["one", "two", "two"]
    assert FakeSTT([]).listen() == ""


# ------------------------------------------------------------------ recorder
def test_record_stops_after_silence_following_speech():
    # 0.3 s quiet, 0.5 s speech, then 3 s quiet: stop 1.0 s into the trailing quiet.
    popen = FakePopen(pcm(0.001, 3) + pcm(0.3, 5) + pcm(0.001, 30))
    audio = record_until_silence(max_seconds=8.0, silence_seconds=1.0, popen=popen)
    assert audio.dtype == np.float32
    assert audio.size == CHUNK * (3 + 5 + 10)
    assert np.max(np.abs(audio)) == pytest.approx(0.3, abs=1e-3)
    assert popen.proc.terminated
    assert popen.cmd[0] == "arecord"
    assert popen.cmd[popen.cmd.index("-r") + 1] == "16000"
    assert popen.cmd[popen.cmd.index("-f") + 1] == "S16_LE"
    assert "-D" not in popen.cmd


def test_record_short_pause_does_not_stop():
    # A 0.5 s pause inside the utterance is shorter than silence_seconds.
    popen = FakePopen(pcm(0.3, 3) + pcm(0.001, 5) + pcm(0.3, 3) + pcm(0.001, 30))
    audio = record_until_silence(silence_seconds=1.0, popen=popen)
    assert audio.size == CHUNK * (3 + 5 + 3 + 10)


def test_record_time_limit():
    popen = FakePopen(pcm(0.3, 100))  # the speaker never stops
    audio = record_until_silence(max_seconds=2.0, popen=popen)
    assert audio.size == CHUNK * 20
    assert popen.proc.terminated


def test_record_only_silence_returns_empty():
    popen = FakePopen(pcm(0.001, 100))
    audio = record_until_silence(max_seconds=2.0, popen=popen)
    assert audio.size == 0
    assert popen.proc.terminated


def test_record_device_argument():
    popen = FakePopen(pcm(0.3, 2) + pcm(0.0, 20))
    record_until_silence(device="plughw:2,0", popen=popen)
    assert popen.cmd[popen.cmd.index("-D") + 1] == "plughw:2,0"


def test_record_no_audio_raises_with_arecord_message():
    popen = FakePopen(b"", stderr=b"arecord: main:830: audio open error: No such file or directory")
    with pytest.raises(RuntimeError) as err:
        record_until_silence(popen=popen)
    assert "audio open error" in str(err.value)


def test_record_missing_arecord_raises_runtime_error():
    def popen(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    with pytest.raises(RuntimeError) as err:
        record_until_silence(popen=popen)
    assert "arecord" in str(err.value)


# ------------------------------------------------------------------ WhisperSTT
def test_whisper_loads_on_first_listen_only(fake_whisper):
    audio = np.ones(SAMPLE_RATE, dtype=np.float32) * 0.1
    stt = WhisperSTT(recorder=lambda: audio)
    assert stt.model_name == "base.en"
    assert not stt.loaded
    assert fake_whisper.loads == []  # constructing does not load the model

    assert stt.listen() == "Where is the blue mug?"
    assert stt.loaded
    assert stt.listen() == "Where is the blue mug?"
    assert fake_whisper.loads == [("base.en", None)]  # loaded once

    passed, kwargs = fake_whisper.model.calls[0]
    assert passed.dtype == np.float32 and passed.shape == (SAMPLE_RATE,)
    assert kwargs == {"fp16": False}  # CPU model, English-only model name


def test_whisper_fp16_on_cuda_and_language_for_multilingual(fake_whisper):
    fake_whisper.model.device = "cuda:0"
    stt = WhisperSTT(model="base", device="cuda", recorder=lambda: np.ones(100, dtype=np.float32))
    stt.listen()
    assert fake_whisper.loads == [("base", "cuda")]
    assert fake_whisper.model.calls[0][1] == {"fp16": True, "language": "en"}


def test_whisper_silence_returns_empty_without_loading(fake_whisper):
    stt = WhisperSTT(recorder=lambda: np.zeros(0, dtype=np.float32))
    assert stt.listen() == ""
    assert fake_whisper.loads == []


def test_whisper_unload_then_reload(fake_whisper):
    stt = WhisperSTT(recorder=lambda: np.ones(10, dtype=np.float32))
    stt.listen()
    stt.unload()
    assert not stt.loaded
    stt.listen()
    assert len(fake_whisper.loads) == 2


def test_whisper_uses_arecord_recorder_with_its_settings(fake_whisper, monkeypatch):
    seen = {}

    def fake_record(**kwargs):
        seen.update(kwargs)
        return np.ones(10, dtype=np.float32)

    monkeypatch.setattr(speech, "record_until_silence", fake_record)
    stt = WhisperSTT(max_seconds=5.0, silence_seconds=0.7, silence_rms=0.02, mic="plughw:2,0")
    assert stt.listen() == "Where is the blue mug?"
    assert seen == {"max_seconds": 5.0, "silence_seconds": 0.7, "silence_rms": 0.02, "device": "plughw:2,0"}


def test_import_does_not_need_whisper():
    assert "whisper" not in sys.modules or isinstance(sys.modules["whisper"], types.ModuleType)
    assert not hasattr(speech, "whisper")
