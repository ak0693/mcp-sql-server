"""Run the evaluation and write a report.

Usage:
    # Free pipeline check: should score 22/22.
    python -m mcp_sql_server.evals --model oracle

    # The real thing.
    export ANTHROPIC_API_KEY=...
    python -m mcp_sql_server.evals --model claude-sonnet-5-5

Results go to eval_results/ as a JSON Lines file (one record per question,
including every tool call) and a Markdown summary that can be pasted into
the README.
"""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anyio

from ..guard import GuardError
from ..server import create_server
from ..warehouse import QueryTimeout, Warehouse
from .agent import Transcript, answer_question
from .models import ChatModel, ClaudeModel, OracleModel
from .reference import Case, load_cases
from .scoring import compare_results


@dataclass
class CaseResult:
    number: int
    correct: bool
    reason: str
    transcript: Transcript


def score_submission(scorer: Warehouse, case: Case, transcript: Transcript) -> tuple[bool, str]:
    if transcript.submitted_sql is None:
        return False, f"no answer ({transcript.stopped})"
    try:
        result = scorer.run_query(transcript.submitted_sql)
    except GuardError as err:
        return False, f"submission refused: {err}"
    except QueryTimeout:
        return False, "submission timed out"
    except Exception as err:  # noqa: BLE001 - any SQL failure is a wrong answer
        return False, f"submission failed: {type(err).__name__}"
    if result.truncated:
        return False, "submission returned too many rows"
    comparison = compare_results(case.expected_rows, result.rows)
    return comparison.match, comparison.reason


async def run_eval(
    warehouse_path: Path,
    model: ChatModel,
    numbers: list[int] | None = None,
    max_tool_calls: int = 15,
) -> list[CaseResult]:
    cases = load_cases(warehouse_path, numbers)
    # What the model talks to: the real server, default limits.
    served = Warehouse(warehouse_path)
    # What scores submissions: same guard, but room for full result sets.
    scorer = Warehouse(warehouse_path, max_rows=1_000_000, timeout_s=120)
    server = create_server(served)
    results = []
    try:
        for case in cases:
            if isinstance(model, OracleModel):
                model.start_case(case.number)
            transcript = await answer_question(server, model, case.question, max_tool_calls)
            correct, reason = score_submission(scorer, case, transcript)
            results.append(CaseResult(case.number, correct, reason, transcript))
            mark = "PASS" if correct else "FAIL"
            print(f"Q{case.number:<2} {mark}  calls={transcript.tool_calls:<2} {reason}")
    finally:
        served.close()
        scorer.close()
    return results


def summarise(results: list[CaseResult], model_name: str, scale_factor: str) -> str:
    total = len(results)
    correct = sum(r.correct for r in results)
    calls = [r.transcript.tool_calls for r in results]
    lines = [
        f"### {model_name}, TPC-H scale factor {scale_factor}",
        "",
        f"- **Accuracy:** {correct}/{total} ({correct / total:.0%})",
        f"- **Tool calls per question:** median {statistics.median(calls):g}, max {max(calls)}",
        f"- **Guard refusals:** {sum(r.transcript.refusals for r in results)}"
        f" · SQL errors: {sum(r.transcript.sql_errors for r in results)}"
        f" · timeouts: {sum(r.transcript.timeouts for r in results)}",
        f"- **Tokens:** {sum(r.transcript.input_tokens for r in results):,} in, "
        f"{sum(r.transcript.output_tokens for r in results):,} out",
        "",
        "| Q | Result | Tool calls | Refusals | SQL errors | Note |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        t = r.transcript
        mark = "pass" if r.correct else "fail"
        note = "" if r.correct else r.reason
        lines.append(f"| {r.number} | {mark} | {t.tool_calls} | {t.refusals} | {t.sql_errors} | {note} |")
    return "\n".join(lines) + "\n"


def write_report(results: list[CaseResult], model_name: str, scale_factor: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # Build names by hand: Path.with_suffix would treat the "." in "0.1" as an extension.
    stem = f"{model_name}_sf{scale_factor.replace('.', 'p')}_{stamp}"
    with (out_dir / f"{stem}.jsonl").open("w") as f:
        for r in results:
            record: dict[str, Any] = {"question": r.number, "correct": r.correct, "reason": r.reason}
            record.update(asdict(r.transcript))
            f.write(json.dumps(record, default=str) + "\n")
    summary = out_dir / f"{stem}.md"
    summary.write_text(summarise(results, model_name, scale_factor))
    return summary


def _scale_factor(path: Path) -> str:
    import duckdb

    from ..warehouse import LOCKDOWN

    con = duckdb.connect(str(path), read_only=True, config=LOCKDOWN)
    try:
        lineitems = con.execute("SELECT count(*) FROM lineitem").fetchone()[0]
    finally:
        con.close()
    # TPC-H has about 6 million line items per unit of scale factor.
    return f"{lineitems / 6_000_000:.2g}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a model on the 22 TPC-H questions via MCP.")
    parser.add_argument("--model", default="oracle", help="'oracle' (free pipeline check) or a Claude model id.")
    parser.add_argument("--db", type=Path, default=Path("data/tpch.duckdb"))
    parser.add_argument("--questions", type=int, nargs="*", help="Subset of question numbers, e.g. 1 6 14.")
    parser.add_argument("--max-tool-calls", type=int, default=15)
    parser.add_argument("--out", type=Path, default=Path("eval_results"))
    args = parser.parse_args()

    if args.model == "oracle":
        cases = load_cases(args.db, args.questions)
        model: ChatModel = OracleModel({c.number: c.reference_sql for c in cases})
    else:
        model = ClaudeModel(args.model)

    results = anyio.run(run_eval, args.db, model, args.questions, args.max_tool_calls)
    summary = write_report(results, model.name, _scale_factor(args.db), args.out)
    print()
    print(summary.read_text())
    print(f"Saved {summary} and {summary.parent / (summary.stem + '.jsonl')}")


if __name__ == "__main__":
    main()
