"""Local reminder delivery: UTC persistence, visible alerts, and at-least-once recovery."""

import asyncio
import time

from buddy.core.storage import Store


class Reminders:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def wait_due(self) -> None:
        while True:
            if self.store.due(time.time()):
                return
            await asyncio.sleep(0.5)

    async def deliver(self, assistant, notify=lambda _: None) -> None:
        for item in self.store.due(time.time()):
            late = time.time() - item["due"] > 60
            text = f"{'Overdue reminder' if late else 'Reminder'}: {item['label']}"
            notify(text)
            await assistant.announce(text)
            # A crash between display and this commit can repeat an alert; never silently lose it.
            self.store.acknowledge(item["id"])
