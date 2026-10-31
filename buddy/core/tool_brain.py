"""Provider-specific tool/result round trips. Only final, grounded replies reach speech."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from buddy.core.brain import BrainError, ClaudeBrain, OllamaBrain, OpenAIBrain, _api_error
from buddy.core.tools import ToolRegistry

MAX_ROUNDS = 6
MAX_CALLS = 8


async def _execute(registry: ToolRegistry, name: str, arguments) -> dict:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (json.JSONDecodeError, RecursionError):
            return {"ok": False, "error": "Tool arguments are not valid JSON."}
    return await registry.invoke(name, arguments)


async def stream_tools(
    brain, messages: list[dict], system: str, registry: ToolRegistry
) -> AsyncIterator[str]:
    definitions = registry.definitions()
    if not definitions or not isinstance(brain, (ClaudeBrain, OpenAIBrain, OllamaBrain)):
        async for text in brain.stream(messages, system):
            yield text
        return
    try:
        # A round includes network and actions; per-request and per-tool deadlines also apply.
        async with asyncio.timeout(brain.config.timeout_seconds * MAX_ROUNDS):
            if isinstance(brain, ClaudeBrain):
                answer = await _claude(brain, messages, system, registry, definitions)
            elif isinstance(brain, OpenAIBrain):
                answer = await _openai(brain, messages, system, registry, definitions)
            else:
                answer = await _ollama(brain, messages, system, registry, definitions)
        if not isinstance(answer, str) or not answer.strip():
            raise BrainError("The provider returned an empty reply.")
        yield answer
    except BrainError:
        raise
    except Exception as error:
        raise _api_error(error, type(brain).__name__.removesuffix("Brain")) from None


async def _claude(brain, messages, system, registry, definitions) -> str:
    turns = list(messages)
    for _ in range(MAX_ROUNDS):
        response = await brain.client.messages.create(
            model=brain.config.model,
            system=system,
            messages=turns,
            tools=definitions,
            max_tokens=brain.config.max_output_tokens,
        )
        calls = [b for b in response.content if b.type == "tool_use"]
        if not calls:
            if response.stop_reason not in {"end_turn", "stop_sequence"}:
                raise BrainError(
                    "Claude did not finish its tool-enabled reply. Raise the token limit."
                )
            return "".join(b.text for b in response.content if b.type == "text")
        if response.stop_reason != "tool_use" or len(calls) > MAX_CALLS:
            raise BrainError(
                "Claude returned incomplete or excessive tool calls; no calls from this round ran."
            )
        turns.append({"role": "assistant", "content": [b.model_dump() for b in response.content]})
        outcomes = []
        for call in calls:
            outcome = await _execute(registry, call.name, call.input)
            if registry.pending:
                return registry.confirmation_text()
            outcomes.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": json.dumps(outcome),
                    "is_error": not outcome["ok"],
                }
            )
        turns.append({"role": "user", "content": outcomes})
    raise BrainError(
        "The action loop reached its limit. Some actions may have completed; "
        "inspect their state before retrying."
    )


async def _openai(brain, messages, system, registry, definitions) -> str:
    turns = list(messages)
    tools = [
        {
            "type": "function",
            "name": d["name"],
            "description": d["description"],
            "parameters": d["input_schema"],
            "strict": False,
        }
        for d in definitions
    ]
    for _ in range(MAX_ROUNDS):
        response = await brain.client.responses.create(
            model=brain.config.model,
            instructions=system,
            input=turns,
            tools=tools,
            max_output_tokens=brain.config.max_output_tokens,
            store=False,
        )
        if response.status != "completed":
            raise BrainError(
                "OpenAI did not finish its tool-enabled reply; no incomplete calls ran."
            )
        calls = [b for b in response.output if b.type == "function_call"]
        if not calls:
            return response.output_text
        if len(calls) > MAX_CALLS:
            raise BrainError("OpenAI returned too many tool calls; this round was not executed.")
        turns.extend(b.model_dump(exclude_none=True) for b in response.output)
        for call in calls:
            outcome = await _execute(registry, call.name, call.arguments)
            if registry.pending:
                return registry.confirmation_text()
            turns.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(outcome),
                }
            )
    raise BrainError(
        "The action loop reached its limit. Some actions may have completed; "
        "inspect their state before retrying."
    )


async def _ollama(brain, messages, system, registry, definitions) -> str:
    turns = [{"role": "system", "content": system}, *messages]
    tools = [
        {
            "type": "function",
            "function": {
                "name": d["name"],
                "description": d["description"],
                "parameters": d["input_schema"],
            },
        }
        for d in definitions
    ]
    for _ in range(MAX_ROUNDS):
        response = await brain.client.post(
            brain.config.ollama_base_url.rstrip("/") + "/api/chat",
            json={
                "model": brain.config.model,
                "messages": turns,
                "tools": tools,
                "stream": False,
                "options": {"num_predict": brain.config.max_output_tokens},
            },
        )
        response.raise_for_status()
        if len(response.content) > 1_000_000:
            raise BrainError("Ollama returned too much data.")
        data = response.json()
        if not data.get("done") or data.get("error"):
            raise BrainError("Ollama did not finish its tool-enabled response.")
        message = data["message"]
        calls = message.get("tool_calls", [])
        if not calls:
            return message.get("content", "")
        if len(calls) > MAX_CALLS:
            raise BrainError("Ollama returned too many tool calls; this round was not executed.")
        turns.append(message)
        for call in calls:
            function = call["function"]
            outcome = await _execute(registry, function["name"], function["arguments"])
            if registry.pending:
                return registry.confirmation_text()
            turns.append(
                {"role": "tool", "tool_name": function["name"], "content": json.dumps(outcome)}
            )
    raise BrainError(
        "The action loop reached its limit. Some actions may have completed; "
        "inspect their state before retrying."
    )
