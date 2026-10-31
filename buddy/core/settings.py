"""Atomic settings writes. Credentials remain in a separate, owner-readable .env."""

import os
import tempfile
from dataclasses import asdict
from pathlib import Path

import yaml
from dotenv import dotenv_values, set_key

from buddy.core.config import Config, validate
from buddy.core.errors import ConfigurationError


def save_settings(config: Config, path: Path) -> None:
    validate(config)
    raw = {
        name: asdict(getattr(config, name))
        for name in (
            "pet",
            "brain",
            "audio",
            "stt",
            "tts",
            "logging",
            "wake",
            "skills",
            "memory",
            "ui",
        )
    }
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as output:
            temporary = Path(output.name)
            yaml.safe_dump(raw, output, sort_keys=False, allow_unicode=True)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except OSError:
        raise ConfigurationError(
            "Cannot save settings. Check the configuration file permissions."
        ) from None
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def save_api_key(path: Path, provider: str, value: str) -> None:
    if not value:
        return
    variable = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}.get(provider)
    if not variable or len(value) > 4096 or any(c in value for c in "\r\n\0"):
        raise ConfigurationError("Choose a cloud provider and supply a single-line API key.")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
        set_key(str(path), variable, value, quote_mode="always")
        os.chmod(path, 0o600)
    except OSError:
        raise ConfigurationError("Cannot save the API key to the selected .env file.") from None


def sync_env_overrides(config: Config, path: Path) -> None:
    """Keep pre-existing .env overrides aligned with choices made in the settings editor."""
    if not path.is_file():
        return
    existing = dotenv_values(path, interpolate=False)
    values = {
        "BUDDY_PROVIDER": config.brain.provider,
        "BUDDY_MODEL": config.brain.model,
        "BUDDY_USER_NAME": config.pet.user_name,
        "BUDDY_TTS_BACKEND": config.tts.backend,
        "OLLAMA_BASE_URL": config.brain.ollama_base_url,
    }
    try:
        for name, value in values.items():
            if name in existing:
                set_key(str(path), name, value, quote_mode="always")
        os.chmod(path, 0o600)
    except OSError:
        raise ConfigurationError("Cannot update the existing .env overrides.") from None
