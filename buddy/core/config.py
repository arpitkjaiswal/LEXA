"""Load one explicit YAML and .env pair; never search parent directories for secrets."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urlparse

import yaml
from dotenv import dotenv_values

from buddy.core.errors import ConfigurationError


@dataclass(frozen=True)
class PetConfig:
    name: str = "BUDDY"
    user_name: str = "friend"
    personality: str = "Casual, warm and lightly funny. Use 1-3 short sentences by default."


@dataclass(frozen=True)
class BrainConfig:
    provider: str = "anthropic"
    model: str = ""
    max_output_tokens: int = 512
    timeout_seconds: float = 45
    history_turns: int = 10
    max_input_chars: int = 6000
    ollama_base_url: str = "http://127.0.0.1:11434"


@dataclass(frozen=True)
class AudioConfig:
    device: int | str | None = None
    sample_rate: int = 16000
    max_record_seconds: float = 25
    min_record_seconds: float = 0.25
    silence_rms: float = 0.003
    hotkey: str = "<ctrl>+<alt>+<space>"


@dataclass(frozen=True)
class STTConfig:
    model: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str | None = None
    local_files_only: bool = False


@dataclass(frozen=True)
class TTSConfig:
    backend: str = "edge"
    voice: str = "en-IN-NeerjaNeural"
    rate: str = "+0%"
    local_voice: str = ""
    local_rate: int = 180
    fallback: list[str] = field(default_factory=lambda: ["pyttsx3", "say"])
    timeout_seconds: float = 45
    piper_model: str = ""
    piper_sample_rate: int = 22050


@dataclass(frozen=True)
class LogConfig:
    enabled: bool = True
    max_bytes: int = 1_000_000
    backups: int = 3


@dataclass(frozen=True)
class WakeConfig:
    model: str = "hey_jarvis"
    framework: str = "auto"
    threshold: float = 0.5
    consecutive_frames: int = 2
    silence_seconds: float = 1.2


@dataclass(frozen=True)
class SkillsConfig:
    enabled: list[str] = field(
        default_factory=lambda: [
            "apps",
            "web",
            "system",
            "music",
            "timers",
            "notes",
            "memory",
            "weather",
            "screenshot",
        ]
    )
    confirmation_seconds: int = 60
    apps: dict[str, str] = field(
        default_factory=lambda: {
            "vscode": "com.microsoft.VSCode",
            "safari": "com.apple.Safari",
            "music": "com.apple.Music",
            "spotify": "com.spotify.client",
            "calculator": "com.apple.calculator",
            "notes": "com.apple.Notes",
        }
    )
    web_domains: list[str] = field(
        default_factory=lambda: ["youtube.com", "google.com", "github.com", "wikipedia.org"]
    )


@dataclass(frozen=True)
class MemoryConfig:
    enabled: bool = True
    save_history: bool = False
    history_turns: int = 50
    timezone: str = ""  # empty uses the system zone; reminder timestamps require an offset


@dataclass(frozen=True)
class UIConfig:
    scale: float = 1.0
    always_on_top: bool = True
    reduced_motion: bool = False


@dataclass(frozen=True)
class Secrets:
    anthropic_api_key: str = field(default="", repr=False)
    openai_api_key: str = field(default="", repr=False)


def default_data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "BUDDY"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "BUDDY"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "buddy"


@dataclass(frozen=True)
class Config:
    pet: PetConfig = field(default_factory=PetConfig)
    brain: BrainConfig = field(default_factory=BrainConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    logging: LogConfig = field(default_factory=LogConfig)
    wake: WakeConfig = field(default_factory=WakeConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    secrets: Secrets = field(default_factory=Secrets, repr=False)
    data_dir: Path = field(default_factory=default_data_dir)


T = TypeVar("T")


def _section(cls: type[T], value: Any, name: str) -> T:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ConfigurationError(f"config.yaml: {name} must be a mapping.")
    allowed = {f.name for f in fields(cls)}  # type: ignore[arg-type]
    if set(value) - allowed:
        raise ConfigurationError(f"config.yaml: unknown setting in {name}.")
    try:
        return cls(**value)
    except TypeError:
        raise ConfigurationError(f"config.yaml: invalid {name} settings.") from None


def _number(value: Any, name: str, low: float, high: float, *, integer: bool = False) -> None:
    valid_type = type(value) is int if integer else type(value) in (float, int)
    if not valid_type or not low <= value <= high:
        raise ConfigurationError(
            f"{name} must be {'an integer' if integer else 'a number'} between {low} and {high}."
        )


def validate(config: Config) -> None:
    for section_name in ("pet", "brain", "audio", "stt", "tts", "wake", "memory", "ui"):
        section = getattr(config, section_name)
        for item in fields(section):
            value = getattr(section, item.name)
            # Dataclass defaults provide the scalar type contract.
            default = getattr(type(section)(), item.name)
            if isinstance(default, str) and not isinstance(value, str):
                raise ConfigurationError(f"{section_name}.{item.name} must be a string.")
    if config.brain.provider not in {"anthropic", "openai", "ollama"}:
        raise ConfigurationError("brain.provider must be anthropic, openai or ollama.")
    if not config.pet.name.strip() or not config.pet.user_name.strip():
        raise ConfigurationError("pet.name and pet.user_name cannot be blank.")
    if not isinstance(config.tts.fallback, list) or any(
        not isinstance(backend, str) or backend not in {"pyttsx3", "say", "piper"}
        for backend in config.tts.fallback
    ):
        raise ConfigurationError("tts.fallback must contain local backends: pyttsx3, say or piper.")
    if config.tts.backend not in {"edge", "pyttsx3", "say", "piper", "none"}:
        raise ConfigurationError("tts.backend must be edge, pyttsx3, say, piper or none.")
    if config.audio.device is not None and type(config.audio.device) not in (str, int):
        raise ConfigurationError("audio.device must be an index, device name or null.")
    if config.stt.language is not None and not isinstance(config.stt.language, str):
        raise ConfigurationError("stt.language must be a language code or null.")
    if type(config.stt.local_files_only) is not bool or type(config.logging.enabled) is not bool:
        raise ConfigurationError("local_files_only and logging.enabled must be true or false.")
    _number(config.brain.history_turns, "brain.history_turns", 1, 100, integer=True)
    _number(config.brain.max_input_chars, "brain.max_input_chars", 1, 100_000, integer=True)
    _number(config.brain.max_output_tokens, "brain.max_output_tokens", 64, 8192, integer=True)
    _number(config.brain.timeout_seconds, "brain.timeout_seconds", 1, 300)
    _number(config.audio.sample_rate, "audio.sample_rate", 8000, 192000, integer=True)
    _number(config.audio.max_record_seconds, "audio.max_record_seconds", 1, 120)
    _number(config.audio.min_record_seconds, "audio.min_record_seconds", 0.05, 5)
    if config.audio.min_record_seconds >= config.audio.max_record_seconds:
        raise ConfigurationError("audio.min_record_seconds must be below max_record_seconds.")
    _number(config.audio.silence_rms, "audio.silence_rms", 0, 1)
    _number(config.tts.local_rate, "tts.local_rate", 50, 400, integer=True)
    _number(config.tts.timeout_seconds, "tts.timeout_seconds", 1, 180)
    _number(config.tts.piper_sample_rate, "tts.piper_sample_rate", 8000, 48000, integer=True)
    _number(config.logging.max_bytes, "logging.max_bytes", 1024, 50_000_000, integer=True)
    _number(config.logging.backups, "logging.backups", 0, 10, integer=True)
    validate_extensions(config)
    endpoint = urlparse(config.brain.ollama_base_url)
    if (
        endpoint.scheme not in {"http", "https"}
        or not endpoint.hostname
        or endpoint.username
        or endpoint.password
        or endpoint.query
        or endpoint.fragment
    ):
        raise ConfigurationError("OLLAMA_BASE_URL must be an HTTP(S) URL without credentials.")


def load_config(path: Path | None = None, env_file: Path | None = None) -> Config:
    """Existing environment variables override .env; .env overrides YAML."""
    config_path = path or Path.cwd() / "config.yaml"
    if path is not None and not path.is_file():
        raise ConfigurationError("The supplied --config file does not exist.")
    try:
        raw = (
            yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
        )
        raw = {} if raw is None else raw
        if not isinstance(raw, dict):
            raise ConfigurationError("config.yaml must contain a mapping.")
        if set(raw) - {
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
        }:
            raise ConfigurationError("config.yaml contains an unknown section.")
        dotenv_path = env_file or config_path.parent / ".env"
        if env_file is not None and not env_file.is_file():
            raise ConfigurationError("The supplied --env-file does not exist.")
        env = {**dotenv_values(dotenv_path, interpolate=False), **os.environ}
    except (OSError, yaml.YAMLError):
        raise ConfigurationError(
            "Cannot read configuration; check file permissions and YAML syntax."
        ) from None

    sections: dict[str, Any] = {}
    for name in ("pet", "brain", "tts"):
        value = raw.get(name)
        if value is not None and not isinstance(value, dict):
            raise ConfigurationError(f"config.yaml: {name} must be a mapping.")
        sections[name] = dict(value or {})
    overrides = {
        "BUDDY_PROVIDER": ("brain", "provider"),
        "BUDDY_MODEL": ("brain", "model"),
        "OLLAMA_BASE_URL": ("brain", "ollama_base_url"),
        "BUDDY_USER_NAME": ("pet", "user_name"),
        "BUDDY_TTS_BACKEND": ("tts", "backend"),
    }
    for variable, (section, name) in overrides.items():
        if env.get(variable):
            sections[section][name] = env[variable]
    config = Config(
        pet=_section(PetConfig, sections["pet"], "pet"),
        brain=_section(BrainConfig, sections["brain"], "brain"),
        audio=_section(AudioConfig, raw.get("audio"), "audio"),
        stt=_section(STTConfig, raw.get("stt"), "stt"),
        tts=_section(TTSConfig, sections["tts"], "tts"),
        logging=_section(LogConfig, raw.get("logging"), "logging"),
        wake=_section(WakeConfig, raw.get("wake"), "wake"),
        skills=_section(SkillsConfig, raw.get("skills"), "skills"),
        memory=_section(MemoryConfig, raw.get("memory"), "memory"),
        ui=_section(UIConfig, raw.get("ui"), "ui"),
        secrets=Secrets(env.get("ANTHROPIC_API_KEY") or "", env.get("OPENAI_API_KEY") or ""),
        data_dir=Path(env.get("BUDDY_DATA_DIR") or default_data_dir()).expanduser().resolve(),
    )
    validate(config)
    return config


def validate_extensions(config: Config) -> None:
    import re
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    if config.wake.framework not in {"auto", "onnx", "tflite"}:
        raise ConfigurationError("wake.framework must be auto, onnx or tflite.")
    if not config.wake.model.strip():
        raise ConfigurationError("wake.model must identify a trained model.")
    _number(config.wake.threshold, "wake.threshold", 0.01, 1)
    _number(config.wake.consecutive_frames, "wake.consecutive_frames", 1, 10, integer=True)
    _number(config.wake.silence_seconds, "wake.silence_seconds", 0.4, 5)
    _number(
        config.skills.confirmation_seconds, "skills.confirmation_seconds", 10, 300, integer=True
    )
    _number(config.memory.history_turns, "memory.history_turns", 1, 1000, integer=True)
    _number(config.ui.scale, "ui.scale", 0.6, 2)
    for value in (
        config.memory.enabled,
        config.memory.save_history,
        config.ui.always_on_top,
        config.ui.reduced_motion,
    ):
        if type(value) is not bool:
            raise ConfigurationError("Memory and UI switches must be true or false.")
    known = {"apps", "web", "system", "music", "timers", "notes", "memory", "weather", "screenshot"}
    if not isinstance(config.skills.enabled, list) or any(
        not isinstance(x, str) or x not in known for x in config.skills.enabled
    ):
        raise ConfigurationError("skills.enabled must contain built-in skill module names.")
    if (
        not isinstance(config.skills.apps, dict)
        or len(config.skills.apps) > 100
        or any(
            not isinstance(k, str)
            or not re.fullmatch(r"[a-z0-9_ -]{1,40}", k)
            or not isinstance(v, str)
            or not re.fullmatch(r"[A-Za-z0-9.-]{3,150}", v)
            for k, v in config.skills.apps.items()
        )
    ):
        raise ConfigurationError("skills.apps must map short aliases to macOS bundle identifiers.")
    if not isinstance(config.skills.web_domains, list) or any(
        not isinstance(v, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,250})\.[a-z]{2,63}", v)
        for v in config.skills.web_domains
    ):
        raise ConfigurationError("skills.web_domains must contain domain names only.")
    if config.memory.timezone:
        try:
            ZoneInfo(config.memory.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ConfigurationError("memory.timezone must be an IANA timezone.") from None
