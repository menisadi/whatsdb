# /// script
# dependencies = ["fire", "python-bidi"]
# ///

import re
import csv
import sqlite3
import sys
from collections import defaultdict, Counter
from pathlib import Path

import fire
from bidi.algorithm import get_display


def load_stopwords(path: str | None = None) -> set[str]:
    if path is None:
        path = str(Path(__file__).parent / "stopwords.txt")
    words = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            word = line.split("#")[0].strip().lower()
            if word:
                words.add(word)
    return words


STOP_WORDS = load_stopwords()

_OMITTED = {"<media omitted>", "null", "this message was deleted"}


def parse(db: str = "cats.db") -> tuple[defaultdict[str, dict], dict[str, str]]:
    messages_by_day: defaultdict[str, dict] = defaultdict(
        lambda: {"messages": [], "senders": Counter()}
    )
    all_senders: set[str] = set()
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.execute(
        "SELECT DATE(ts), sender, body FROM messages"
        " WHERE is_system = 0 AND sender IS NOT NULL"
    )
    for date, sender, body in cur.fetchall():
        if body.strip().lower() in _OMITTED:
            continue
        all_senders.add(sender)
        messages_by_day[date]["messages"].append(body)
        messages_by_day[date]["senders"][sender] += 1
    con.close()
    return messages_by_day, build_display_names(all_senders)


_bidi_enabled = True


def bidi(text: str) -> str:
    if _bidi_enabled and any("\u0590" <= c <= "\u05ff" for c in text):
        result = get_display(text)
        return result.decode("utf-8") if isinstance(result, bytes) else result
    return text


def build_display_names(all_senders: set[str]) -> dict[str, str]:
    """Return shortest unambiguous label for each sender (first name, else first+last)."""
    first_names: dict[str, list[str]] = {}
    for name in all_senders:
        first = name.split()[0]
        first_names.setdefault(first, []).append(name)
    result = {}
    for name in all_senders:
        parts = name.split()
        first = parts[0]
        if len(first_names[first]) == 1:
            result[name] = first
        else:
            result[name] = " ".join(parts[:2]) if len(parts) > 1 else name
    return result


def fmt_senders(sender_counts: Counter, display_names: dict[str, str], n: int) -> str:
    return " ".join(
        f"{bidi(display_names.get(name, name.split()[0]))}({cnt})"
        for name, cnt in sender_counts.most_common(n)
    )


def top_words_for(msgs: list[str], n: int) -> list[tuple[str, int]]:
    all_text = " ".join(msgs)
    words = re.findall(r"[\u0590-\u05ffa-zA-Z']{2,}", all_text.lower())
    words = [w for w in words if w not in STOP_WORDS and len(w) > 2]
    return Counter(words).most_common(n)


def apply_aliases(display_names: dict[str, str], pairs: list[str]) -> None:
    for pair in pairs:
        full, _, label = pair.partition("=")
        if full.strip() in display_names:
            display_names[full.strip()] = label.strip()


def analyze(
    db: str = "cats.db",
    top: int = 10,
    top_words: int = 5,
    csv_output: bool = False,
    counts: bool = False,
    per_user: bool = False,
    top_senders: int = 3,
    aliases: str = "",
    aliases_file: str = "aliases.txt",
    no_bidi: bool = False,
) -> None:
    """Analyze WhatsApp chat history and show busiest days with top keywords.

    Args:
        db:           Path to the SQLite database.
        top:          Number of days to show (default: 10).
        top_words:    Number of top words per day (default: 5).
        csv_output:   Print output as CSV instead of a table.
        counts:       Show occurrence count next to each top word.
        per_user:     Add a column showing per-sender message counts.
        top_senders:  Number of top senders to show when --per_user is set (default: 3).
        aliases:      Override display names inline, e.g. "Meni Sadigurschi=מני,Other=X".
        aliases_file: Path to aliases file (default: aliases.txt). Lines: "Full Name=Label".
        no_bidi:      Disable bidi reordering (useful when pasting into RTL-aware apps).
    """
    import os

    global _bidi_enabled
    if no_bidi:
        _bidi_enabled = False
    messages_by_day, display_names = parse(db)
    if os.path.exists(aliases_file):
        with open(aliases_file, encoding="utf-8") as f:
            apply_aliases(
                display_names,
                [line.split("#")[0].strip() for line in f if "=" in line.split("#")[0]],
            )
    if aliases:
        apply_aliases(display_names, aliases.split(","))
    ranked = sorted(
        messages_by_day.items(), key=lambda x: len(x[1]["messages"]), reverse=True
    )[:top]
    rows = [
        (
            rank,
            date,
            len(day["messages"]),
            top_words_for(day["messages"], top_words),
            day["senders"],
        )
        for rank, (date, day) in enumerate(ranked, 1)
    ]

    def fmt_words(word_counts: list[tuple[str, int]]) -> str:
        if counts:
            return bidi(", ".join(f"{w}({c})" for w, c in word_counts))
        return bidi(", ".join(w for w, _ in word_counts))

    if csv_output:
        writer = csv.writer(sys.stdout)
        header = ["rank", "date", "messages", "top_words"]
        if per_user:
            header.append("per_user")
        writer.writerow(header)
        for rank, date, count, word_counts, senders in rows:
            row = [rank, date, count, fmt_words(word_counts)]
            if per_user:
                row.append(fmt_senders(senders, display_names, top_senders))
            writer.writerow(row)
    else:
        header = f"{'Rank':<5} {'Date':<14} {'Messages':<10} Top words"
        if per_user:
            header += f"  {'Per user'}"
        print(header)
        print("-" * (90 if per_user else 70))
        for rank, date, count, word_counts, senders in rows:
            line = f"{rank:<5} {date:<14} {count:<10} {fmt_words(word_counts):<30}"
            if per_user:
                line += f"  {fmt_senders(senders, display_names, top_senders)}"
            print(line)


if __name__ == "__main__":
    fire.Fire(analyze)
