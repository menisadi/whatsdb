# /// script
# dependencies = ["fire", "rich"]
# ///

"""Summarize recent WhatsApp messages using the Claude CLI."""

import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import fire
from rich.console import Console
from rich.panel import Panel

console = Console()


def parse_bound(value: str, is_end: bool) -> datetime:
    """Parse 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM'; a date-only end covers that whole day."""
    dt = datetime.fromisoformat(str(value))
    if is_end and len(str(value).strip()) <= 10:
        dt += timedelta(days=1)
    return dt


def summarize(
    db: str = "cats.db",
    hours: int = 24,
    start: str | None = None,
    end: str | None = None,
    output: str | None = None,
    model: str | None = None,
) -> None:
    """Query messages and ask Claude to summarize them in Hebrew.

    Args:
        db: Path to the SQLite database.
        hours: How many hours back to include (default: 24). Ignored if start is set.
        start: Range start, 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM'.
        end: Range end (default: now). A date-only value includes that whole day.
        output: File path to save the summary; prints to stdout if omitted.
        model: Claude model alias to use (e.g. 'sonnet', 'opus').
    """
    db_path = Path(db)
    if not db_path.exists():
        console.print(f"[red]Error:[/red] database '{db_path}' not found")
        sys.exit(1)

    use_range = start is not None or end is not None
    if use_range and start is None:
        console.print("[red]Error:[/red] --end requires --start")
        sys.exit(1)
    if start is not None:
        since_dt = parse_bound(start, is_end=False)
        until_dt = parse_bound(end, is_end=True) if end else datetime.now()
        label = f"{since_dt:%Y-%m-%d %H:%M} – {until_dt:%Y-%m-%d %H:%M}"
        prompt_span = f"מ-{since_dt:%Y-%m-%d %H:%M} עד {until_dt:%Y-%m-%d %H:%M}"
        title = f"סיכום — {label}"
    else:
        since_dt = datetime.now() - timedelta(hours=hours)
        until_dt = None
        label = f"the last {hours}h"
        prompt_span = f"מ-{hours} השעות האחרונות"
        title = f"סיכום — {hours}h אחרונות"

    since = since_dt.strftime("%Y-%m-%d %H:%M:%S")
    until = until_dt.strftime("%Y-%m-%d %H:%M:%S") if until_dt else None

    with console.status(f"[bold]Querying messages from {label}…[/bold]"):
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        query = "SELECT ts, sender, body FROM messages WHERE ts >= ? AND is_system = 0"
        params: tuple[str, ...] = (since,)
        if until:
            query += " AND ts < ?"
            params += (until,)
        rows = cur.execute(query + " ORDER BY ts", params).fetchall()
        con.close()

    if not rows:
        console.print(f"[yellow]No messages found in {label}.[/yellow]")
        return

    console.print(f"[green]✓[/green] Found [bold]{len(rows):,}[/bold] messages.")

    chat_text = "\n".join(f"[{ts}] {sender}: {body}" for ts, sender, body in rows)

    prompt = (
        f"להלן שיחת וואטסאפ {prompt_span}.\n"
        "אנא כתוב סיכום קצר של השיחה בעברית, \n\n"
        f"{chat_text}"
    )

    cmd = ["claude", "-p", prompt]
    if model:
        cmd += ["--model", model]

    model_label = model or "default"
    with console.status(f"[bold]Asking Claude for a summary ({model_label})…[/bold]"):
        result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        console.print(f"[red]claude exited with code {result.returncode}:[/red]")
        console.print(result.stderr)
        sys.exit(1)

    summary = result.stdout.strip()

    if output:
        out_path = Path(output)
        out_path.write_text(summary, encoding="utf-8")
        console.print(f"[green]✓[/green] Summary saved to [bold]{out_path}[/bold]")
    else:
        console.print(Panel(summary, title=title, border_style="blue"))


if __name__ == "__main__":
    fire.Fire(summarize)
