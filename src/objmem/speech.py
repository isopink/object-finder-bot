"""Speech to text for spoken queries.

    stt = WhisperSTT("base.en")
    text = stt.listen()      # records one utterance, returns English text

``WhisperSTT`` records from the default microphone with ``arecord`` (ALSA,
Linux) until the speaker stops or a time limit is reached, then runs OpenAI
Whisper on the samples. The model is loaded on the first ``listen()`` only,
because the Jetson shares 8 GB between CPU and GPU; ``unload()`` frees it.

``FakeSTT`` returns fixed text and is used in tests and on a PC.

Install on the Jetson (do not let pip touch torch):

    pip install --no-deps openai-whisper
    pip install tiktoken more-itertools numba tqdm

Check the microphone: ``arecord -l`` lists capture devices; pass e.g.
``device="plughw:2,0"`` when the USB microphone is not the default.
"""
import subprocess
from typing import Any, Callable, List, Optional, Sequence, Union

import numpy as np

SAMPLE_RATE = 16000  # Hz, what Whisper expects
_BYTES_PER_SAMPLE = 2  # S16_LE mono


class FakeSTT:
    """SpeechToText that returns canned text.

    ``FakeSTT("where is the mug")`` always returns that text.
    ``FakeSTT(["first", "second"])`` returns them in turn and repeats the last.
    """

    def __init__(self, text: Union[str, Sequence[str]] = ""):
        if isinstance(text, str):
            self._texts = [text]  # type: List[str]
        else:
            self._texts = list(text) or [""]
        self.calls = 0

    def listen(self) -> str:
        index = min(self.calls, len(self._texts) - 1)
        self.calls += 1
        return self._texts[index]


def rms(chunk: np.ndarray) -> float:
    """Root mean square of float samples in [-1, 1]."""
    if chunk.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(chunk.astype(np.float64)))))


def record_until_silence(
    max_seconds: float = 8.0,
    silence_seconds: float = 1.0,
    silence_rms: float = 0.015,
    chunk_seconds: float = 0.1,
    device: Optional[str] = None,
    popen: Callable[..., Any] = subprocess.Popen,
) -> np.ndarray:
    """Record one utterance with ``arecord``; return float32 mono samples at 16 kHz.

    Recording stops ``silence_seconds`` after the speaker goes quiet (chunk
    RMS below ``silence_rms`` once speech has been heard), or after
    ``max_seconds`` in any case. Returns an empty array when nothing louder
    than ``silence_rms`` was heard, so the caller can skip transcription.

    ``popen`` is injectable for tests.
    """
    cmd = ["arecord", "-q", "-t", "raw", "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", "1"]
    if device:
        cmd += ["-D", device]
    try:
        proc = popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise RuntimeError(
            "arecord was not found. Install it with 'sudo apt install alsa-utils' "
            "(Linux only), or pass your own recorder to WhisperSTT(recorder=...)."
        )

    chunk_samples = max(1, int(round(SAMPLE_RATE * chunk_seconds)))
    chunk_bytes = chunk_samples * _BYTES_PER_SAMPLE
    max_chunks = max(1, int(round(max_seconds / chunk_seconds)))
    quiet_limit = max(1, int(round(silence_seconds / chunk_seconds)))

    chunks = []  # type: List[np.ndarray]
    heard_speech = False
    quiet_chunks = 0
    try:
        for _ in range(max_chunks):
            data = proc.stdout.read(chunk_bytes)
            if not data:
                break
            data = data[: len(data) - (len(data) % _BYTES_PER_SAMPLE)]
            samples = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
            chunks.append(samples)
            if rms(samples) >= silence_rms:
                heard_speech = True
                quiet_chunks = 0
            elif heard_speech:
                quiet_chunks += 1
                if quiet_chunks >= quiet_limit:
                    break
    finally:
        _stop(proc)

    if not chunks:
        detail = ""
        try:
            err = proc.stderr.read() if proc.stderr is not None else b""
            detail = err.decode("utf-8", "replace").strip() if err else ""
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(
            "arecord produced no audio{}. Check the microphone with 'arecord -l'.".format(
                ": " + detail if detail else ""))
    if not heard_speech:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32)


def _stop(proc: Any) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=2.0)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


class WhisperSTT:
    """SpeechToText backed by OpenAI Whisper.

    model: Whisper model name (``tiny.en``, ``base.en``, ``small.en``, ...).
    device: ``"cuda"`` / ``"cpu"``; None lets Whisper choose (CUDA if available).
    max_seconds, silence_seconds, silence_rms, mic: recording settings, see
        ``record_until_silence``. ``mic`` is the ALSA capture device.
    recorder: a callable returning float32 mono 16 kHz samples; replaces
        ``arecord`` (used in tests, or on a machine without ALSA).
    """

    def __init__(
        self,
        model: str = "base.en",
        device: Optional[str] = None,
        max_seconds: float = 8.0,
        silence_seconds: float = 1.0,
        silence_rms: float = 0.015,
        mic: Optional[str] = None,
        recorder: Optional[Callable[[], np.ndarray]] = None,
    ):
        self.model_name = model
        self.device = device
        self.max_seconds = max_seconds
        self.silence_seconds = silence_seconds
        self.silence_rms = silence_rms
        self.mic = mic
        self._recorder = recorder
        self._model = None  # type: Any

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _load(self) -> Any:
        if self._model is None:
            import whisper  # heavy; only when first needed
            self._model = whisper.load_model(self.model_name, device=self.device)
        return self._model

    def unload(self) -> None:
        """Drop the model so its memory can be reclaimed."""
        self._model = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001 - torch is optional here
            pass

    def record(self) -> np.ndarray:
        if self._recorder is not None:
            return np.asarray(self._recorder(), dtype=np.float32).reshape(-1)
        return record_until_silence(
            max_seconds=self.max_seconds,
            silence_seconds=self.silence_seconds,
            silence_rms=self.silence_rms,
            device=self.mic,
        )

    def transcribe(self, audio: np.ndarray) -> str:
        """Float32 mono 16 kHz samples -> text."""
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        if audio.size == 0:
            return ""
        model = self._load()
        use_fp16 = str(getattr(model, "device", "cpu")).startswith("cuda")
        kwargs = {"fp16": use_fp16}
        if not self.model_name.endswith(".en"):
            kwargs["language"] = "en"
        result = model.transcribe(audio, **kwargs)
        return " ".join(str(result.get("text", "")).split())

    def listen(self) -> str:
        """Record one utterance and return the recognized text ("" if nothing was said)."""
        audio = self.record()
        if audio.size == 0:
            return ""  # silence: do not load or run the model
        return self.transcribe(audio)
