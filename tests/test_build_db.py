"""Tests for build_db."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from build_db import Message, _build_db, _parse_file, _parse_ts


def test_parse_ts_new_format_with_seconds() -> None:
    assert _parse_ts("05/06/2026, 14:30:45") == "2026-06-05 14:30:45"


def test_parse_ts_old_format_without_seconds() -> None:
    assert _parse_ts("05/06/2026, 14:30") == "2026-06-05 14:30:00"


def test_parse_file_regular_system_and_multiline(tmp_path: Path) -> None:
    chat = tmp_path / "chat.txt"
    chat.write_text(
        "[05/06/2026, 14:30:45] Alice: Hello\n"
        "[05/06/2026, 14:31:00] Messages and calls are end-to-end encrypted.\n"
        "[05/06/2026, 14:32:10] Bob: line one\n"
        "line two\n"
        "line three\n",
        encoding="utf-8",
    )

    messages = _parse_file(chat)

    assert len(messages) == 3

    assert messages[0] == Message(
        ts="2026-06-05 14:30:45",
        sender="Alice",
        body="Hello",
        is_system=False,
    )

    assert messages[1].sender is None
    assert messages[1].is_system is True
    assert messages[1].body == "Messages and calls are end-to-end encrypted."

    assert messages[2].sender == "Bob"
    assert messages[2].body == "line one\nline two\nline three"
    assert messages[2].is_system is False


def test_parse_file_old_format(tmp_path: Path) -> None:
    chat = tmp_path / "chat.txt"
    chat.write_text(
        "05/06/2026, 14:30 - Alice: Hi there\n",
        encoding="utf-8",
    )

    messages = _parse_file(chat)

    assert len(messages) == 1
    assert messages[0].ts == "2026-06-05 14:30:00"
    assert messages[0].sender == "Alice"
    assert messages[0].body == "Hi there"


def test_parse_file_mixed_precision_in_one_file(tmp_path: Path) -> None:
    chat = tmp_path / "chat.txt"
    chat.write_text(
        "05/06/2026, 14:30 - Alice: old-style line\n"
        "[05/06/2026, 14:31:22] Bob: new-style line\n"
        "05/06/2026, 14:32 - Alice: another old line\n",
        encoding="utf-8",
    )

    messages = _parse_file(chat)

    assert [(m.ts, m.sender, m.body) for m in messages] == [
        ("2026-06-05 14:30:00", "Alice", "old-style line"),
        ("2026-06-05 14:31:22", "Bob", "new-style line"),
        ("2026-06-05 14:32:00", "Alice", "another old line"),
    ]


def test_build_db_writes_schema_and_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "out.db"
    messages = [
        Message(
            ts="2026-06-05 14:30:45", sender="Alice", body="Hello", is_system=False
        ),
        Message(
            ts="2026-06-05 14:31:00", sender=None, body="system event", is_system=True
        ),
    ]

    _build_db(db_path, messages)

    con = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"messages", "messages_fts"}.issubset(tables)

        indexes = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert {"idx_ts", "idx_sender", "idx_dedup"}.issubset(indexes)

        rows = con.execute(
            "SELECT ts, sender, body, is_system FROM messages ORDER BY id"
        ).fetchall()
        assert rows == [
            ("2026-06-05 14:30:45", "Alice", "Hello", 0),
            ("2026-06-05 14:31:00", None, "system event", 1),
        ]

        fts_count = con.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
        assert fts_count == 2
    finally:
        con.close()


def test_build_db_overwrites_existing(tmp_path: Path) -> None:
    db_path = tmp_path / "out.db"

    _build_db(
        db_path,
        [
            Message(
                ts="2026-06-05 14:30:45", sender="Alice", body="first", is_system=False
            )
        ],
    )
    _build_db(
        db_path,
        [
            Message(
                ts="2026-06-05 14:31:00", sender="Bob", body="second", is_system=False
            )
        ],
    )

    con = sqlite3.connect(db_path)
    try:
        rows = con.execute("SELECT sender, body FROM messages").fetchall()
        assert rows == [("Bob", "second")]
    finally:
        con.close()
