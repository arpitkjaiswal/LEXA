import plistlib
from dataclasses import replace
from types import SimpleNamespace

from buddy.core.config import load_config
from buddy.core.settings import save_api_key, save_settings, sync_env_overrides
from buddy.core.startup import startup


def test_settings_roundtrip_keeps_keys_out_of_yaml_and_aligns_existing_overrides(config, tmp_path):
    path, env_path = tmp_path / "config.yaml", tmp_path / ".env"
    env_path.write_text(
        "BUDDY_MODEL=old-model\nBUDDY_PROVIDER=anthropic\nANTHROPIC_API_KEY=old-key\n"
    )
    config = replace(config, brain=replace(config.brain, model="new-model"))
    save_settings(config, path)
    sync_env_overrides(config, env_path)
    save_api_key(env_path, "anthropic", "new-test-key")
    loaded = load_config(path, env_path)
    assert loaded.brain.model == "new-model"
    assert loaded.secrets.anthropic_api_key == "new-test-key"
    assert "new-test-key" not in path.read_text()
    assert "not-a-real-key" not in path.read_text()
    assert env_path.stat().st_mode & 0o777 == 0o600
    assert path.stat().st_mode & 0o777 == 0o600


def test_login_startup_is_explicit_preserves_venv_path_and_uninstalls(
    config, tmp_path, monkeypatch
):
    from buddy.core import startup as module

    home = tmp_path / "home"
    monkeypatch.setattr(module.Path, "home", lambda: home)
    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.setattr(module.sys, "executable", str(tmp_path / ".venv/bin/python"))
    monkeypatch.setattr(module, "require_apple_silicon", lambda: None)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", run)
    path = tmp_path / "config.yaml"
    save_settings(config, path)
    assert not (home / "Library/LaunchAgents").exists()
    assert "will open at login" in startup("install", path, tmp_path / ".env")
    agent = home / "Library/LaunchAgents/io.lexa.buddy.plist"
    payload = plistlib.loads(agent.read_bytes())
    assert payload["ProgramArguments"][0] == str(tmp_path / ".venv/bin/python")
    assert payload["KeepAlive"] is False
    assert "API_KEY" not in agent.read_text()
    assert "removed" in startup("uninstall", path, tmp_path / ".env")
    assert not agent.exists()
    assert calls[0][0] == "/bin/launchctl"
