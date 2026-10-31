"""Actionable public errors, without raw provider responses or secret values."""


class BuddyError(Exception):
    """Expected failure that is safe to display in the terminal."""


class ConfigurationError(BuddyError):
    pass


class AudioError(BuddyError):
    pass


class TranscriptionError(BuddyError):
    pass


class BrainError(BuddyError):
    pass


class SpeechError(BuddyError):
    pass


class SpeechInterruptedError(SpeechError):
    """Playback started; do not repeat the phrase through a fallback voice."""
