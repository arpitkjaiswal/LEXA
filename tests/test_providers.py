import json
from dataclasses import replace

import httpx
import pytest
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from buddy.core.brain import ClaudeBrain, OllamaBrain, OpenAIBrain, create_brain
from buddy.core.errors import BrainError, ConfigurationError


def sse(events):
    return "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)


async def collect(brain):
    try:
        return "".join(
            [
                chunk
                async for chunk in brain.stream(
                    [{"role": "user", "content": "Hello"}],
                    "Be concise.",
                )
            ]
        )
    finally:
        await brain.close()


async def test_claude_real_sdk_stream_against_mock_transport(config):
    requests = []
    events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": "test-model",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 3, "output_tokens": 0},
            },
        },
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Hey friend."},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 4},
        },
        {"type": "message_stop"},
    ]

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=sse(events)
        )

    client = AsyncAnthropic(
        api_key="test-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    assert await collect(ClaudeBrain(config, client=client)) == "Hey friend."
    assert requests[0]["stream"] is True
    assert requests[0]["system"] == "Be concise."
    assert "tools" not in requests[0]


async def test_openai_real_sdk_stream_and_stateless_payload(config):
    requests = []
    events = [
        {
            "type": "response.output_text.delta",
            "delta": "Hello ",
            "sequence_number": 0,
            "item_id": "msg_1",
            "output_index": 0,
            "content_index": 0,
            "logprobs": [],
        },
        {
            "type": "response.output_text.delta",
            "delta": "friend.",
            "sequence_number": 1,
            "item_id": "msg_1",
            "output_index": 0,
            "content_index": 0,
            "logprobs": [],
        },
        {
            "type": "response.completed",
            "sequence_number": 2,
            "response": {"id": "resp_1", "object": "response", "status": "completed", "output": []},
        },
    ]

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=sse(events)
        )

    client = AsyncOpenAI(
        api_key="test-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    assert await collect(OpenAIBrain(config, client=client)) == "Hello friend."
    assert requests[0]["store"] is False and requests[0]["instructions"] == "Be concise."
    assert "tools" not in requests[0]


@pytest.mark.parametrize(
    "status, expected",
    [
        (401, "authentication"),
        (403, "authentication"),
        (404, "model"),
        (429, "quota"),
        (500, "request"),
    ],
)
async def test_api_errors_never_leak_response_bodies(config, status, expected):
    def handle(request):
        return httpx.Response(
            status,
            json={
                "type": "error",
                "error": {
                    "type": "authentication_error",
                    "message": "private-test-key and private conversation",
                },
            },
        )

    client = AsyncAnthropic(
        api_key="test-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    with pytest.raises(BrainError) as error:
        await collect(ClaudeBrain(config, client=client))
    assert expected in str(error.value)
    assert "private-test-key" not in str(error.value)
    assert "private conversation" not in str(error.value)


async def test_ollama_stream(config):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200, text='{"message":{"content":"Hi!"},"done":false}\n{"done":true}\n'
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    brain = OllamaBrain(config, client=client)
    assert await collect(brain) == "Hi!"
    assert str(requests[0].url) == "http://127.0.0.1:11434/api/chat"
    assert json.loads(requests[0].content)["messages"][0]["role"] == "system"


@pytest.mark.parametrize("data", ["{}\n", "not json\n", '{"error":"secret detail"}\n'])
async def test_ollama_incomplete_or_invalid_stream_is_not_success(config, data):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=data))
    )
    with pytest.raises(BrainError):
        await collect(OllamaBrain(config, client=client))


async def test_openai_disconnect_fails_instead_of_saving_partial_answer(config):
    events = [
        {
            "type": "response.output_text.delta",
            "delta": "Partial.",
            "sequence_number": 0,
            "item_id": "msg_1",
            "output_index": 0,
            "content_index": 0,
            "logprobs": [],
        }
    ]
    client = AsyncOpenAI(
        api_key="test-key",
        max_retries=0,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=sse(events),
                )
            ),
        ),
    )
    with pytest.raises(BrainError, match="disconnected"):
        await collect(OpenAIBrain(config, client=client))


def test_live_configuration_is_required_but_demo_never_needs_a_key(config):
    config = replace(config, brain=replace(config.brain, model=""))
    with pytest.raises(ConfigurationError):
        create_brain(config)
    assert create_brain(config, demo=True).__class__.__name__ == "DemoBrain"
