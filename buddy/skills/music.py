"""One managed mpv player, a private Unix socket, and yt-dlp YouTube search."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
from pathlib import Path

from buddy.core.errors import BuddyError
from buddy.core.tools import Tool, schema, string
from buddy.skills.common import process


class MusicPlayer:
    def __init__(self) -> None:
        self.child: asyncio.subprocess.Process | None = None
        self.directory: tempfile.TemporaryDirectory | None = None
        self.socket: Path | None = None
        self.tracks: list[str] = []
        self.index = 0

    async def start(self) -> None:
        if self.child and self.child.returncode is None:
            return
        await self.close()
        executable = shutil.which("mpv")
        if not executable:
            raise BuddyError("Music needs mpv and yt-dlp: brew install mpv yt-dlp.")
        # Keep the pathname short enough for macOS's 104-byte Unix socket limit.
        self.directory = tempfile.TemporaryDirectory(prefix="buddy-", dir="/tmp")
        self.socket = Path(self.directory.name) / "music.sock"
        self.child = await asyncio.create_subprocess_exec(
            executable,
            "--no-config",
            "--idle=yes",
            "--no-video",
            "--really-quiet",
            "--no-terminal",
            f"--input-ipc-server={self.socket}",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        for _ in range(100):
            if self.socket.exists():
                return
            if self.child.returncode is not None:
                break
            await asyncio.sleep(0.05)
        await self.close()
        raise BuddyError("mpv could not create its music control socket.")

    async def command(self, command: list, *, wait_loaded: bool = False):
        if not self.child or self.child.returncode is not None or self.socket is None:
            raise BuddyError("No managed music player is running. Ask to play music first.")
        reader, writer = await asyncio.open_unix_connection(str(self.socket), limit=1_000_000)
        try:
            async with asyncio.timeout(25):
                writer.write((json.dumps({"command": command, "request_id": 1}) + "\n").encode())
                await writer.drain()
                acknowledged, loaded = False, False
                while line := await reader.readline():
                    result = json.loads(line)
                    if result.get("request_id") == 1:
                        if result.get("error") != "success":
                            raise BuddyError("The music player rejected that action.")
                        acknowledged = True
                        if not wait_loaded:
                            return result.get("data")
                    if result.get("event") == "file-loaded":
                        loaded = True
                    if result.get("event") == "end-file" and result.get("reason") == "error":
                        raise BuddyError(
                            "Music could not load. Check Internet access and update yt-dlp."
                        )
                    if acknowledged and loaded:
                        return None
                raise BuddyError("The music player disconnected.")
        except TimeoutError:
            raise BuddyError(
                "The music player timed out; playback could not be verified."
            ) from None
        finally:
            writer.close()
            await writer.wait_closed()

    async def play(self, query: str) -> dict:
        executable = shutil.which("yt-dlp")
        if not executable:
            raise BuddyError("Music search needs yt-dlp: brew install yt-dlp.")
        raw = await process(
            [
                executable,
                "--ignore-config",
                "--no-warnings",
                "--flat-playlist",
                "--dump-single-json",
                "--",
                "ytsearch5:" + query,
            ],
            deadline_seconds=25,
        )
        entries = json.loads(raw).get("entries", [])
        tracks = [
            "https://www.youtube.com/watch?v=" + e["id"]
            for e in entries
            if isinstance(e, dict)
            and isinstance(e.get("id"), str)
            and re.fullmatch(r"[A-Za-z0-9_-]{11}", e["id"])
        ]
        if not tracks:
            raise BuddyError("No playable music results found.")
        await self.start()
        await self.command(["loadfile", tracks[0], "replace"], wait_loaded=True)
        self.tracks, self.index = tracks, 0
        return {"playing_url": tracks[0], "search_results": len(tracks)}

    async def control(self, action: str) -> dict:
        if action == "pause":
            await self.command(["set_property", "pause", True])
        elif action == "resume":
            await self.command(["set_property", "pause", False])
        elif action == "stop":
            await self.command(["stop"])
            self.tracks = []
        elif action == "next":
            index = self.index + 1
            if index >= len(self.tracks):
                raise BuddyError("No next search result remains. Ask to play something new.")
            await self.command(["loadfile", self.tracks[index], "replace"], wait_loaded=True)
            self.index = index
        return {"music_action": action}

    async def close(self) -> None:
        child, self.child = self.child, None
        if child and child.returncode is None:
            try:
                child.kill()
            except ProcessLookupError:
                pass
            await child.wait()
        if self.directory:
            self.directory.cleanup()
            self.directory = None
        self.socket = None
        self.tracks = []


def register(registry):
    player = MusicPlayer()
    registry.cleanups.append(player.close)

    async def play(args):
        return await player.play(args["query"])

    async def control(args):
        return await player.control(args["action"])

    registry.add(
        Tool(
            "play_music",
            "Search YouTube for requested music and play it through BUDDY's mpv player.",
            schema({"query": string(300)}, ["query"]),
            play,
        )
    )
    registry.add(
        Tool(
            "control_music",
            "Pause, resume, stop, or play the next music search result in BUDDY's player.",
            schema({"action": string(enum=["pause", "resume", "stop", "next"])}, ["action"]),
            control,
        )
    )
