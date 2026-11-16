"""The agent loop: one question, answered through the real MCP tools.

The model sees the server's own tools (fetched with ``list_tools`` over the MCP
protocol, so the eval exercises exactly what a client like Claude Desktop
would see) plus one harness tool, ``submit_answer``. It explores and queries
as it likes, then submits the SQL it believes answers the question. Scoring
runs that SQL, not the model's prose, so the grade is objective.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from mcp import Client

from ..server import REFUSED, SQL_ERROR, TIMED_OUT
from .models import ChatModel

SUBMIT_TOOL = {
    "name": "submit_answer",
    "description": (
        "Submit your final answer as one SELECT query. It is run in full (no row cap) and its "
        "result is compared with the reference answer. Call this exactly once, when you are done."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"sql": {"type": "string", "description": "The final SELECT query."}},
        "required": ["sql"],
    },
}

SYSTEM_PROMPT = """\
You answer business questions about a sales warehouse by writing SQL.
You have tools to inspect the schema and run read-only queries. Explore as
much as you need, check your query returns what the question asks for, then
call submit_answer once with the final SELECT. Return exactly the columns the
question asks for, in that order, and nothing else.

Server instructions:
{instructions}"""


@dataclass
class Transcript:
    submitted_sql: str | None = None
    tool_calls: int = 0
    refusals: int = 0
    sql_errors: int = 0
    timeouts: int = 0
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    stopped: str = ""
    calls: list[dict[str, Any]] = field(default_factory=list)


def _mcp_tools_to_claude(tools: list[Any]) -> list[dict[str, Any]]:
    return [
        {"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
        for t in tools
    ]


_SDK_PREFIX = re.compile(r"^Error executing tool \w+: ")


def _error_kind(text: str) -> str | None:
    """Read the server's error tag, after the prefix the MCP SDK adds."""
    body = _SDK_PREFIX.sub("", text, count=1)
    for tag in (REFUSED, TIMED_OUT, SQL_ERROR):
        if body.startswith(tag):
            return tag
    return None


def _result_text(result: Any) -> str:
    if result.structured_content is not None and not result.is_error:
        return json.dumps(result.structured_content, default=str)
    return "\n".join(getattr(block, "text", "") for block in result.content)


async def answer_question(
    server: Any, model: ChatModel, question: str, max_tool_calls: int = 15
) -> Transcript:
    """Let the model answer one question; return what it submitted and how it got there."""
    transcript = Transcript()
    started = time.perf_counter()

    async with Client(server) as client:
        listed = await client.list_tools()
        tools = _mcp_tools_to_claude(listed.tools) + [SUBMIT_TOOL]
        instructions = getattr(server, "instructions", "") or ""
        system = SYSTEM_PROMPT.format(instructions=instructions)
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]

        while True:
            turn = model.respond(system=system, tools=tools, messages=messages)
            transcript.turns += 1
            transcript.input_tokens += turn.input_tokens
            transcript.output_tokens += turn.output_tokens
            messages.append({"role": "assistant", "content": turn.raw_content or turn.text})

            if not turn.tool_calls:
                transcript.stopped = "no_submission"
                break

            results: list[dict[str, Any]] = []
            for call in turn.tool_calls:
                if call.name == "submit_answer":
                    transcript.submitted_sql = str(call.input.get("sql", ""))
                    transcript.stopped = "submitted"
                    break
                transcript.tool_calls += 1
                result = await client.call_tool(call.name, call.input)
                text = _result_text(result)
                if result.is_error:
                    kind = _error_kind(text)
                    if kind == REFUSED:
                        transcript.refusals += 1
                    elif kind == TIMED_OUT:
                        transcript.timeouts += 1
                    elif kind == SQL_ERROR:
                        transcript.sql_errors += 1
                transcript.calls.append(
                    {"tool": call.name, "input": call.input, "error": bool(result.is_error)}
                )
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": text,
                        "is_error": bool(result.is_error),
                    }
                )

            if transcript.stopped == "submitted":
                break
            if transcript.tool_calls >= max_tool_calls:
                transcript.stopped = "tool_call_limit"
                break
            messages.append({"role": "user", "content": results})

    transcript.seconds = round(time.perf_counter() - started, 2)
    return transcript
