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


def summarize(
    db: str = "cats.db",
    hours: int = 24,
    output: str | None = None,
    model: str | None = None,
) -> None:
    """Query recent messages and ask Claude to summarize them in Hebrew.

    Args:
        db: Path to the SQLite database.
        hours: How many hours back to include (default: 24).
        output: File path to save the summary; prints to stdout if omitted.
        model: Claude model alias to use (e.g. 'sonnet', 'opus').
    """
    db_path = Path(db)
    if not db_path.exists():
        console.print(f"[red]Error:[/red] database '{db_path}' not found")
        sys.exit(1)

    since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

    with console.status(f"[bold]Querying messages from the last {hours}h…[/bold]"):
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        rows = cur.execute(
            "SELECT ts, sender, body FROM messages"
            " WHERE ts >= ? AND is_system = 0 ORDER BY ts",
            (since,),
        ).fetchall()
        con.close()

    if not rows:
        console.print(f"[yellow]No messages found in the last {hours} hours.[/yellow]")
        return

    console.print(f"[green]✓[/green] Found [bold]{len(rows):,}[/bold] messages.")

    chat_text = "\n".join(f"[{ts}] {sender}: {body}" for ts, sender, body in rows)

    prompt = (
        f"להלן שיחת וואטסאפ מ-{hours} השעות האחרונות.\n"
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
        console.print(
            Panel(summary, title=f"סיכום — {hours}h אחרונות", border_style="blue")
        )


if __name__ == "__main__":
    fire.Fire(summarize)
