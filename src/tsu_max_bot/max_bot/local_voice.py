import json
import logging
from io import BytesIO
from itertools import chain
from pathlib import Path
from threading import Lock

_LOGGER = logging.getLogger(__name__)
_SAMPLE_RATE = 16_000
_BYTES_PER_SAMPLE = 2
MAX_LOCAL_AUDIO_BYTES = 4_000_000
_MAX_PCM_BYTES = 30 * _SAMPLE_RATE * _BYTES_PER_SAMPLE
_AUDIO_DEMUXERS = "ogg,mp3,aac,mov,mp4,m4a,wav"


def _decode_audio(data: bytes) -> bytes | None:
    import av

    pcm = bytearray()
    # Probe by content. Restrict FFmpeg to self-contained audio and disable MP4 data references.
    options = {"format_whitelist": _AUDIO_DEMUXERS, "enable_drefs": "0"}
    with av.open(BytesIO(data), options=options) as container:
        tracks = container.streams.audio
        if len(tracks) != 1:
            return None

        resampler = av.AudioResampler(format="s16", layout="mono", rate=_SAMPLE_RATE)
        # A final None flushes the samples buffered during resampling.
        for frame in chain(container.decode(tracks[0]), (None,)):
            for converted in resampler.resample(frame):
                size = converted.samples * _BYTES_PER_SAMPLE
                if len(pcm) + size > _MAX_PCM_BYTES:
                    return None
                pcm.extend(memoryview(converted.planes[0])[:size])
    return bytes(pcm) or None


class LocalVoice:
    """Recognize short MAX voice messages with a local Vosk model."""

    def __init__(self, model_path: Path) -> None:
        self._model_path = model_path
        self._model = None
        self._model_lock = Lock()

    def recognize(self, data: bytes) -> str | None:
        if not data or len(data) > MAX_LOCAL_AUDIO_BYTES:
            return None
        try:
            pcm = _decode_audio(data)
            if not pcm:
                return None
        except Exception as error:
            _LOGGER.debug("Could not decode MAX voice message (%s)", type(error).__name__)
            return None

        try:
            import vosk

            with self._model_lock:
                if self._model is None:
                    vosk.SetLogLevel(-1)
                    self._model = vosk.Model(str(self._model_path))
                model = self._model

            recognizer = vosk.KaldiRecognizer(model, _SAMPLE_RATE)
            results = []
            # Read a quarter second at a time to preserve phrases separated by pauses.
            chunk_size = _SAMPLE_RATE * _BYTES_PER_SAMPLE // 4
            for offset in range(0, len(pcm), chunk_size):
                if recognizer.AcceptWaveform(pcm[offset : offset + chunk_size]):
                    results.append(recognizer.Result())
            results.append(recognizer.FinalResult())
            texts = (json.loads(result)["text"].strip() for result in results)
            return " ".join(filter(None, texts)) or None
        except Exception as error:
            # Vosk's Python binding raises a plain Exception on native failures.
            _LOGGER.warning("Local voice recognition failed (%s)", type(error).__name__)
            return None
