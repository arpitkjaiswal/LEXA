"""Explicit saved preferences, inspection and deletion. Never infer facts silently."""

from buddy.core.tools import Tool, schema, string


def register(registry):
    store = registry.store
    if not registry.config.memory.enabled:
        return

    async def remember(args):
        store.remember(args["key"], args["value"])
        return {"saved_key": args["key"]}

    async def recall(args):
        return {"facts": store.facts()}

    async def forget(args):
        store.execute("DELETE FROM facts WHERE key=?", (args["key"],))
        return {"forgotten_key": args["key"]}

    async def clear(args):
        store.execute("DELETE FROM turns")
        return {"deleted": "saved chat history"}

    registry.add(
        Tool(
            "remember_fact",
            "Save a preference ONLY when the user explicitly asks to remember it.",
            schema({"key": string(80), "value": string(1000)}, ["key", "value"]),
            remember,
        )
    )
    registry.add(Tool("recall_memory", "Inspect explicitly saved user facts.", schema({}), recall))
    registry.add(
        Tool(
            "forget_fact",
            "Delete one explicitly saved fact.",
            schema({"key": string(80)}, ["key"]),
            forget,
            confirm=True,
        )
    )
    registry.add(
        Tool(
            "clear_saved_history",
            "Delete all saved conversations from the local database.",
            schema({}),
            clear,
            confirm=True,
        )
    )
