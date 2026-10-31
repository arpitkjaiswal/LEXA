"""Notes stay in BUDDY's own database; no access to arbitrary user files."""

from buddy.core.errors import BuddyError
from buddy.core.tools import Tool, schema, string


def register(registry):
    store = registry.store

    async def create(args):
        return {"id": store.add_note(args["title"], args["body"]), "saved": True}

    async def listing(args):
        return {
            "notes": store.execute(
                "SELECT id, title, created FROM notes ORDER BY created DESC LIMIT 50"
            )
        }

    async def read(args):
        rows = store.execute("SELECT id, title, body FROM notes WHERE id=?", (args["id"],))
        if not rows:
            raise BuddyError("That note was not found.")
        return rows[0]

    async def delete(args):
        await read(args)
        store.execute("DELETE FROM notes WHERE id=?", (args["id"],))
        return {"deleted": args["id"]}

    identifier = schema({"id": string(12, pattern="^[a-f0-9]{12}$")}, ["id"])
    registry.add(
        Tool(
            "create_note",
            "Save a note when the user asks; returns its local ID.",
            schema({"title": string(120), "body": string(6000)}, ["title", "body"]),
            create,
        )
    )
    registry.add(
        Tool("list_notes", "List the 50 newest local note titles and IDs.", schema({}), listing)
    )
    registry.add(Tool("read_note", "Read a local note by its exact ID.", identifier, read))
    registry.add(
        Tool("delete_note", "Delete one local note by its ID.", identifier, delete, confirm=True)
    )
