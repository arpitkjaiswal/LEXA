"""Launch only configured macOS bundle identifiers."""

from buddy.core.tools import Tool, schema, string
from buddy.skills.common import mac_only, process


def register(registry):
    allowed = registry.config.skills.apps

    async def run(args):
        mac_only()
        bundle = allowed[args["app"]]
        await process(["/usr/bin/open", "-b", bundle])
        return {"opened": args["app"], "bundle_id": bundle}

    if allowed:
        registry.add(
            Tool(
                "open_app",
                "Open an allowlisted application on this Mac.",
                schema({"app": string(enum=list(allowed))}, ["app"]),
                run,
            )
        )
