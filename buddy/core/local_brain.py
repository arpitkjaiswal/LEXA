"""A small, explicit command vocabulary for first launch without an AI provider."""

from __future__ import annotations

import json
import re

from buddy.core.tools import ToolRegistry

HELP = (
    "Local mode is ready; no AI provider is configured. Try: what time is it, "
    "set a timer for 5 minutes, list reminders, open calculator, open YouTube, "
    "search for Python tutorials, note revision: finish chapter two, list notes, "
    "remember style: short answers, or take a screenshot. "
    "Open Configure AI for conversation, or enable Demo to try canned replies."
)


def parse_command(text: str, apps: dict[str, str]) -> tuple[str, dict] | None:
    """Match entire commands only; never interpret quoted text or guess missing values."""
    command = text.strip().rstrip(".!?")
    lower = command.casefold()
    fixed = {
        "what time is it": "get_time",
        "time": "get_time",
        "date": "get_time",
        "list reminders": "list_reminders",
        "list timers": "list_reminders",
        "list notes": "list_notes",
        "what do you remember": "recall_memory",
        "take a screenshot": "take_screenshot",
    }
    if lower in fixed:
        return fixed[lower], {}
    match = re.fullmatch(r"set (?:a )?timer for (\d{1,8}) (seconds?|minutes?|hours?)", lower)
    if match:
        count, unit = match.groups()
        seconds = int(count) * {"second": 1, "minute": 60, "hour": 3600}[unit.rstrip("s")]
        return "set_timer", {"seconds": seconds, "label": f"Timer: {count} {unit}"}
    match = re.fullmatch(r"set volume to (\d{1,3})(?: percent|%)?", lower)
    if match:
        return "set_volume", {"percent": int(match[1])}
    match = re.fullmatch(r"open (.+)", lower)
    if match:
        target = {"vs code": "vscode"}.get(match[1], match[1])
        if target in apps:
            return "open_app", {"app": target}
        sites = {
            "youtube": "youtube.com",
            "google": "google.com",
            "github": "github.com",
            "wikipedia": "wikipedia.org",
        }
        if target in sites:
            return "open_url", {"url": "https://" + sites[target]}
    match = re.fullmatch(r"search for (.+)", command, re.IGNORECASE)
    if match:
        return "web_search", {"query": match[1]}
    match = re.fullmatch(r"note ([^:\n]+):\s*(.+)", text.strip(), re.IGNORECASE | re.DOTALL)
    if match:
        return "create_note", {"title": match[1].strip(), "body": match[2].strip()}
    match = re.fullmatch(r"remember ([^:\n]+):\s*(.+)", text.strip(), re.IGNORECASE | re.DOTALL)
    if match:
        return "remember_fact", {"key": match[1].strip(), "value": match[2].strip()}
    match = re.fullmatch(r"(read note|delete note|cancel reminder) ([a-f0-9]{12})", lower)
    if match:
        return match[1].replace(" ", "_"), {"id": match[2]}
    return None


class LocalBrain:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def stream(self, messages, system):
        parsed = parse_command(messages[-1]["content"], self.registry.config.skills.apps)
        if parsed is None:
            yield HELP
            return
        name, arguments = parsed
        outcome = await self.registry.invoke(name, arguments)
        if outcome.get("pending"):
            yield self.registry.confirmation_text()
        elif not outcome["ok"]:
            yield outcome["error"]
        else:
            # Values come only from a completed, schema-validated tool result.
            yield "Local result:\n" + json.dumps(outcome["result"], ensure_ascii=False, indent=2)

    async def close(self):
        pass
