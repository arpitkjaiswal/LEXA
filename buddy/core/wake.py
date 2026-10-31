"""Local openWakeWord detection. Detection is suspended throughout capture and replies."""

from __future__ import annotations

import asyncio
import math
import platform
import sys
import threading
import types
from pathlib import Path

from buddy.core.config import Config
from buddy.core.errors import AudioError


def effective_framework(config: Config) -> str:
    if config.wake.framework != "auto":
        return config.wake.framework
    return "tflite" if sys.platform == "darwin" and platform.machine() == "arm64" else "onnx"


def ensure_tflite_runtime() -> None:
    """openWakeWord 0.6 expects an older import name for the same Interpreter API."""
    try:
        import tflite_runtime.interpreter  # noqa: F401
    except ImportError:
        from ai_edge_litert import interpreter

        # Process-local compatibility only: never modify site-packages or user files.
        package = types.ModuleType("tflite_runtime")
        package.__path__ = []
        package.interpreter = interpreter
        sys.modules["tflite_runtime"] = package
        sys.modules["tflite_runtime.interpreter"] = interpreter


class WakeDetector:
    def __init__(self, config: Config, *, model=None, sounddevice_module=None) -> None:
        self.config = config
        self.model, self.sd = model, sounddevice_module

    async def prepare(self) -> None:
        if self.model is not None:
            return

        def load():
            try:
                framework = effective_framework(self.config)
                if framework == "tflite":
                    ensure_tflite_runtime()
                from openwakeword.model import Model

                directory = self.config.data_dir / "wake"
                suffix = "." + framework
                requested = Path(self.config.wake.model).expanduser()
                if requested.is_file():
                    model_path = requested
                else:
                    candidates = sorted(directory.glob(self.config.wake.model + "_v*" + suffix))
                    if not candidates:
                        raise FileNotFoundError
                    model_path = candidates[-1]
                return Model(
                    wakeword_models=[str(model_path)],
                    inference_framework=framework,
                    melspec_model_path=str(directory / ("melspectrogram" + suffix)),
                    embedding_model_path=str(directory / ("embedding_model" + suffix)),
                )
            except Exception:
                raise AudioError(
                    "Wake detector is unavailable. Install .[wake], run --download-wake-models, "
                    "and select a matching wake.model/framework. Push-to-talk remains available."
                ) from None

        self.model = await asyncio.to_thread(load)

    async def wait(self, stop: threading.Event) -> bool:
        await self.prepare()
        task = asyncio.create_task(asyncio.to_thread(self._wait, stop))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            stop.set()
            try:
                await task
            except AudioError:
                pass
            raise

    def _wait(self, stop: threading.Event) -> bool:
        if stop.is_set():
            return False
        try:
            import numpy as np
            from scipy.signal import resample_poly

            if self.sd is None:
                import sounddevice

                self.sd = sounddevice
            sd = self.sd
            rate = 16000
            try:
                sd.check_input_settings(
                    device=self.config.audio.device, channels=1, dtype="int16", samplerate=rate
                )
            except sd.PortAudioError:
                rate = int(
                    sd.query_devices(self.config.audio.device, "input")["default_samplerate"]
                )
            frames = round(rate * 0.08)
            consecutive = 0
            self.model.reset()
            with sd.RawInputStream(
                samplerate=rate,
                device=self.config.audio.device,
                channels=1,
                dtype="int16",
                blocksize=frames,
            ) as stream:
                while not stop.is_set():
                    data, overflow = stream.read(frames)
                    if overflow:
                        raise AudioError(
                            "Wake audio overflowed. Try a quieter workload or push-to-talk."
                        )
                    samples = np.frombuffer(data, dtype=np.int16)
                    if rate != 16000:
                        divisor = math.gcd(rate, 16000)
                        samples = np.clip(
                            resample_poly(
                                samples.astype(np.float32), 16000 // divisor, rate // divisor
                            ),
                            -32768,
                            32767,
                        ).astype(np.int16)
                    prediction = self.model.predict(samples)
                    score = max((float(v) for v in prediction.values()), default=0)
                    consecutive = consecutive + 1 if score >= self.config.wake.threshold else 0
                    if consecutive >= self.config.wake.consecutive_frames and not stop.is_set():
                        return True
            return False
        except AudioError:
            raise
        except Exception:
            raise AudioError(
                "Cannot listen for a wake word. Check Microphone permission and audio.device."
            ) from None


async def download_models(config: Config) -> None:
    def download():
        try:
            import os
            import tempfile
            from urllib.request import urlopen

            import openwakeword

            custom = Path(config.wake.model).expanduser().is_file()
            if not custom and config.wake.model not in openwakeword.MODELS:
                raise AudioError(
                    "Select a supported built-in wake model or an existing trained model path."
                )
            models = list(openwakeword.FEATURE_MODELS.values())
            if not custom:
                models.append(openwakeword.MODELS[config.wake.model])
            directory = config.data_dir / "wake"
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            for item in models:
                url = item["download_url"].replace(".tflite", "." + effective_framework(config))
                destination = directory / url.rsplit("/", 1)[-1]
                if destination.is_file():
                    continue
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(dir=directory, delete=False) as output:
                        temporary = Path(output.name)
                        with urlopen(url, timeout=30) as response:
                            count = 0
                            while chunk := response.read(65536):
                                count += len(chunk)
                                if count > 100_000_000:
                                    raise AudioError("Wake model exceeded the download size limit.")
                                output.write(chunk)
                    os.replace(temporary, destination)
                finally:
                    if temporary:
                        temporary.unlink(missing_ok=True)
        except AudioError:
            raise
        except Exception:
            raise AudioError(
                "Wake model download failed. Install .[wake] and check the connection."
            ) from None

    await asyncio.to_thread(download)
