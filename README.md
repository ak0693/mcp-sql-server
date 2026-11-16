# mcp-sql-server

[![CI](https://github.com/ak0693/mcp-sql-server/actions/workflows/ci.yml/badge.svg)](https://github.com/ak0693/mcp-sql-server/actions/workflows/ci.yml)

An [MCP](https://modelcontextprotocol.io) server that gives an LLM read-only SQL access to a DuckDB warehouse. The model can explore the schema and answer questions with SQL. It cannot write, read files, reach the network, or run a query long enough to hang the server.

The demo warehouse is [TPC-H](https://www.tpc.org/tpch/), the standard decision-support benchmark: orders, line items, customers, suppliers and parts across 25 nations. DuckDB generates it locally, so there is nothing to download.

## Why this exists

Pointing an LLM at a database is easy. Doing it so a wrong or hostile query cannot cause damage, and so the model gets error messages it can learn from, takes more care. This repo is a small, fully tested example of that care.

## Tools

| Tool | What it does |
|---|---|
| `list_tables` | Tables with approximate row counts and a one-line description |
| `describe_table` | Columns with type, nullability and a plain-English meaning |
| `run_query` | One `SELECT` in DuckDB SQL; returns columns, rows and a `truncated` flag |

All three are annotated read-only and closed-world, so MCP clients can treat them as safe to call without confirmation.

TPC-H column names are terse (`l_extendedprice`, `ps_supplycost`). The build step writes a description on every table and column, for example *"l_discount: Discount as a fraction, 0.00 to 0.10. Revenue = l_extendedprice \* (1 - l_discount)."* That is most of what a model needs to write correct SQL against a schema it has never seen.

## Safety: three independent layers

```
run_query(sql)
   │
   ├─ 1. Static guard (sqlglot)      refuses anything but one SELECT over known tables
   ├─ 2. Locked-down connection      read-only, no file/network access, settings locked
   └─ 3. Execution limits            row cap and wall-clock timeout
```

1. **Static guard** ([`guard.py`](src/mcp_sql_server/guard.py)). Parses the query and accepts it only if it is a single read statement whose tables are all in the warehouse. Writes and DDL are refused even inside a CTE. File, network and environment functions (`read_csv`, `glob`, `getenv`, ...) and table functions in `FROM` are refused.
2. **Locked-down connection** ([`warehouse.py`](src/mcp_sql_server/warehouse.py)). The database is opened `read_only`, with `enable_external_access` off, extension autoloading off and `lock_configuration` on. The tests bypass the guard on purpose and confirm this layer refuses writes, file reads and attempts to unlock settings on its own.
3. **Execution limits.** Results are capped (200 rows by default) and the response says whether more existed. A timer interrupts any query past the time limit (10 s by default), and the connection stays usable afterwards.

Errors the model can fix come back as plain-text tool errors tagged by kind (`Refused:`, `SQL error:`, `Timed out:`), so the model can correct itself and the evaluation can count each kind. Unexpected failures are reported generically, so internals do not leak.

## Evaluation

Guardrails are only half the job: the tools also have to be usable. The harness in [`evals/`](src/mcp_sql_server/evals) measures that with the 22 TPC-H benchmark queries.

**How it works**

1. Each reference query is restated as a plain-English business question that names the columns to return ([`questions.py`](src/mcp_sql_server/evals/questions.py)). The reference SQL itself comes from DuckDB's tpch extension, not from this repo.
2. The model gets the server's real tools, fetched over the MCP protocol exactly as a client like Claude Desktop sees them, plus one harness tool, `submit_answer`. It explores and queries as it likes (up to 15 tool calls), then submits one SELECT.
3. The submitted query runs in full and its result is compared with the reference result. Row order, column order and floating-point noise are ignored; extra or missing rows or columns are not ([`scoring.py`](src/mcp_sql_server/evals/scoring.py)).
4. The report records accuracy, tool calls per question, guard refusals, SQL errors, timeouts and tokens, plus a JSON Lines file with every tool call for each question.

Grading runs the model's SQL, not its prose, so the score is objective. One question is a deliberate trap: TPC-H query 19 filters on ship mode `'AIR REG'`, which never occurs in the data (the real value is `'REG AIR'`). A model that quietly "fixes" the filter gets a different answer and fails, which tests whether it follows the stated spec.

**Run it**

```bash
pip install -e ".[dev,eval]"
python -m mcp_sql_server.evals --model oracle               # free pipeline check, scores 22/22
export ANTHROPIC_API_KEY=...
python -m mcp_sql_server.evals --model claude-sonnet-5-5    # the real run
```

The oracle submits the reference SQL without calling a model. It checks that every reference query passes the guard and scores as correct against itself, and it runs in the test suite on every push. Use `--questions 1 6 14` to try a few questions before a full run.

**Results**

_Pending the first full model run._

## Quick start

```bash
pip install -e ".[dev]"
python -m mcp_sql_server.build --sf 0.1      # about 600k line items, takes a few seconds
python -m pytest                              # 70+ tests, a few seconds
```

### Use it from Claude Desktop

Add this to `claude_desktop_config.json`, with absolute paths:

```json
{
  "mcpServers": {
    "tpch-warehouse": {
      "command": "python",
      "args": ["-m", "mcp_sql_server", "--db", "/absolute/path/to/data/tpch.duckdb"]
    }
  }
}
```

Then ask something like *"Which five nations generated the most revenue in 1995?"* and watch it list tables, read descriptions and query.

Options: `--max-rows` (default 200) and `--timeout` in seconds (default 10). The database path can also come from `MCP_SQL_DB`.

## Project layout

```
src/mcp_sql_server/
  build.py       generate TPC-H and write table/column descriptions
  guard.py       static SQL checks
  warehouse.py   locked-down connection, row cap, timeout
  server.py      MCP tools and stdio entry point
  evals/
    questions.py   the 22 questions in plain English
    reference.py   reference SQL and expected results
    agent.py       the model loop over the MCP tools
    models.py      Claude adapter, scripted and oracle models
    scoring.py     result-set comparison
    runner.py      CLI and reports
tests/           guard, warehouse, MCP client and harness tests
eval_results/    reports from model runs
```

## Roadmap

- [x] Read-only server, three-layer guardrails, test suite, CI
- [x] Evaluation harness on the 22 TPC-H questions, with an oracle pipeline check in CI
- [ ] Results from a full model run in this README
- [ ] Compare models, and with and without the column descriptions, to measure how much the descriptions help

## Limitations

- The guard uses a denylist for dangerous functions. It is not the only defence, since the connection itself blocks external access, but a function added in a future DuckDB release would not be refused with a friendly message until the list is updated.
- One connection serves queries one at a time. That suits a single local client; a shared deployment would want a connection pool.
- Row capping wraps the query in an outer `LIMIT`, so DuckDB still does all the work needed to produce the first rows. The timeout covers the expensive cases.

## License

MIT
