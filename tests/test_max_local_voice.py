import sys
from io import BytesIO
from types import SimpleNamespace

import pytest

from tsu_max_bot.max_bot.local_voice import LocalVoice


def _audio_clip(av, *, muxer="ogg", codec="libopus", sample_format="s16", seconds=1):
    output = BytesIO()
    sample_rate = 48_000
    frame_samples = 960
    resampler = av.AudioResampler(format=sample_format)
    with av.open(output, "w", format=muxer) as container:
        stream = container.add_stream(codec, rate=sample_rate)
        stream.layout = "stereo"
        stream.codec_context.format = sample_format
        for first_sample in range(0, sample_rate * seconds, frame_samples):
            frame = av.AudioFrame(format="s16", layout="stereo", samples=frame_samples)
            frame.sample_rate = sample_rate
            frame.pts = first_sample
            frame.planes[0].update(b"\xc4\x09\x18\xfc" * frame_samples)
            for converted in resampler.resample(frame):
                for packet in stream.encode(converted):
                    container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return output.getvalue()


def test_local_voice_resamples_opus_and_reuses_the_model(monkeypatch, tmp_path):
    av = pytest.importorskip("av")
    models = []
    recordings = []

    def load_model(path):
        assert path == str(tmp_path)
        model = object()
        models.append(model)
        return model

    class Recognizer:
        def __init__(self, model, sample_rate):
            assert model is models[0]
            assert sample_rate == 16_000
            self.pcm = bytearray()
            recordings.append(self.pcm)
            self.completed = False

        def AcceptWaveform(self, samples):
            self.pcm.extend(samples)
            if len(self.pcm) >= 16_000 and not self.completed:
                self.completed = True
                return True
            return False

        def Result(self):
            return '{"text":"какие пары"}'

        def FinalResult(self):
            return '{"text":" завтра "}'

    monkeypatch.setitem(
        sys.modules,
        "vosk",
        SimpleNamespace(Model=load_model, KaldiRecognizer=Recognizer, SetLogLevel=lambda _: None),
    )
    voice = LocalVoice(tmp_path)
    clip = _audio_clip(av)

    assert voice.recognize(clip) == "какие пары завтра"
    assert voice.recognize(clip) == "какие пары завтра"
    assert len(models) == 1
    assert [len(pcm) for pcm in recordings] == [32_000, 32_000]
    assert any(recordings[0])


def test_local_voice_rejects_more_than_thirty_seconds(monkeypatch, tmp_path):
    av = pytest.importorskip("av")

    def load_model(path):
        pytest.fail("An oversized voice message should be rejected before model inference")

    monkeypatch.setitem(sys.modules, "vosk", SimpleNamespace(Model=load_model))

    assert LocalVoice(tmp_path).recognize(_audio_clip(av, seconds=31)) is None


@pytest.mark.parametrize(
    ("muxer", "codec", "sample_format", "seconds"),
    [
        ("adts", "aac", "fltp", 1),
        ("mp4", "aac", "fltp", 1),
        ("mp3", "libmp3lame", "s16p", 1),
        ("wav", "pcm_s16le", "s16", 6),
    ],
)
def test_local_voice_decodes_other_common_voice_formats(
    monkeypatch, tmp_path, muxer, codec, sample_format, seconds
):
    av = pytest.importorskip("av")

    class Recognizer:
        def __init__(self, model, sample_rate):
            self.has_samples = False

        def AcceptWaveform(self, samples):
            self.has_samples |= any(samples)
            return False

        def FinalResult(self):
            return '{"text":"завтра"}' if self.has_samples else '{"text":""}'

    monkeypatch.setitem(
        sys.modules,
        "vosk",
        SimpleNamespace(
            Model=lambda _: object(), KaldiRecognizer=Recognizer, SetLogLevel=lambda _: None
        ),
    )
    clip = _audio_clip(av, muxer=muxer, codec=codec, sample_format=sample_format, seconds=seconds)

    assert LocalVoice(tmp_path).recognize(clip) == "завтра"


def test_local_voice_rejects_an_unlisted_container(monkeypatch, tmp_path):
    av = pytest.importorskip("av")

    def load_model(path):
        pytest.fail("An unsupported container should be rejected before model inference")

    monkeypatch.setitem(
        sys.modules, "vosk", SimpleNamespace(Model=load_model, SetLogLevel=lambda _: None)
    )

    clip = _audio_clip(av, muxer="flac", codec="flac")

    assert LocalVoice(tmp_path).recognize(clip) is None


@pytest.mark.parametrize("clip", [b"", b"OggS invalid", b"OggS" + b"\0" * 4_000_000])
def test_local_voice_returns_no_text_for_invalid_audio(tmp_path, clip):
    assert LocalVoice(tmp_path).recognize(clip) is None


def test_local_voice_returns_no_text_when_the_model_fails_to_load(monkeypatch, tmp_path):
    av = pytest.importorskip("av")

    def load_model(path):
        raise Exception("Failed to create a model")

    monkeypatch.setitem(
        sys.modules, "vosk", SimpleNamespace(Model=load_model, SetLogLevel=lambda _: None)
    )

    assert LocalVoice(tmp_path).recognize(_audio_clip(av)) is None
