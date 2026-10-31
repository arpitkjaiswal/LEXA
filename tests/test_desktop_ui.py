import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_native_qt_pet_chat_settings_confirmation_and_shutdown(tmp_path):
    pytest.importorskip("PySide6")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "tests/ui_smoke.py"), str(tmp_path)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": str(root)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "desktop smoke OK" in result.stdout
    assert (tmp_path / "pet-states.png").stat().st_size > 5000
