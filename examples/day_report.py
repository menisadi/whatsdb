# /// script
# dependencies = ["fire", "python-bidi"]
# ///

"""Per-day report for a WhatsApp chat: stats, and topics via distinctive keywords."""

import itertools
import math
import re
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

import analyze_chat as ac
import fire
from analyze_chat import bidi

_WORD_RE = re.compile(r"[֐-׿a-zA-Z']{2,}")
_URL_RE = re.compile(r"https?://\S+")
_EMOJI_RE = re.compile("[\U0001f300-\U0001faff☀-➿]")
_HE_PREFIXES = "והבלמשכ"


@dataclass
class Msg:
    ts: datetime
    sender: str
    body: str
    media: bool


def load(db: str, utc_offset: int) -> list[Msg]:
    con = sqlite3.connect(db)
    rows = con.execute(
        "SELECT ts, sender, body FROM messages"
        " WHERE is_system = 0 AND sender IS NOT NULL ORDER BY ts"
    ).fetchall()
    con.close()
    shift = timedelta(hours=utc_offset)
    msgs = []
    for ts, sender, body in rows:
        if body.strip().lower() in {"null", "this message was deleted"}:
            continue
        media = body.strip().lower() == "<media omitted>"
        msgs.append(Msg(datetime.fromisoformat(ts) + shift, sender, body, media))
    return msgs


def setup_names(
    msgs: list[Msg], aliases: str, aliases_file: str | None, no_bidi: bool
) -> tuple[dict[str, str], set[str]]:
    if no_bidi:
        ac._bidi_enabled = False
    display = ac.build_display_names({m.sender for m in msgs})
    name_tokens = {t.lower() for n in display for t in n.split()}
    if aliases_file is not None:
        with open(aliases_file, encoding="utf-8") as f:
            ac.apply_aliases(
                display,
                [line.split("#")[0].strip() for line in f if "=" in line.split("#")[0]],
            )
    if aliases:
        ac.apply_aliases(display, aliases.split(","))
    return display, name_tokens


def tokens(text: str, exclude: set[str]) -> list[str]:
    out = []
    for w in _WORD_RE.findall(_URL_RE.sub(" ", text).lower()):
        if len(w) > 4 and w[0] in _HE_PREFIXES and "֐" <= w[0] <= "׿":
            w = w[1:]
        if len(w) > 2 and w not in ac.STOP_WORDS and w not in exclude:
            out.append(w)
    return out


def count_tokens(msgs: list[Msg], exclude: set[str]) -> Counter[str]:
    c: Counter[str] = Counter()
    for m in msgs:
        if not m.media:
            c.update(tokens(m.body, exclude))
    return c


def distinctive(
    target: Counter[str],
    background: Counter[str],
    n: int,
    min_count: int = 2,
    alpha0: float = 500.0,
) -> list[tuple[str, int]]:
    """Rank words by log-odds z-score vs. the background (Monroe et al., informative prior)."""
    n_t, n_b = sum(target.values()), sum(background.values())
    if not n_t or not n_b:
        return []
    scored = []
    for w, y_t in target.items():
        if y_t < min_count:
            continue
        a = alpha0 * background[w] / n_b + 0.01
        y_b = background[w]
        d = math.log((y_t + a) / (n_t + alpha0 - y_t - a)) - math.log(
            (y_b + a) / (n_b + alpha0 - y_b - a)
        )
        z = d / math.sqrt(1 / (y_t + a) + 1 / (y_b + a))
        scored.append((z, w, y_t))
    scored.sort(reverse=True)
    return [(w, c) for _, w, c in scored[:n]]


def select_day(msgs: list[Msg], date: str) -> tuple[list[Msg], list[Msg]]:
    day = [m for m in msgs if m.ts.strftime("%Y-%m-%d") == date]
    rest = [m for m in msgs if m.ts.strftime("%Y-%m-%d") != date]
    if not day:
        sys.exit(f"No messages on {date}")
    return day, rest


def split_sessions(day: list[Msg], gap: int) -> list[list[Msg]]:
    sessions: list[list[Msg]] = [[day[0]]]
    for prev, cur in itertools.pairwise(day):
        if cur.ts - prev.ts >= timedelta(minutes=gap):
            sessions.append([])
        sessions[-1].append(cur)
    return sessions


def fmt_words(words: list[tuple[str, int]], counts: bool) -> str:
    return bidi(", ".join(f"{w}({c})" if counts else w for w, c in words))


class DayReport:
    """Report for a single day of chat history.

    Commands:
        stats  DATE   Message counts per speaker, hourly activity, extras.
        topics DATE   Distinctive keywords for the day and per conversation.

    Run `day_report.py <command> --help` for options.
    """

    def stats(
        self,
        date: str,
        db: str = "cats.db",
        utc_offset: int = 0,
        aliases: str = "",
        aliases_file: str | None = None,
        no_bidi: bool = False,
    ) -> None:
        """Message counts per speaker, hourly activity and a few extras.

        Args:
            date:         Day to report, YYYY-MM-DD.
            db:           Path to the SQLite database.
            utc_offset:   Hours to shift timestamps before picking the day.
            aliases:      Override display names inline, e.g. "Full Name=Label".
            aliases_file: Path to aliases file. Lines: "Full Name=Label".
            no_bidi:      Disable bidi reordering.
        """
        msgs = load(db, utc_offset)
        display, _ = setup_names(msgs, aliases, aliases_file, no_bidi)
        day, _ = select_day(msgs, date)
        text = [m for m in day if not m.media]

        print(f"{date}: {len(day)} messages ({len(day) - len(text)} media)")
        print(f"first {day[0].ts:%H:%M}  last {day[-1].ts:%H:%M}", end="")
        gaps = [(b.ts - a.ts, a, b) for a, b in itertools.pairwise(day)]
        if gaps:
            gap, a, b = max(gaps, key=lambda g: g[0])
            print(f"  longest silence {gap} ({a.ts:%H:%M}-{b.ts:%H:%M})")
        else:
            print()
        print(
            f"opened by {bidi(display[day[0].sender])}, "
            f"closed by {bidi(display[day[-1].sender])}"
        )
        print(
            f"links {sum(bool(_URL_RE.search(m.body)) for m in text)}  "
            f"questions {sum('?' in m.body for m in text)}  "
            f"emoji {sum(len(_EMOJI_RE.findall(m.body)) for m in text)}"
        )

        print(f"\n{'Speaker':<16} {'Msgs':>5} {'Share':>6} {'Avg words':>10}")
        by_sender: Counter[str] = Counter(m.sender for m in day)
        for sender, cnt in by_sender.most_common():
            own = [m for m in text if m.sender == sender]
            avg = sum(len(m.body.split()) for m in own) / len(own) if own else 0
            name = bidi(display[sender])
            print(f"{name:<16} {cnt:>5} {cnt / len(day):>6.0%} {avg:>10.1f}")

        print("\nHour  Messages")
        hours = Counter(m.ts.hour for m in day)
        peak = max(hours.values())
        for h in range(24):
            if hours[h]:
                print(f"{h:02d}    {'█' * math.ceil(hours[h] / peak * 40)} {hours[h]}")

    def topics(
        self,
        date: str,
        db: str = "cats.db",
        top: int = 10,
        session_words: int = 4,
        gap: int = 10,
        min_session: int = 5,
        counts: bool = False,
        utc_offset: int = 0,
        aliases: str = "",
        aliases_file: str | None = None,
        no_bidi: bool = False,
    ) -> None:
        """Distinctive keywords for the day, overall and per conversation.

        Words are ranked by how much more frequent they are on this day than in
        the rest of the chat, so always-common words drop out.

        Args:
            date:          Day to report, YYYY-MM-DD.
            db:            Path to the SQLite database.
            top:           Keywords for the whole day (default: 10).
            session_words: Keywords per conversation (default: 4).
            gap:           Minutes of silence that start a new conversation (default: 10).
            min_session:   Skip keywords for conversations shorter than this (default: 5).
            counts:        Show occurrence counts next to keywords.
            utc_offset:    Hours to shift timestamps before picking the day.
            aliases:       Override display names inline, e.g. "Full Name=Label".
            aliases_file:  Path to aliases file. Lines: "Full Name=Label".
            no_bidi:       Disable bidi reordering.
        """
        msgs = load(db, utc_offset)
        display, names = setup_names(msgs, aliases, aliases_file, no_bidi)
        day, rest = select_day(msgs, date)
        background = count_tokens(rest, names)

        print(f"{date}: {len(day)} messages")
        words = distinctive(count_tokens(day, names), background, top)
        print(f"Day keywords: {fmt_words(words, counts)}\n")

        for s in split_sessions(day, gap):
            who = Counter(m.sender for m in s)
            people = " ".join(f"{bidi(display[n])}({c})" for n, c in who.most_common(3))
            line = f"{s[0].ts:%H:%M}-{s[-1].ts:%H:%M}  {len(s):>3} msgs  {people}"
            if len(s) >= min_session:
                sw = distinctive(count_tokens(s, names), background, session_words)
                line += f"  | {fmt_words(sw, counts)}"
            print(line)


if __name__ == "__main__":
    fire.Fire(DayReport)
