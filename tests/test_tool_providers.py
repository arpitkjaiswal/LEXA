import json
from dataclasses import replace

import httpx
import pytest
from anthropic import AsyncAnthropic
from conftest import AuditDouble
from openai import AsyncOpenAI

from buddy.core.brain import ClaudeBrain, OllamaBrain, OpenAIBrain
from buddy.core.errors import BrainError
from buddy.core.tool_brain import stream_tools
from buddy.core.tools import Tool, ToolRegistry, schema


def setup_registry(config, *, confirm=False):
    registry = ToolRegistry(
        replace(config, skills=replace(config.skills, enabled=[])), AuditDouble()
    )
    calls = []

    async def run(args):
        calls.append(True)
        return {"datetime": "2026-10-31T13:00:00+05:30"}

    registry.add(Tool("clock", "Read the clock", schema({}), run, confirm))
    return registry, calls


async def collect(brain, registry):
    return "".join(
        [
            text
            async for text in stream_tools(
                brain, [{"role": "user", "content": "What time is it?"}], "Test system", registry
            )
        ]
    )


def claude_response(content, reason):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "test-model",
        "content": content,
        "stop_reason": reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 5, "output_tokens": 5},
    }


async def test_claude_real_sdk_receives_tool_result_before_final_reply(config):
    registry, calls = setup_registry(config)
    requests = []

    def handle(request):
        data = json.loads(request.content)
        requests.append(data)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json=claude_response(
                    [
                        {"type": "text", "text": "I already changed something."},
                        {"type": "tool_use", "id": "tool_1", "name": "clock", "input": {}},
                    ],
                    "tool_use",
                ),
            )
        outcome = json.loads(data["messages"][-1]["content"][0]["content"])
        assert outcome["ok"] and outcome["result"]["datetime"].endswith("+05:30")
        return httpx.Response(
            200, json=claude_response([{"type": "text", "text": "It is 1 PM."}], "end_turn")
        )

    client = AsyncAnthropic(
        api_key="test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    brain = ClaudeBrain(config, client=client)
    assert await collect(brain, registry) == "It is 1 PM."
    assert calls == [True] and len(requests) == 2
    await brain.close()


async def test_claude_sensitive_call_is_pending_and_no_action_runs(config):
    registry, calls = setup_registry(config, confirm=True)
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json=claude_response(
                [{"type": "tool_use", "id": "t", "name": "clock", "input": {}}], "tool_use"
            ),
        )

    client = AsyncAnthropic(
        api_key="test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    brain = ClaudeBrain(config, client=client)
    answer = await collect(brain, registry)
    assert "/confirm " + registry.pending.identifier in answer
    assert calls == [] and len(requests) == 1
    await brain.close()


async def test_openai_real_sdk_stateless_function_result_roundtrip(config):
    registry, calls = setup_registry(config)
    requests = []

    def handle(request):
        data = json.loads(request.content)
        requests.append(data)
        assert data["store"] is False
        if len(requests) == 1:
            output = [
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "clock",
                    "arguments": "{}",
                    "status": "completed",
                }
            ]
        else:
            assert data["input"][-1]["call_id"] == "call_1"
            assert json.loads(data["input"][-1]["output"])["ok"]
            output = [
                {
                    "type": "message",
                    "id": "msg_1",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "It is 1 PM.", "annotations": []}],
                }
            ]
        return httpx.Response(
            200,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "output": output,
            },
        )

    client = AsyncOpenAI(
        api_key="test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    brain = OpenAIBrain(config, client=client)
    assert await collect(brain, registry) == "It is 1 PM."
    assert len(requests) == 2 and calls == [True]
    await brain.close()


async def test_ollama_roundtrip_and_invalid_tool_name_denied(config):
    registry, calls = setup_registry(config)
    requests = []

    def handle(request):
        data = json.loads(request.content)
        requests.append(data)
        if len(requests) == 1:
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "shell", "arguments": {"command": "anything"}}}
                ],
            }
        else:
            outcome = json.loads(data["messages"][-1]["content"])
            assert not outcome["ok"] and "allowlisted" in outcome["error"]
            message = {"role": "assistant", "content": "That action is unavailable."}
        return httpx.Response(200, json={"message": message, "done": True})

    brain = OllamaBrain(config, client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    assert "unavailable" in await collect(brain, registry)
    assert calls == [] and len(requests) == 2
    await brain.close()


async def test_incomplete_tool_response_does_not_execute_any_call(config):
    registry, calls = setup_registry(config)
    client = AsyncAnthropic(
        api_key="test",
        max_retries=0,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json=claude_response(
                        [{"type": "tool_use", "id": "t", "name": "clock", "input": {}}],
                        "max_tokens",
                    ),
                )
            )
        ),
    )
    brain = ClaudeBrain(config, client=client)
    with pytest.raises(BrainError, match="incomplete"):
        await collect(brain, registry)
    assert calls == []
    await brain.close()
