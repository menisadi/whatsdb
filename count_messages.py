#!/usr/bin/env python3
"""Count WhatsApp messages per day and output in termgraph-compatible CSV format."""

import re
import sys
from collections import Counter


def count_messages_per_day(chat_file: str, output_file: str):
    date_pattern = re.compile(r"^(\d{2}/\d{2}/\d{4}), \d{2}:\d{2} - ")
    counts: Counter[str] = Counter()

    with open(chat_file, encoding="utf-8") as f:
        for line in f:
            m = date_pattern.match(line)
            if m:
                counts[m.group(1)] += 1

    # Output one value per line for termgraph --histogram --bins
    sorted_dates = sorted(counts.keys(), key=lambda d: (d[6:10], d[3:5], d[0:2]))

    with open(output_file, "w") as out:
        out.write("date,count\n")
        for date in sorted_dates:
            out.write(f"{date},{counts[date]}\n")

    print(f"Wrote {len(sorted_dates)} days to {output_file}")


if __name__ == "__main__":
    chat = sys.argv[1] if len(sys.argv) > 1 else "cats.txt"
    output = sys.argv[2] if len(sys.argv) > 2 else "messages_per_day.csv"
    count_messages_per_day(chat, output)
