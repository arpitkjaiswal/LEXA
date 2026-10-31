"""A screenshot is captured only after an explicit request and specific confirmation."""

import os
import uuid
from datetime import datetime

from buddy.core.tools import Tool, schema
from buddy.skills.common import mac_only, process


def register(registry):
    async def capture(args):
        mac_only()
        directory = registry.config.data_dir / "screenshots"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / (
            datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8] + ".png"
        )
        try:
            await process(["/usr/sbin/screencapture", "-x", str(path)])
            if not path.is_file() or path.stat().st_size < 8:
                from buddy.core.errors import BuddyError

                raise BuddyError("No screenshot was saved. Check Screen Recording permission.")
            os.chmod(path, 0o600)
            return {"saved_path": str(path), "uploaded": False}
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    registry.add(
        Tool(
            "take_screenshot",
            "Save a screenshot locally ONLY when explicitly requested. Never upload it.",
            schema({}),
            capture,
            confirm=True,
        )
    )
