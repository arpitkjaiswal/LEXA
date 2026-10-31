import json
from contextlib import closing
from dataclasses import replace

import pytest
from conftest import AuditDouble, SpeakerDouble

from buddy.core.assistant import Assistant
from buddy.core.local_brain import LocalBrain, parse_command
from buddy.core.storage import Store
from buddy.core.tools import Tool, ToolRegistry, schema


@pytest.mark.parametrize(
    "command",
    [
        "please read this note: open calculator",
        '"open calculator"',
        "open calculator and delete my files",
        "set a timer for tomorrow",
    ],
)
def test_local_commands_do_not_guess_or_execute_embedded_instructions(command):
    assert parse_command(command, {"calculator": "com.apple.calculator"}) is None


async def test_local_first_launch_runs_real_timer_note_and_memory_without_provider(config):
    with closing(Store(config)) as store:
        registry = ToolRegistry(config, AuditDouble(), store)
        brain = LocalBrain(registry)

        async def ask(text):
            return "".join([part async for part in brain.stream([{"content": text}], "")])

        timer = json.loads((await ask("set a timer for 5 minutes")).split("\n", 1)[1])
        assert store.execute("SELECT label FROM reminders WHERE id=?", (timer["id"],))
        await ask("note Revision: finish chapter two.")
        assert store.execute("SELECT body FROM notes")[0]["body"] == "finish chapter two."
        await ask("remember style: short answers")
        assert store.facts()[0]["value"] == "short answers"
        assert "Configure AI" in await ask("Tell me a joke")
        await registry.close()


async def test_local_mode_obeys_disabled_skills_and_exact_action_approval(config):
    config = replace(config, skills=replace(config.skills, enabled=[]))
    registry = ToolRegistry(config, AuditDouble())
    calls = []

    async def action(args):
        calls.append(args)
        return {"saved_path": "/test/screenshot.png"}

    registry.add(Tool("take_screenshot", "test capture", schema({}), action, confirm=True))
    assistant = Assistant(
        config, LocalBrain(registry), SpeakerDouble(), AuditDouble(), tools=registry
    )
    assert "not allowlisted" in await assistant.respond("what time is it")
    assert "approve" in await assistant.respond("take a screenshot")
    identifier = registry.pending.identifier
    assert calls == []
    assert "Configure AI" in await assistant.respond("yes")
    assert "missing" in await assistant.respond("/confirm " + identifier)
    await assistant.respond("take a screenshot")
    answer = await assistant.respond("/confirm " + registry.pending.identifier)
    assert calls == [{}] and "/test/screenshot.png" in answer
    await assistant.close()
