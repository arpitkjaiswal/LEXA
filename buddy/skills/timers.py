"""UTC-backed timers and offset-aware reminders, delivered while BUDDY is running."""

import time
from datetime import UTC, datetime

from buddy.core.errors import BuddyError
from buddy.core.tools import Tool, schema, string


def register(registry):
    store = registry.store

    async def timer(args):
        due = time.time() + args["seconds"]
        return {
            "id": store.add_reminder(args["label"], due),
            "due": datetime.fromtimestamp(due, UTC).isoformat(),
            "delivery": "BUDDY must be running; overdue reminders appear after restart or wake.",
        }

    async def reminder(args):
        try:
            at = datetime.fromisoformat(args["at"])
        except ValueError:
            raise BuddyError(
                "Use an ISO datetime with a UTC offset, such as 2026-11-01T18:00:00+05:30."
            ) from None
        if at.tzinfo is None or at.utcoffset() is None:
            raise BuddyError(
                "The reminder needs an explicit UTC offset to avoid timezone ambiguity."
            )
        due = at.timestamp()
        if not time.time() < due <= time.time() + 366 * 86400:
            raise BuddyError("Choose a future reminder within the next year.")
        return {
            "id": store.add_reminder(args["label"], due),
            "due": at.isoformat(),
            "delivery": "BUDDY must be running. Missed alerts appear on next start.",
        }

    async def listing(args):
        rows = store.execute(
            "SELECT id, label, due FROM reminders WHERE status='pending' ORDER BY due"
        )
        return {
            "reminders": [
                {**r, "due": datetime.fromtimestamp(r["due"], UTC).isoformat()} for r in rows
            ]
        }

    async def cancel(args):
        rows = store.execute(
            "SELECT id FROM reminders WHERE id=? AND status='pending'", (args["id"],)
        )
        if not rows:
            raise BuddyError("No pending reminder has that ID.")
        store.execute("UPDATE reminders SET status='cancelled' WHERE id=?", (args["id"],))
        return {"cancelled": args["id"]}

    registry.add(
        Tool(
            "set_timer",
            "Set a durable local timer for the requested duration.",
            schema(
                {
                    "seconds": {"type": "integer", "minimum": 1, "maximum": 31622400},
                    "label": string(200),
                },
                ["seconds", "label"],
            ),
            timer,
        )
    )
    registry.add(
        Tool(
            "set_reminder",
            "Schedule a local reminder at an ISO datetime WITH UTC offset. Read get_time first.",
            schema({"at": string(80), "label": string(200)}, ["at", "label"]),
            reminder,
        )
    )
    registry.add(
        Tool("list_reminders", "List pending local timers/reminders and IDs.", schema({}), listing)
    )
    registry.add(
        Tool(
            "cancel_reminder",
            "Cancel a timer/reminder specified by the user.",
            schema({"id": string(12, pattern="^[a-f0-9]{12}$")}, ["id"]),
            cancel,
        )
    )
