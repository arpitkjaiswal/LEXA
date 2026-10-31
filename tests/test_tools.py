import asyncio
import time
from dataclasses import replace

import pytest
from conftest import AuditDouble, BrainDouble, SpeakerDouble

from buddy.core.assistant import Assistant
from buddy.core.storage import Store
from buddy.core.tools import Tool, ToolRegistry, schema, string


def registry(config, enabled=()):
    config = replace(config, skills=replace(config.skills, enabled=list(enabled)))
    return ToolRegistry(config, AuditDouble())


@pytest.mark.parametrize(
    "arguments",
    [
        {"value": True},
        {"value": -1},
        {"value": 101},
        {"value": "40"},
        {"value": 40, "script": "unexpected"},
        [],
        None,
        {"value": float("nan")},
    ],
)
async def test_invalid_arguments_never_execute(config, arguments):
    calls = []

    async def run(args):
        calls.append(args)
        return {}

    tools = registry(config)
    tools.add(
        Tool(
            "volume",
            "test",
            schema({"value": {"type": "integer", "minimum": 0, "maximum": 100}}, ["value"]),
            run,
        )
    )
    assert not (await tools.invoke("volume", arguments))["ok"]
    assert calls == []
    assert not (await tools.invoke("shell", {"command": "anything"}))["ok"]


async def test_confirmation_binds_immutable_arguments_is_single_use_and_expires(config):
    tools = registry(config)
    calls = []

    async def run(args):
        calls.append(args["value"])
        return {"saved": args["value"]}

    tools.add(Tool("sensitive", "test", schema({"value": string()}, ["value"]), run, True))
    args = {"value": "original"}
    assert (await tools.invoke("sensitive", args))["pending"]
    args["value"] = "mutated"
    token = tools.pending.identifier
    assert (await tools.confirm(token))["ok"]
    assert calls == ["original"]
    assert not (await tools.confirm(token))["ok"]
    await tools.invoke("sensitive", {"value": "expired"})
    tools.pending = replace(tools.pending, expires=time.monotonic() - 1)
    assert not (await tools.confirm(tools.pending.identifier))["ok"]
    assert calls == ["original"]
    await tools.invoke("sensitive", {"value": "wrong token"})
    assert not (await tools.confirm("wrong"))["ok"]
    assert tools.pending is None


async def test_sensitive_tool_has_no_effect_before_approval_and_mute_revokes_it(config):
    tools = registry(config)
    calls = []

    async def run(args):
        calls.append(True)
        return {}

    tools.add(Tool("sensitive", "test", schema({}), run, True))
    app = Assistant(
        config, BrainDouble(), SpeakerDouble(), AuditDouble(), tools=tools, on_text=lambda _: None
    )
    await tools.invoke("sensitive", {})
    token = tools.pending.identifier
    assert calls == []
    app.set_muted(True)
    assert tools.pending is None
    app.set_muted(False)
    assert "does not match" in await app.respond("/confirm " + token)
    assert calls == []


async def test_cancelled_execution_propagates_and_runs_cleanup(config):
    tools = registry(config)
    started, closed = asyncio.Event(), asyncio.Event()

    async def run(args):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    tools.add(Tool("wait", "test", schema({}), run))
    task = asyncio.create_task(tools.invoke("wait", {}))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


async def test_disabled_modules_do_not_register_and_urls_cannot_escape_allowlist(
    config, monkeypatch
):
    config = replace(config, skills=replace(config.skills, enabled=["web"]))
    tools = ToolRegistry(config, AuditDouble())
    assert set(tools.tools) == {"open_url", "web_search"}
    from buddy.skills import web

    monkeypatch.setattr(web, "mac_only", lambda: None)
    opened = []

    async def process(args):
        opened.append(args)
        return b""

    monkeypatch.setattr(web, "process", process)
    for url in (
        "file:///tmp/test",
        "https://youtube.com.evil.test/",
        "https://127.0.0.1/",
        "https://youtube.com@evil.test/",
        "javascript:alert(1)",
        "https://youtube.com:444/",
        "https://youtube.com/\nanything",
    ):
        assert not (await tools.invoke("open_url", {"url": url}))["ok"]
    assert not opened
    assert (await tools.invoke("open_url", {"url": "https://www.youtube.com/"}))["ok"]
    assert opened == [["/usr/bin/open", "https://www.youtube.com/"]]


async def test_clear_saved_history_does_not_reinsert_the_confirmation_turn(config):
    config = replace(
        config,
        memory=replace(config.memory, save_history=True),
        tts=replace(config.tts, backend="none"),
    )
    store = Store(config)
    tools = ToolRegistry(config, AuditDouble(), store)
    app = Assistant(
        config,
        BrainDouble(),
        SpeakerDouble(),
        AuditDouble(),
        tools=tools,
        store=store,
        on_text=lambda _: None,
    )
    await app.respond("private retained turn")
    assert store.history()
    await tools.invoke("clear_saved_history", {})
    answer = await app.respond("/confirm " + tools.pending.identifier)
    assert "deleted" in answer
    assert store.execute("SELECT * FROM turns") == []
    assert app.history == []
    await app.close()
    store.close()
