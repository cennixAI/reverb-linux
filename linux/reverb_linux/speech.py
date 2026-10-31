"""Offline speech recognition: the bundled Parakeet model on the CPU. No network client."""
import json
import os
import threading

from .text import resource_root


class Speech:
    def __init__(self):
        import numpy as np
        import sherpa_onnx
        self.np = np
        spec = json.loads((resource_root() / "models.json").read_text())["asr"]
        model = resource_root() / "models" / spec["directory"]
        if not all((model / name).exists() for name in spec["required"]):
            raise ValueError("The bundled speech model is missing. Reinstall Reverb.")
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(model / "encoder.int8.onnx"), decoder=str(model / "decoder.int8.onnx"),
            joiner=str(model / "joiner.int8.onnx"), tokens=str(model / "tokens.txt"),
            num_threads=min(4, os.cpu_count() or 2), model_type="nemo_transducer", provider="cpu")

    def transcribe(self, samples, sample_rate):
        # Taps shorter than the Mac's 0.35 s threshold are not speech.
        if len(samples) <= sample_rate * 0.35:
            return ""
        stream = self.recognizer.create_stream()
        # sherpa-onnx resamples to the model's 16 kHz itself.
        stream.accept_waveform(sample_rate, self.np.asarray(samples, dtype=self.np.float32))
        self.recognizer.decode_stream(stream)
        return stream.result.text.strip()


def read_wav(path):
    """16-bit PCM WAV as mono float samples, for command-line checks."""
    import wave
    import numpy as np
    with wave.open(str(path), "rb") as source:
        if source.getsampwidth() != 2:
            raise ValueError("Use a 16-bit PCM WAV file")
        rate, channels = source.getframerate(), source.getnchannels()
        data = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float32) / 32768
    return data.reshape(-1, channels).mean(axis=1), rate


class Recorder:
    MAX_SECONDS = 120

    def __init__(self):
        self.stream = None
        self.blocks = []
        self.frames = 0
        self.rate = 16000
        self.error = ""
        self.lock = threading.Lock()

    def start(self):
        import sounddevice as sd
        self.rate = int(sd.query_devices(kind="input")["default_samplerate"])
        with self.lock:
            self.blocks, self.frames, self.error = [], 0, ""

        def receive(data, frames, time_info, status):
            with self.lock:
                if status:
                    self.error = str(status)
                if self.frames + frames <= self.rate * self.MAX_SECONDS:
                    self.blocks.append(data[:, 0].copy())
                    self.frames += frames
        self.stream = sd.InputStream(samplerate=self.rate, channels=1, dtype="float32", callback=receive)
        try:
            self.stream.start()
        except BaseException:
            self.stream.close()
            self.stream = None
            raise

    def stop(self):
        """Close the microphone and return what was heard. Recordings live only in memory."""
        import numpy as np
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        with self.lock:
            blocks, self.blocks = self.blocks, []
            error = self.error
        # Overflow warnings only mean a dropped block; the rest of the recording is still usable.
        if error and not blocks:
            raise ValueError("Microphone recording error: " + error)
        return (np.concatenate(blocks) if blocks else np.empty(0, dtype=np.float32)), self.rate
