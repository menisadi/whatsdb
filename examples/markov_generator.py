# /// script
# dependencies = ["markovify", "fire"]
# ///

import random
import re
import sqlite3
from collections import Counter
from pathlib import Path

import fire
import markovify

_OMITTED = {"<media omitted>", "null", "this message was deleted"}


def load_messages_by_sender(db: str, top_senders: int) -> dict[str, list[str]]:
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.execute(
        "SELECT sender, body FROM messages WHERE is_system = 0 AND sender IS NOT NULL"
    )
    rows = [
        (sender, body)
        for sender, body in cur.fetchall()
        if body.strip().lower() not in _OMITTED
    ]
    con.close()

    counts = Counter(sender for sender, _ in rows)
    top = {sender for sender, _ in counts.most_common(top_senders)}
    result: dict[str, list[str]] = {s: [] for s in top}
    for sender, body in rows:
        if sender in top:
            result[sender].append(body)
    return result


def build_display_names(senders: set[str]) -> dict[str, str]:
    """Return shortest unambiguous label per sender (first name, or first+last on collision)."""
    first_names: dict[str, list[str]] = {}
    for name in senders:
        first_names.setdefault(name.split()[0], []).append(name)
    result = {}
    for name in senders:
        parts = name.split()
        first = parts[0]
        if len(first_names[first]) == 1:
            result[name] = first
        else:
            result[name] = " ".join(parts[:2]) if len(parts) > 1 else name
    return result


def generate(
    db: str = "cats.db",
    top_senders: int = 5,
    n: int = 5,
    state_size: int = 2,
    sender: str | None = None,
) -> None:
    """Train a per-sender Markov chain language model and generate sample messages.

    Args:
        db:           Path to the SQLite database (default: cats.db).
        top_senders:  Number of most active senders to model (default: 5).
        n:            Number of messages to generate per sender (default: 5).
        state_size:   Markov chain order — 1 for sparse data, 2 for more coherent output.
        sender:       Generate only for this sender (substring match, case-insensitive).
    """
    db_path = Path(db)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db}")

    print(f"Loading messages from {db}...")
    messages_by_sender = load_messages_by_sender(db, top_senders)
    counts = Counter({s: len(msgs) for s, msgs in messages_by_sender.items()})

    if sender:
        matches = [s for s in messages_by_sender if sender.lower() in s.lower()]
        if not matches:
            raise ValueError(
                f"No sender matching '{sender}' found in top {top_senders}"
            )
        messages_by_sender = {s: messages_by_sender[s] for s in matches}

    display = build_display_names(set(messages_by_sender.keys()))
    print(
        f"Training Markov chain (state_size={state_size}) for {len(messages_by_sender)} sender(s):\n"
    )

    for name, msgs in sorted(messages_by_sender.items(), key=lambda x: -counts[x[0]]):
        print(f"--- {display[name]} ({counts[name]:,} messages) ---")
        try:
            model = markovify.NewlineText("\n".join(msgs), state_size=state_size)
        except Exception:
            print("  (not enough data to build a model)\n")
            continue

        generated = 0
        for _ in range(n * 20):
            if generated >= n:
                break
            sentence = model.make_sentence(tries=10)
            if sentence:
                print(f"  {sentence}")
                generated += 1

        if generated == 0:
            print("  (corpus too sparse to generate — try --state_size=1)")
        print()


_SKIP = {
    "את",
    "אני",
    "אתה",
    "הוא",
    "היא",
    "אנחנו",
    "הם",
    "הן",
    "של",
    "על",
    "עם",
    "כי",
    "אם",
    "לא",
    "כן",
    "זה",
    "זו",
    "יש",
    "אין",
    "the",
    "a",
    "an",
    "is",
    "it",
    "i",
    "you",
    "we",
    "to",
    "in",
    "of",
    "and",
    "or",
    "but",
}
_WORD_RE = re.compile(r"[^\W\d_]{3,}", re.UNICODE)


def _make_sentence(model: markovify.NewlineText, prev: str | None) -> str:
    if prev:
        words = [w for w in _WORD_RE.findall(prev.lower()) if w not in _SKIP]
        random.shuffle(words)
        for word in words:
            try:
                result = model.make_sentence_with_start(word, tries=10, strict=False)
                if result:
                    return result
            except (KeyError, markovify.text.ParamError):
                continue
    for _ in range(30):
        result = model.make_sentence(tries=10)
        if result:
            return result
    return "(...)"


def converse(
    db: str = "cats.db",
    senders: int = 2,
    turns: int = 20,
    state_size: int = 2,
    coherent: bool = False,
) -> None:
    """Simulate a conversation by alternating between per-sender Markov chain models.

    Args:
        db:           Path to the SQLite database (default: cats.db).
        senders:      Number of participants — picks the most active senders (default: 2).
        turns:        Total number of messages to generate (default: 20).
        state_size:   Markov chain order — 1 for sparse data, 2 for more coherent output.
        coherent:     Seed each turn from keywords in the previous message (default: False).
    """
    db_path = Path(db)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db}")

    print(f"Loading messages from {db}...")
    messages_by_sender = load_messages_by_sender(db, senders)
    counts = Counter({s: len(msgs) for s, msgs in messages_by_sender.items()})

    print(
        f"Training Markov chain (state_size={state_size}) for {len(messages_by_sender)} sender(s)...\n"
    )

    display = build_display_names(set(messages_by_sender.keys()))
    models: dict[str, markovify.NewlineText] = {}
    for name, msgs in messages_by_sender.items():
        try:
            models[name] = markovify.NewlineText("\n".join(msgs), state_size=state_size)
        except Exception:
            print(f"  Skipping {display[name]}: not enough data.")

    if len(models) < 2:
        raise RuntimeError(
            "Need at least 2 senders with enough data to simulate a conversation."
        )

    participants = list(models.keys())
    print("-" * 50)

    last_sender: str | None = None
    last_sentence: str | None = None
    for _ in range(turns):
        pool = (
            [p for p in participants if p != last_sender]
            if last_sender
            else participants
        )
        pool_weights = [counts[p] for p in pool]
        speaker = random.choices(pool, weights=pool_weights, k=1)[0]
        last_sender = speaker

        sentence = _make_sentence(models[speaker], last_sentence if coherent else None)
        last_sentence = sentence if sentence != "(...)" else last_sentence

        print(f"  {display[speaker]:<16} {sentence}")

    print("-" * 50)


if __name__ == "__main__":
    fire.Fire({"generate": generate, "converse": converse})
