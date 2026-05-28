"""Parse WhatsApp chat export(s) into a SQLite database."""

from __future__ import annotations

import argparse
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_MSG_RE = re.compile(r"^(\d{2}/\d{2}/\d{4}, \d{2}:\d{2}) - (.*)")


def _parse_ts(ts_str: str) -> str:
    return datetime.strptime(ts_str, "%d/%m/%Y, %H:%M").strftime("%Y-%m-%d %H:%M")


@dataclass
class Message:
    ts: str
    sender: str | None
    body: str
    is_system: bool


def _parse_file(path: Path) -> list[Message]:
    messages: list[Message] = []
    current: Message | None = None

    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            m = _MSG_RE.match(line)
            if m:
                if current is not None:
                    messages.append(current)
                ts = _parse_ts(m.group(1))
                content = m.group(2)
                if ": " in content:
                    sender, _, body = content.partition(": ")
                    current = Message(
                        ts=ts, sender=sender.strip(), body=body, is_system=False
                    )
                else:
                    current = Message(ts=ts, sender=None, body=content, is_system=True)
            elif current is not None:
                current.body += "\n" + line

    if current is not None:
        messages.append(current)

    return messages


def _build_db(db_path: Path, messages: list[Message]) -> None:
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.executescript("""
        DROP TABLE IF EXISTS messages_fts;
        DROP TABLE IF EXISTS messages;

        CREATE TABLE messages (
            id        INTEGER PRIMARY KEY,
            ts        TEXT NOT NULL,
            sender    TEXT,
            body      TEXT NOT NULL,
            is_system INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX idx_ts     ON messages(ts);
        CREATE INDEX idx_sender ON messages(sender);

        CREATE VIRTUAL TABLE messages_fts USING fts5(
            body, sender,
            content=messages,
            content_rowid=id,
            tokenize='unicode61'
        );
    """)
    cur.executemany(
        "INSERT INTO messages(ts, sender, body, is_system) VALUES (?, ?, ?, ?)",
        [(msg.ts, msg.sender, msg.body, int(msg.is_system)) for msg in messages],
    )
    cur.execute(
        "INSERT INTO messages_fts(rowid, body, sender) SELECT id, body, sender FROM messages"
    )
    con.commit()
    con.close()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Parse WhatsApp chat export(s) into SQLite"
    )
    ap.add_argument(
        "--input",
        nargs="+",
        default=["cats.txt"],
        metavar="FILE",
        help="One or more chat export files (default: cats.txt)",
    )
    ap.add_argument(
        "--output",
        default="cats.db",
        metavar="FILE",
        help="Output SQLite database (default: cats.db)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing database without prompting",
    )
    args = ap.parse_args()

    input_paths = [Path(p) for p in args.input]
    output_path = Path(args.output)

    for p in input_paths:
        if not p.exists():
            print(f"Error: input file '{p}' not found")
            return

    if output_path.exists() and not args.force:
        answer = input(f"'{output_path}' already exists. Overwrite? [y/N] ")
        if answer.strip().lower() != "y":
            print("Aborted.")
            return

    all_messages: list[Message] = []
    for p in input_paths:
        print(f"Parsing {p}...")
        msgs = _parse_file(p)
        print(f"  {len(msgs):,} messages")
        all_messages.extend(msgs)

    all_messages.sort(key=lambda m: m.ts)
    print(f"Total: {len(all_messages):,} messages")

    print(f"Writing {output_path}...")
    _build_db(output_path, all_messages)
    print("Done.")


if __name__ == "__main__":
    main()
