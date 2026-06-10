"""Merge a source WhatsApp SQLite database into a target, skipping duplicates."""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path


def _count(con: sqlite3.Connection, table: str) -> int:
    row = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return int(row[0])


def _merge(target: Path, source: Path) -> int:
    con = sqlite3.connect(target)
    try:
        con.execute("ATTACH ? AS upd", (str(source),))
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_dedup ON messages(STRFTIME('%Y-%m-%d %H:%M', ts), body, sender)"
        )

        before_main = _count(con, "messages")
        before_upd = _count(con, "upd.messages")
        print(f"  target {target.name}: {before_main:,} rows")
        print(f"  source {source.name}: {before_upd:,} rows")

        cur = con.execute(
            """
            INSERT INTO messages (ts, sender, body, is_system)
            SELECT u.ts, u.sender, u.body, u.is_system
            FROM upd.messages u
            WHERE NOT EXISTS (
                SELECT 1 FROM messages m
                WHERE STRFTIME('%Y-%m-%d %H:%M', m.ts) = STRFTIME('%Y-%m-%d %H:%M', u.ts)
                  AND m.body = u.body
                  AND m.sender IS u.sender
            )
            """
        )
        inserted = cur.rowcount
        skipped = before_upd - inserted
        con.commit()

        con.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
        con.commit()

        after_main = _count(con, "messages")
        after_fts = _count(con, "messages_fts")
        print(f"  inserted: {inserted:,}")
        print(f"  skipped (duplicates): {skipped:,}")
        print(f"  merged total: {after_main:,}")

        if after_fts != after_main:
            print(
                f"ERROR: messages_fts ({after_fts:,}) does not match messages "
                + f"({after_main:,}) — FTS rebuild may have failed",
                file=sys.stderr,
            )
            return 1

        return 0
    finally:
        try:
            con.execute("DETACH upd")
        except sqlite3.OperationalError:
            pass
        con.close()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Merge a WhatsApp SQLite DB into another, skipping duplicates"
    )
    ap.add_argument("target", help="Target DB to merge into (modified in place)")
    ap.add_argument("source", help="Source DB whose rows are merged in")
    ap.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip creating <target>.bak before merging",
    )
    args = ap.parse_args()

    target = Path(args.target)
    source = Path(args.source)

    if not target.exists():
        print(f"Error: target '{target}' not found", file=sys.stderr)
        sys.exit(1)
    if not source.exists():
        print(f"Error: source '{source}' not found", file=sys.stderr)
        sys.exit(1)

    if not args.no_backup:
        backup = target.with_suffix(target.suffix + ".bak")
        print(f"Backing up {target} -> {backup}")
        shutil.copy2(target, backup)

    print(f"Merging {source} into {target}...")
    sys.exit(_merge(target, source))


if __name__ == "__main__":
    main()
