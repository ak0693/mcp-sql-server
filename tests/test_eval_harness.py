"""Tests for the evaluation harness. No API key needed: models are scripted."""

from types import SimpleNamespace

import pytest

from mcp_sql_server.evals.agent import answer_question
from mcp_sql_server.evals.models import ClaudeModel, OracleModel, ScriptedModel
from mcp_sql_server.evals.questions import QUESTIONS
from mcp_sql_server.evals.reference import load_cases, reference_queries
from mcp_sql_server.evals.runner import run_eval, summarise, write_report
from mcp_sql_server.server import create_server

pytestmark = pytest.mark.anyio


def test_there_is_a_question_for_every_reference_query():
    assert set(QUESTIONS) == set(reference_queries()) == set(range(1, 23))


async def test_oracle_scores_22_out_of_22(warehouse_path):
    # The whole pipeline end to end: every reference query must pass the
    # guard, run, and score as correct against itself.
    cases = load_cases(warehouse_path)
    oracle = OracleModel({c.number: c.reference_sql for c in cases})
    results = await run_eval(warehouse_path, oracle)
    failed = [(r.number, r.reason) for r in results if not r.correct]
    assert failed == []
    assert len(results) == 22


async def test_wrong_answer_is_marked_wrong(warehouse_path):
    model = ScriptedModel([[("submit_answer", {"sql": "SELECT 1"})]])
    results = await run_eval(warehouse_path, model, numbers=[6])
    assert results[0].correct is False


async def test_refusals_and_errors_are_counted(warehouse, warehouse_path):
    reference = load_cases(warehouse_path, [6])[0].reference_sql
    model = ScriptedModel(
        [
            [("run_query", {"sql": "DELETE FROM lineitem"})],
            [("run_query", {"sql": "SELECT no_such_column FROM lineitem"})],
            [("describe_table", {"table": "lineitem"})],
            [("submit_answer", {"sql": reference})],
        ]
    )
    transcript = await answer_question(create_server(warehouse), model, QUESTIONS[6])
    assert transcript.submitted_sql == reference
    assert transcript.tool_calls == 3
    assert transcript.refusals == 1
    assert transcript.sql_errors == 1
    assert transcript.stopped == "submitted"


async def test_model_that_never_submits(warehouse):
    model = ScriptedModel([[("list_tables", {})]])
    transcript = await answer_question(create_server(warehouse), model, QUESTIONS[1])
    assert transcript.submitted_sql is None
    assert transcript.stopped == "no_submission"


async def test_tool_call_limit(warehouse):
    model = ScriptedModel([[("list_tables", {})]] * 10)
    transcript = await answer_question(create_server(warehouse), model, QUESTIONS[1], max_tool_calls=3)
    assert transcript.tool_calls == 3
    assert transcript.stopped == "tool_call_limit"


async def test_report_files(warehouse_path, tmp_path):
    model = ScriptedModel([[("submit_answer", {"sql": "SELECT 1"})]])
    results = await run_eval(warehouse_path, model, numbers=[6])
    summary = write_report(results, "scripted", "0.01", tmp_path)
    assert summary.name.startswith("scripted_sf0p01_") and summary.suffix == ".md"
    assert (tmp_path / (summary.stem + ".jsonl")).exists()
    assert "Accuracy:** 0/1" in summarise(results, "scripted", "0.01")


def test_claude_adapter_parses_text_and_tool_use():
    # A stand-in for the Anthropic client, shaped like its response objects.
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="Let me look."),
            SimpleNamespace(type="tool_use", id="tu_1", name="list_tables", input={}),
        ],
        usage=SimpleNamespace(input_tokens=120, output_tokens=30),
    )
    seen = {}

    def create(**kwargs):
        seen.update(kwargs)
        return response

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    model = ClaudeModel("claude-test", client=client)
    turn = model.respond(system="sys", tools=[{"name": "t"}], messages=[{"role": "user", "content": "q"}])

    assert seen["model"] == "claude-test" and seen["system"] == "sys"
    assert turn.text == "Let me look."
    assert [(c.id, c.name) for c in turn.tool_calls] == [("tu_1", "list_tables")]
    assert (turn.input_tokens, turn.output_tokens) == (120, 30)
    assert turn.raw_content[1] == {"type": "tool_use", "id": "tu_1", "name": "list_tables", "input": {}}
