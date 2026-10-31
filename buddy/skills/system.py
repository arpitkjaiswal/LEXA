"""Read the clock and change Mac volume using fixed AppleScript templates."""

from datetime import datetime
from zoneinfo import ZoneInfo

from buddy.core.tools import Tool, schema
from buddy.skills.common import mac_only, process


def register(registry):
    async def clock(args):
        zone = registry.config.memory.timezone
        now = datetime.now(ZoneInfo(zone)) if zone else datetime.now().astimezone()
        return {"datetime": now.isoformat(), "timezone": zone or str(now.tzinfo)}

    async def volume(args):
        mac_only()
        # Only validated integers enter this fixed script; no arbitrary AppleScript tool.
        level = args["percent"]
        await process(["/usr/bin/osascript", "-e", f"set volume output volume {level}"])
        actual = await process(
            ["/usr/bin/osascript", "-e", "output volume of (get volume settings)"]
        )
        return {"volume_percent": int(actual.strip())}

    registry.add(
        Tool("get_time", "Read the current local date, time and UTC offset.", schema({}), clock)
    )
    registry.add(
        Tool(
            "set_volume",
            "Set the Mac system output volume, between 0 and 100 percent.",
            schema({"percent": {"type": "integer", "minimum": 0, "maximum": 100}}, ["percent"]),
            volume,
        )
    )
