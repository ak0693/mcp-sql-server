"""Model adapters for the evaluation agent.

The agent keeps the conversation in Anthropic Messages format and talks to a
model through one method, ``respond``. Two adapters exist:

- ``ClaudeModel`` calls the Claude API (needs ``ANTHROPIC_API_KEY`` and the
  ``eval`` extra).
- ``OracleModel`` needs no API: it submits the reference SQL straight away.
  It checks the whole pipeline (questions, references, guard, scoring) and
  should always score 22/22. Run it before spending anything on a real model.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ModelTurn:
    text: str
    tool_calls: list[ToolCall]
    input_tokens: int = 0
    output_tokens: int = 0
    # Content blocks to append to the transcript as the assistant message.
    raw_content: list[dict[str, Any]] = field(default_factory=list)


class ChatModel(Protocol):
    name: str

    def respond(
        self, *, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]
    ) -> ModelTurn: ...


class ClaudeModel:
    def __init__(self, model: str, max_tokens: int = 4096, client: Any = None) -> None:
        if client is None:
            try:
                import anthropic
            except ImportError as err:  # pragma: no cover - depends on install
                raise SystemExit('Install the eval extra first: pip install -e ".[eval]"') from err
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise SystemExit("Set ANTHROPIC_API_KEY to run the evaluation against Claude.")
            client = anthropic.Anthropic()
        self.client = client
        self.name = model
        self.max_tokens = max_tokens

    def respond(
        self, *, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]
    ) -> ModelTurn:
        response = self.client.messages.create(
            model=self.name,
            max_tokens=self.max_tokens,
            system=system,
            tools=tools,
            messages=messages,
        )
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        raw: list[dict[str, Any]] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
                raw.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                calls.append(ToolCall(id=block.id, name=block.name, input=dict(block.input)))
                raw.append(
                    {"type": "tool_use", "id": block.id, "name": block.name, "input": dict(block.input)}
                )
        return ModelTurn(
            text="\n".join(text_parts),
            tool_calls=calls,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            raw_content=raw,
        )


class ScriptedModel:
    """Replays a fixed list of turns. Used by the tests and by OracleModel."""

    name = "scripted"

    def __init__(self, turns: list[list[tuple[str, dict[str, Any]]]]) -> None:
        self._turns = list(turns)
        self._counter = 0

    def respond(
        self, *, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]
    ) -> ModelTurn:
        if not self._turns:
            return ModelTurn(text="I am done.", tool_calls=[], raw_content=[{"type": "text", "text": "I am done."}])
        calls = []
        for name, args in self._turns.pop(0):
            self._counter += 1
            calls.append(ToolCall(id=f"call_{self._counter}", name=name, input=args))
        raw = [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in calls]
        return ModelTurn(text="", tool_calls=calls, raw_content=raw)


class OracleModel:
    """Looks at the schema once, then submits the reference SQL."""

    name = "oracle"

    def __init__(self, reference_sql: dict[int, str]) -> None:
        self.reference_sql = reference_sql
        self._script: ScriptedModel | None = None

    def start_case(self, number: int) -> None:
        self._script = ScriptedModel(
            [
                [("list_tables", {})],
                [("submit_answer", {"sql": self.reference_sql[number]})],
            ]
        )

    def respond(self, **kwargs: Any) -> ModelTurn:
        assert self._script is not None, "call start_case first"
        return self._script.respond(**kwargs)
