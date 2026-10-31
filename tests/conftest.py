from dataclasses import replace

import pytest

from buddy.core.config import Config, Secrets


@pytest.fixture
def config(tmp_path):
    base = Config(data_dir=tmp_path)
    return replace(
        base,
        brain=replace(base.brain, model="test-model"),
        secrets=Secrets("not-a-real-key", "not-a-real-key"),
    )


class AuditDouble:
    def __init__(self):
        self.events = []

    def record(self, event, **metadata):
        self.events.append((event, metadata))


class BrainDouble:
    def __init__(self, chunks=("Hey friend. ", "You have got this!"), failure=None):
        self.chunks = chunks
        self.failure = failure
        self.calls = []
        self.closed = False

    async def stream(self, messages, system):
        self.calls.append((messages, system))
        for chunk in self.chunks:
            yield chunk
        if self.failure:
            raise self.failure

    async def close(self):
        self.closed = True


class SpeakerDouble:
    def __init__(self, failure=None):
        self.phrases = []
        self.failure = failure
        self.stopped = False

    async def speak(self, text):
        self.phrases.append(text)
        if self.failure:
            raise self.failure

    async def stop(self):
        self.stopped = True
