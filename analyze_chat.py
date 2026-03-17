# /// script
# dependencies = ["fire"]
# ///

import re
import csv
import sys
from collections import defaultdict, Counter

import fire


def load_stopwords(path: str = "stopwords.txt") -> set[str]:
    words = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            word = line.split("#")[0].strip().lower()
            if word:
                words.add(word)
    return words


STOP_WORDS = load_stopwords()

MSG_RE = re.compile(r"^(\d{2}/\d{2}/\d{4}), \d{2}:\d{2} - [^:]+: (.+)$")
DATE_RE = re.compile(r"^(\d{2}/\d{2}/\d{4}),")


def parse(file: str = "cats.txt") -> defaultdict[str, list[str]]:
    messages_by_day = defaultdict(list)
    current_date = None
    with open(file, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            m = MSG_RE.match(line)
            if m:
                current_date = m.group(1)
                text = m.group(2)
                if text.strip().lower() in (
                    "<media omitted>",
                    "null",
                    "this message was deleted",
                ):
                    continue
                messages_by_day[current_date].append(text)
            elif current_date and not DATE_RE.match(line):
                if messages_by_day[current_date]:
                    messages_by_day[current_date][-1] += " " + line
    return messages_by_day


def top_words_for(msgs: list[str], n: int) -> list[tuple[str, int]]:
    all_text = " ".join(msgs)
    words = re.findall(r"[\u0590-\u05ffa-zA-Z']{2,}", all_text.lower())
    words = [w for w in words if w not in STOP_WORDS and len(w) > 2]
    return Counter(words).most_common(n)


def analyze(
    file: str = "cats.txt",
    top: int = 10,
    top_words: int = 5,
    csv_output: bool = False,
    counts: bool = False,
) -> None:
    """Analyze WhatsApp chat history and show busiest days with top keywords.

    Args:
        file:        Path to the chat export file.
        top:         Number of days to show (default: 10).
        top_words:   Number of top words per day (default: 5).
        csv_output:  Print output as CSV instead of a table.
        counts:      Show occurrence count next to each top word.
    """
    messages_by_day = parse(file)
    ranked = sorted(messages_by_day.items(), key=lambda x: len(x[1]), reverse=True)[
        :top
    ]
    rows = [
        (rank, date, len(msgs), top_words_for(msgs, top_words))
        for rank, (date, msgs) in enumerate(ranked, 1)
    ]

    def fmt_words(word_counts: list[tuple[str, int]]) -> str:
        if counts:
            return ", ".join(f"{w}({c})" for w, c in word_counts)
        return ", ".join(w for w, _ in word_counts)

    if csv_output:
        writer = csv.writer(sys.stdout)
        writer.writerow(["rank", "date", "messages", "top_words"])
        for rank, date, count, word_counts in rows:
            writer.writerow([rank, date, count, fmt_words(word_counts)])
    else:
        print(f"{'Rank':<5} {'Date':<14} {'Messages':<10} Top words")
        print("-" * 70)
        for rank, date, count, word_counts in rows:
            print(f"{rank:<5} {date:<14} {count:<10} {fmt_words(word_counts)}")


if __name__ == "__main__":
    fire.Fire(analyze)
