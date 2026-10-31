"""Browser navigation with a domain allowlist; no file, JavaScript or local URLs."""

from urllib.parse import urlencode, urlparse

from buddy.core.errors import BuddyError
from buddy.core.tools import Tool, schema, string
from buddy.skills.common import mac_only, process


def register(registry):
    domains = registry.config.skills.web_domains

    async def open_url(args):
        mac_only()
        url = args["url"]
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
            or any(ord(c) < 32 for c in url)
            or not any(host == d or host.endswith("." + d) for d in domains)
        ):
            raise BuddyError("URL is outside skills.web_domains; use an allowlisted HTTPS website.")
        await process(["/usr/bin/open", url])
        return {"opened_url": url}

    async def search(args):
        url = "https://www.google.com/search?" + urlencode({"q": args["query"]})
        return await open_url({"url": url})

    registry.add(
        Tool(
            "open_url",
            "Open an HTTPS website from the configured domain allowlist.",
            schema({"url": string(2000)}, ["url"]),
            open_url,
        )
    )
    registry.add(
        Tool(
            "web_search",
            "Open a Google search in the browser; does not read its results.",
            schema({"query": string(500)}, ["query"]),
            search,
        )
    )
