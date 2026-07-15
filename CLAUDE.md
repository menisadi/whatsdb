# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                          # install dev dependencies (pytest)
uv run -m pytest                 # run all tests
uv run -m pytest tests/test_build_db.py::test_name  # run a single test
uv run ruff format .
uv run ruff check . --fix
uv run ty check
```

Run the main CLI:

```bash
uv run -m build_db --input chat.txt --output out.db
uv run -m merge_db target.db source.db
```

Run example scripts (each declares its own deps via PEP 723 `# /// script` blocks — `uv run` installs them automatically):

```bash
uv run examples/analyze_chat.py --db cats.db
uv run examples/plot_messages.py per-period --period week
uv run examples/markov_generator.py --db cats.db --n 5
uv run examples/sender_classifier.py --db cats.db classify
```

## Architecture

The project has two layers:

**Core (zero external dependencies, stdlib only):**

- `build_db.py` — CLI entry point + parser. `_parse_file()` reads a WhatsApp `.txt` export line by line, assembles multi-line messages, and returns `list[Message]`. `_build_db()` writes to SQLite with a `messages` table, three indexes (including a dedup index on `minute(ts) + body + sender`), and an FTS5 virtual table.
- `merge_db.py` — merges a source DB into a target using SQL `NOT EXISTS` against the dedup key, then rebuilds the FTS5 index.

**Examples (optional deps, standalone scripts):**

Each file in `examples/` is a PEP 723 inline-dependency script. They all read from the SQLite DB produced by `build_db.py` and are independent of each other. They use `fire` or `typer` for their CLIs.

**Data flow:**

```
WhatsApp export (.txt)
  → _parse_file() → list[Message]
  → _build_db()   → SQLite (messages table + FTS5)
  → examples/*    → analysis / plots / ML
```

**Deduplication key** (used by both `build_db` and `merge_db`): `strftime('%Y-%m-%d %H:%M', ts) || body || sender`. This handles the two WhatsApp timestamp formats (second-precision vs. minute-precision) that can appear across different export sources.

## Key constraints

- The core (`build_db.py`, `merge_db.py`) must stay zero-dependency — no imports outside stdlib.
- Python 3.13 is required (`.python-version`).
- FTS5 row count is validated against the main table after every insert/merge; any mismatch is a bug.
- `id` (rowid) tracks chronological order only until the first merge. `build_db.py` inserts rows in file order (chronological), but `merge_db.py` appends merged rows in source-scan order at the end of the `id` range regardless of their `ts`. After any merge, `id` order can no longer be used as a proxy for time — always `ORDER BY ts` (not `id`) for chronological analysis.
