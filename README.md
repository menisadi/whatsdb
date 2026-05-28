# whatsdb

Parse WhatsApp chat exports into a SQLite database.

## Installation

```bash
uv sync
```

This installs the `whatsdb` CLI with no external dependencies — the parser is pure Python stdlib.

## Usage

Export your chat from WhatsApp ("Export Chat" → without media) and run:

```bash
whatsdb --input chat.txt
```

This creates `cats.db` in the current directory. Multiple files are merged and sorted by timestamp:

```bash
whatsdb --input chat1.txt chat2.txt --output merged.db
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--input FILE [FILE …]` | `cats.txt` | One or more export files |
| `--output FILE` | `cats.db` | Output SQLite database |
| `--force` | off | Overwrite existing DB without prompting |

## Database schema

```sql
CREATE TABLE messages (
    id        INTEGER PRIMARY KEY,
    ts        TEXT NOT NULL,   -- "YYYY-MM-DD HH:MM"
    sender    TEXT,            -- NULL for system messages
    body      TEXT NOT NULL,
    is_system INTEGER NOT NULL DEFAULT 0
);
```

A full-text search virtual table (`messages_fts`) is also created over `body` and `sender`.

## Examples

The `examples/` directory contains ready-to-run scripts that show what you can do with the database.
Each script declares its own dependencies and can be run directly with `uv run`:

### Analyze busiest days

```bash
uv run examples/analyze_chat.py --db cats.db --top 10 --per_user
```

### Plot message frequency

```bash
# Messages per week with a 4-week rolling average
uv run examples/plot_messages.py per-period --period week --smooth 4

# Sliding 12-hour window
uv run examples/plot_messages.py sliding --window 12

# Stacked area chart by sender (top 6, monthly)
uv run examples/plot_messages.py by-sender --stacked --period month
```
