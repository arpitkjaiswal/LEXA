"""Fixed built-in plugin catalog, JSON schemas, and single-use action confirmations."""

from __future__ import annotations

import asyncio
import importlib
import json
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

from buddy.core.config import Config
from buddy.core.errors import BuddyError
from buddy.core.storage import Store


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict
    run: Callable[[dict], Awaitable[dict]]
    confirm: bool = False


@dataclass(frozen=True)
class Pending:
    identifier: str
    tool: str
    arguments: str  # immutable canonical JSON: no mutable object can change the approved action
    expires: float


def schema(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def string(maximum: int = 300, **extra: Any) -> dict:
    return {"type": "string", "minLength": 1, "maxLength": maximum, **extra}


class ToolRegistry:
    def __init__(self, config: Config, audit: Any, store: Store | None = None) -> None:
        self.config, self.audit, self.store = config, audit, store
        self.tools: dict[str, Tool] = {}
        self.pending: Pending | None = None
        self.on_pending: Callable[[Pending], None] = lambda _: None
        self.cleanups: list[Callable[[], Awaitable[None]]] = []
        self._lock = asyncio.Lock()
        # Names are selected from this constant catalog, never from model-generated paths.
        catalog = {
            "apps",
            "web",
            "system",
            "music",
            "timers",
            "notes",
            "memory",
            "weather",
            "screenshot",
        }
        for module in dict.fromkeys(config.skills.enabled):
            if module not in catalog:
                raise BuddyError("Unknown skill module; check the allowlist.")
            if module in {"memory", "notes", "timers"} and store is None:
                continue
            importlib.import_module(f"buddy.skills.{module}").register(self)

    def add(self, tool: Tool) -> None:
        if tool.name in self.tools:
            raise BuddyError("Duplicate tool registration.")
        Draft202012Validator.check_schema(tool.schema)
        self.tools[tool.name] = tool

    def definitions(self) -> list[dict]:
        return [
            {
                "name": t.name,
                "description": t.description
                + (
                    " Requires action-specific user confirmation before execution."
                    if t.confirm
                    else ""
                ),
                "input_schema": t.schema,
            }
            for t in self.tools.values()
        ]

    def cancel(self) -> None:
        self.pending = None

    def confirmation_text(self) -> str:
        item = self.pending
        if not item:
            return "No action is awaiting confirmation."
        return (
            f"Please approve {item.tool} with arguments {item.arguments}. "
            f"Use /confirm {item.identifier} within {self.config.skills.confirmation_seconds} "
            "seconds, or /cancel."
        )

    async def invoke(self, name: str, arguments: Any) -> dict:
        async with self._lock:
            tool = self.tools.get(name)
            if not tool:
                return {"ok": False, "error": "This tool is not allowlisted."}
            try:
                if not isinstance(arguments, dict):
                    return {"ok": False, "error": "Tool arguments must be an object."}
                encoded = json.dumps(arguments, allow_nan=False, sort_keys=True)
                if len(encoded) > 16_000 or not Draft202012Validator(tool.schema).is_valid(
                    arguments
                ):
                    return {"ok": False, "error": "Arguments do not match the tool schema."}
            except (ValueError, TypeError, RecursionError):
                return {"ok": False, "error": "Invalid tool arguments."}
            if self.pending:
                return {"ok": False, "error": "Resolve the pending confirmation first."}
            if tool.confirm:
                self.pending = Pending(
                    secrets.token_hex(4),
                    name,
                    encoded,
                    time.monotonic() + self.config.skills.confirmation_seconds,
                )
                self.audit.record("tool_confirmation", source=name, ok=False)
                self.on_pending(self.pending)
                return {"ok": False, "pending": True, "message": self.confirmation_text()}
            return await self._execute(tool, json.loads(encoded))

    async def confirm(self, identifier: str) -> dict:
        async with self._lock:
            pending, self.pending = (
                self.pending,
                None,
            )  # consumed even on a mismatched/expired token
            if (
                not pending
                or not secrets.compare_digest(pending.identifier, identifier)
                or time.monotonic() > pending.expires
            ):
                return {"ok": False, "error": "Confirmation is missing, expired or does not match."}
            return await self._execute(self.tools[pending.tool], json.loads(pending.arguments))

    async def _execute(self, tool: Tool, arguments: dict) -> dict:
        try:
            async with asyncio.timeout(60):
                result = await tool.run(arguments)
            self.audit.record("tool_result", source=tool.name, ok=True)
            return {"ok": True, "tool": tool.name, "result": result}
        except BuddyError as error:
            self.audit.record("tool_result", source=tool.name, ok=False)
            return {"ok": False, "tool": tool.name, "error": str(error)}
        except Exception as error:
            self.audit.record(
                "tool_result", source=tool.name, error_type=type(error).__name__, ok=False
            )
            return {
                "ok": False,
                "tool": tool.name,
                "error": "The action failed. Check its dependency and macOS permissions.",
            }

    async def close(self) -> None:
        self.cancel()
        for cleanup in self.cleanups:
            await cleanup()
