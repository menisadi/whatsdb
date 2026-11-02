# /// script
# dependencies = ["fire", "python-bidi"]
# ///

import csv
import math
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

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


_PERIOD_SQL = {
    "day": "DATE(ts)",
    "week": "strftime('%Y-%W', ts)",
    "month": "strftime('%Y-%m', ts)",
}


def parse(
    db: str = "cats.db",
    period: str = "day",
    utc_offset: int = 0,
) -> tuple[defaultdict[str, dict[str, Any]], dict[str, str]]:
    if period not in _PERIOD_SQL:
        raise ValueError(f"period must be one of: {', '.join(_PERIOD_SQL)}")
    messages_by_day: defaultdict[str, dict[str, Any]] = defaultdict(
        lambda: {"messages": [], "senders": Counter()}
    )
    all_senders: set[str] = set()
    ts_expr = f"datetime(ts, '{utc_offset:+d} hours')" if utc_offset else "ts"
    period_expr = _PERIOD_SQL[period].replace("ts", ts_expr)
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.execute(
        f"SELECT {period_expr}, sender, body FROM messages"
        + " WHERE is_system = 0 AND sender IS NOT NULL"
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


def fmt_senders(
    sender_counts: Counter[str], display_names: dict[str, str], n: int
) -> str:
    return " ".join(
        f"{bidi(display_names.get(name, name.split()[0]))}({cnt})"
        for name, cnt in sender_counts.most_common(n)
    )


def _tokenize(msgs: list[str], exclude: set[str]) -> list[str]:
    all_text = " ".join(msgs)
    words = re.findall(r"[\u0590-\u05ffa-zA-Z']{2,}", all_text.lower())
    return [w for w in words if w not in STOP_WORDS and w not in exclude and len(w) > 2]


def top_words_for(
    msgs: list[str],
    n: int,
    exclude: set[str] | None = None,
    df: Counter[str] | None = None,
    n_docs: int = 0,
) -> list[tuple[str, int]]:
    """Top words by raw count, or by TF-IDF when df (document frequency) is given."""
    if exclude is None:
        exclude = set()
    tf = Counter(_tokenize(msgs, exclude))
    if df is None:
        return tf.most_common(n)
    scored = sorted(
        tf.items(), key=lambda x: x[1] * math.log(n_docs / df[x[0]]), reverse=True
    )
    return scored[:n]


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
    aliases_file: str | None = None,
    no_bidi: bool = False,
    period: str = "day",
    utc_offset: int = 0,
    rank_by: str = "messages",
    long_pct: int = 90,
    show_long: bool = False,
    rank_words: str = "count",
) -> None:
    """Analyze WhatsApp chat history and show busiest days with top keywords.

    Args:
        db:           Path to the SQLite database.
        top:          Number of periods to show (default: 10).
        top_words:    Number of top words per period (default: 5).
        csv_output:   Print output as CSV instead of a table.
        counts:       Show occurrence count next to each top word.
        per_user:     Add a column showing per-sender message counts.
        top_senders:  Number of top senders to show when --per_user is set (default: 3).
        aliases:      Override display names inline, e.g. "Meni Sadigurschi=מני,Other=X".
        aliases_file: Path to aliases file. Lines: "Full Name=Label".
        no_bidi:      Disable bidi reordering (useful when pasting into RTL-aware apps).
        period:       Grouping period: day, week, or month (default: day).
        utc_offset:   Hours to shift timestamps before grouping (e.g. 3 or -5).
        rank_by:      Ranking metric: messages (default) or long (count of long messages).
        long_pct:     A message is "long" if its word count exceeds this percentile
                      of all messages (default: 90).
        show_long:    Show the long-message column (always shown when --rank_by long).
        rank_words:   Top-word ranking: count (default) or tfidf (words distinctive
                      to the period vs. the whole chat).
    """
    global _bidi_enabled
    if no_bidi:
        _bidi_enabled = False
    messages_by_day, display_names = parse(db, period, utc_offset)
    name_tokens: set[str] = {
        token.lower() for name in display_names for token in name.split()
    }
    if aliases_file is not None:
        with open(aliases_file, encoding="utf-8") as f:
            apply_aliases(
                display_names,
                [line.split("#")[0].strip() for line in f if "=" in line.split("#")[0]],
            )
    if aliases:
        apply_aliases(display_names, aliases.split(","))
    if rank_by not in ("messages", "long"):
        raise ValueError("rank_by must be one of: messages, long")
    if not 0 <= long_pct < 100:
        raise ValueError("long_pct must be in [0, 100)")
    if rank_words not in ("count", "tfidf"):
        raise ValueError("rank_words must be one of: count, tfidf")
    df: Counter[str] | None = None
    if rank_words == "tfidf":
        df = Counter()
        for day in messages_by_day.values():
            df.update(set(_tokenize(day["messages"], name_tokens)))
    word_counts_all = sorted(
        len(m.split()) for day in messages_by_day.values() for m in day["messages"]
    )
    long_threshold = (
        word_counts_all[
            min(len(word_counts_all) - 1, len(word_counts_all) * long_pct // 100)
        ]
        if word_counts_all
        else 0
    )
    for day in messages_by_day.values():
        day["long"] = sum(len(m.split()) > long_threshold for m in day["messages"])
    metric = "long" if rank_by == "long" else None
    ranked = sorted(
        messages_by_day.items(),
        key=lambda x: x[1]["long"] if metric else len(x[1]["messages"]),
        reverse=True,
    )[:top]
    show_long = show_long or rank_by == "long"
    rows = [
        (
            rank,
            date,
            len(day["messages"]),
            day["long"],
            top_words_for(
                day["messages"], top_words, name_tokens, df, len(messages_by_day)
            ),
            day["senders"],
        )
        for rank, (date, day) in enumerate(ranked, 1)
    ]

    def fmt_words(word_counts: list[tuple[str, int]]) -> str:
        if counts:
            return bidi(", ".join(f"{w}({c})" for w, c in word_counts))
        return bidi(", ".join(w for w, _ in word_counts))

    if show_long:
        print(
            f"Long = more than {long_threshold} words (p{long_pct} of all messages)",
            file=sys.stderr if csv_output else sys.stdout,
        )

    if csv_output:
        writer = csv.writer(sys.stdout)
        header = ["rank", "date", "messages"]
        if show_long:
            header.append("long")
        header.append("top_words")
        if per_user:
            header.append("per_user")
        writer.writerow(header)
        for rank, date, count, long_count, word_counts, senders in rows:
            row = [rank, date, count]
            if show_long:
                row.append(long_count)
            row.append(fmt_words(word_counts))
            if per_user:
                row.append(fmt_senders(senders, display_names, top_senders))
            writer.writerow(row)
    else:
        period_label = period.capitalize()
        header = f"{'Rank':<5} {period_label:<14} {'Messages':<10} "
        if show_long:
            header += f"{'Long':<8}"
        header += "Top words"
        if per_user:
            header += f"  {'Per user'}"
        print(header)
        print("-" * (90 if per_user else 70))
        for rank, date, count, long_count, word_counts, senders in rows:
            line = f"{rank:<5} {date:<14} {count:<10} "
            if show_long:
                line += f"{long_count:<8}"
            line += f"{fmt_words(word_counts):<30}"
            if per_user:
                line += f"  {fmt_senders(senders, display_names, top_senders)}"
            print(line)


if __name__ == "__main__":
    fire.Fire(analyze)
