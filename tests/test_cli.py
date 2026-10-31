import os
import subprocess
import sys
from pathlib import Path


def invoke(tmp_path, args, input=None):
    environment = os.environ.copy()
    for key in ("BUDDY_PROVIDER", "BUDDY_MODEL", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        environment.pop(key, None)
    environment["BUDDY_DATA_DIR"] = str(tmp_path)
    return subprocess.run(
        [sys.executable, "-m", "buddy", *args],
        input=input,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        cwd=Path(__file__).resolve().parents[1],
    )


def test_demo_cli_without_mic_or_ai_key(tmp_path):
    result = invoke(tmp_path, ["--demo", "--no-tts", "--once", "private-test-chat"])
    assert result.returncode == 0, result.stderr
    assert "DEMO:" in result.stdout and "Demo mode is working" in result.stdout
    assert "[LISTENING]" not in result.stdout
    log = (tmp_path / "logs" / "actions.jsonl").read_text()
    assert "private-test-chat" not in log and "reply_complete" in log


def test_interactive_text_commands_and_eof(tmp_path):
    result = invoke(
        tmp_path, ["--demo", "--text", "--no-tts"], input="/mute\nhello\n/reset\n/unmute\n/quit\n"
    )
    assert result.returncode == 0, result.stderr
    assert "Muted:" in result.stdout and "Session cleared" in result.stdout
    assert "Demo mode is working" in result.stdout


def test_unconfigured_live_provider_has_clear_error_and_nonzero_exit(tmp_path):
    result = invoke(tmp_path, ["--no-tts", "--once", "hello"])
    assert result.returncode == 1
    assert "Set BUDDY_MODEL" in result.stdout
    assert "Traceback" not in result.stderr


def test_doctor_never_requires_audio_or_api(tmp_path):
    result = invoke(tmp_path, ["--doctor"])
    assert result.returncode == 0
    assert "NOT READY" in result.stdout
    assert not (tmp_path / "logs").exists()
