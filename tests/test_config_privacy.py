import json
import os
from dataclasses import replace

import pytest

from buddy.core.audit import AuditLog
from buddy.core.config import load_config
from buddy.core.console import safe_text
from buddy.core.doctor import report
from buddy.core.errors import ConfigurationError


@pytest.fixture(autouse=True)
def clear_config_env(monkeypatch):
    for name in (
        "BUDDY_PROVIDER",
        "BUDDY_MODEL",
        "BUDDY_USER_NAME",
        "BUDDY_TTS_BACKEND",
        "BUDDY_DATA_DIR",
        "OLLAMA_BASE_URL",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_environment_over_dotenv_over_yaml_without_mutating_environment(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("pet:\n  user_name: YAML name\nbrain:\n  model: yaml-model\n")
    (tmp_path / ".env").write_text(
        "BUDDY_USER_NAME=env-file name\nBUDDY_MODEL=dotenv-model\n"
        "ANTHROPIC_API_KEY=private-test-key\n"
    )
    monkeypatch.setenv("BUDDY_MODEL", "environment-model")
    result = load_config(path)
    assert result.pet.user_name == "env-file name"
    assert result.brain.model == "environment-model"
    assert result.secrets.anthropic_api_key == "private-test-key"
    assert "ANTHROPIC_API_KEY" not in os.environ
    assert "private-test-key" not in repr(result)
    assert "private-test-key" not in repr(result.secrets)
    assert "private-test-key" not in "\n".join(report(result))


def test_does_not_search_parent_for_secrets(tmp_path):
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=must-not-load\n")
    child = tmp_path / "child"
    child.mkdir()
    path = child / "config.yaml"
    path.write_text("{}")
    assert load_config(path).secrets.anthropic_api_key == ""


@pytest.mark.parametrize(
    "content",
    [
        "[]",
        "unknown: {}",
        "audio: []",
        "audio: {max_record_seconds: 0}",
        "brain: {history_turns: true}",
        "tts: {fallback: [edge]}",
        "tts: {fallback: [{}]}",
        "audio: {device: false}",
        "pet: {name: 4}",
        "stt: {local_files_only: yesplease}",
        "tts: {local_rate: 0}",
        "brain: {ollama_base_url: 'file:///private'}",
        "brain: {provider: unknown}",
        "logging: {enabled: 'false'}",
        "stt: {language: 42}",
        "secret:\n  key: value",
    ],
)
def test_invalid_configs_are_actionable_without_echoing_contents(tmp_path, content):
    path = tmp_path / "config.yaml"
    path.write_text(content)
    with pytest.raises(ConfigurationError):
        load_config(path)


def test_missing_explicit_configuration_fails(tmp_path):
    with pytest.raises(ConfigurationError):
        load_config(tmp_path / "missing.yaml")


def test_audit_redacts_unknown_fields_and_rotates(config):
    config = replace(config, logging=replace(config.logging, max_bytes=1024, backups=2))
    audit = AuditLog(config)
    for _ in range(40):
        audit.record(
            "reply",
            transcript="private conversation",
            api_key="private-test-key",
            characters=10,
            ok=True,
        )
    audit.close()
    files = list((config.data_dir / "logs").glob("actions.jsonl*"))
    assert 1 <= len(files) <= 3
    for path in files:
        content = path.read_text()
        assert "private conversation" not in content
        assert "private-test-key" not in content
        for line in content.splitlines():
            item = json.loads(line)
            assert item["characters"] == 10
            assert "time" in item


def test_terminal_control_codes_removed():
    assert safe_text("hi\x1b[2J\x00\r\nthere\t!") == "hi[2J\nthere\t!"
