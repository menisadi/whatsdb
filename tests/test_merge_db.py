"""Tests for merge_db."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from build_db import Message, _build_db
from merge_db import _merge


def _read_rows(db: Path) -> list[tuple[str, str | None, str, int]]:
    con = sqlite3.connect(db)
    try:
        return con.execute(
            "SELECT ts, sender, body, is_system FROM messages ORDER BY ts, body"
        ).fetchall()
    finally:
        con.close()


def _fts_count(db: Path) -> int:
    con = sqlite3.connect(db)
    try:
        return int(con.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0])
    finally:
        con.close()


def test_merge_inserts_new_rows_and_skips_duplicates(tmp_path: Path) -> None:
    target = tmp_path / "target.db"
    source = tmp_path / "source.db"

    shared = Message(
        ts="2026-06-05 14:30:45", sender="Alice", body="shared", is_system=False
    )
    target_only = Message(
        ts="2026-06-05 14:31:00", sender="Alice", body="target only", is_system=False
    )
    source_only = Message(
        ts="2026-06-05 14:32:00", sender="Bob", body="source only", is_system=False
    )

    _build_db(target, [shared, target_only])
    _build_db(source, [shared, source_only])

    exit_code = _merge(target, source)

    assert exit_code == 0
    rows = _read_rows(target)
    assert rows == [
        ("2026-06-05 14:30:45", "Alice", "shared", 0),
        ("2026-06-05 14:31:00", "Alice", "target only", 0),
        ("2026-06-05 14:32:00", "Bob", "source only", 0),
    ]
    assert _fts_count(target) == len(rows)


def test_merge_dedups_null_sender(tmp_path: Path) -> None:
    target = tmp_path / "target.db"
    source = tmp_path / "source.db"

    system_msg = Message(
        ts="2026-06-05 14:30:00", sender=None, body="system event", is_system=True
    )

    _build_db(target, [system_msg])
    _build_db(source, [system_msg])

    exit_code = _merge(target, source)

    assert exit_code == 0
    assert _read_rows(target) == [("2026-06-05 14:30:00", None, "system event", 1)]
    assert _fts_count(target) == 1


def test_merge_empty_source(tmp_path: Path) -> None:
    target = tmp_path / "target.db"
    source = tmp_path / "source.db"

    only = Message(ts="2026-06-05 14:30:45", sender="Alice", body="hi", is_system=False)
    _build_db(target, [only])
    _build_db(source, [])

    exit_code = _merge(target, source)

    assert exit_code == 0
    assert _read_rows(target) == [("2026-06-05 14:30:45", "Alice", "hi", 0)]
    assert _fts_count(target) == 1


def test_merge_deduplicates_mixed_precision(tmp_path: Path) -> None:
    target = tmp_path / "target.db"
    source = tmp_path / "source.db"

    # Same message: old-format export stores HH:MM:00, new-format stores exact seconds
    old_fmt = Message(
        ts="2026-06-05 14:30:00", sender="Alice", body="hello", is_system=False
    )
    new_fmt = Message(
        ts="2026-06-05 14:30:45", sender="Alice", body="hello", is_system=False
    )

    _build_db(target, [old_fmt])
    _build_db(source, [new_fmt])

    exit_code = _merge(target, source)

    assert exit_code == 0
    assert len(_read_rows(target)) == 1


def test_merge_keeps_distinct_messages_same_minute(tmp_path: Path) -> None:
    target = tmp_path / "target.db"
    source = tmp_path / "source.db"

    msg1 = Message(
        ts="2026-06-05 14:30:10", sender="Alice", body="first", is_system=False
    )
    msg2 = Message(
        ts="2026-06-05 14:30:50", sender="Alice", body="second", is_system=False
    )

    _build_db(target, [msg1])
    _build_db(source, [msg2])

    exit_code = _merge(target, source)

    assert exit_code == 0
    assert len(_read_rows(target)) == 2


def test_merge_into_empty_target(tmp_path: Path) -> None:
    target = tmp_path / "target.db"
    source = tmp_path / "source.db"

    msg = Message(ts="2026-06-05 14:30:45", sender="Alice", body="hi", is_system=False)
    _build_db(target, [])
    _build_db(source, [msg])

    exit_code = _merge(target, source)

    assert exit_code == 0
    assert _read_rows(target) == [("2026-06-05 14:30:45", "Alice", "hi", 0)]
    assert _fts_count(target) == 1
