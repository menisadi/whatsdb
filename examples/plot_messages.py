#!/usr/bin/env python3
# /// script
# dependencies = ["matplotlib", "pandas", "seaborn", "typer", "python-bidi"]
# ///
"""Plot WhatsApp message frequency over time (seaborn version)."""

import itertools
import sqlite3
from enum import Enum
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
import typer
from bidi.algorithm import get_display

sns.set_theme()

app = typer.Typer(no_args_is_help=True)


class Period(str, Enum):
    day = "day"
    week = "week"
    month = "month"


_FREQ = {Period.day: "D", Period.week: "W", Period.month: "ME"}


def _load_timestamps(db: Path, since: pd.Timestamp | None = None) -> pd.DatetimeIndex:
    con = sqlite3.connect(db)
    df = pd.read_sql_query("SELECT ts FROM messages WHERE is_system = 0", con)
    con.close()
    index = pd.DatetimeIndex(pd.to_datetime(df["ts"], format="ISO8601"))
    if since is not None:
        index = index[index >= since]
    return index


def _parse_since(since: str | None) -> pd.Timestamp | None:
    if since is None:
        return None
    try:
        return pd.Timestamp(since)
    except ValueError as e:
        raise typer.BadParameter(f"invalid date: {since}") from e


def _bw_palette(n: int) -> list[str]:
    """Evenly spaced grayscale shades, avoiding near-white/near-black extremes."""
    if n == 1:
        return ["0.3"]
    lo, hi = 0.15, 0.7
    step = (hi - lo) / (n - 1)
    return [str(lo + i * step) for i in range(n)]


# seaborn's auto-generated dash cycle (from `style=`) isn't distinct enough past
# ~4 categories (some dash-dot variants look nearly identical) — pass this
# explicit list to seaborn's own `dashes=` param instead.
_BW_DASHES = [
    (),
    (5, 2),
    (1, 1.5),
    (6, 2, 1, 2),
    (2, 1),
    (8, 4),
    (5, 1, 1, 1, 1, 1),
    (1, 4),
]


@app.command()
def per_period(
    db: Path = typer.Argument(Path("cats.db"), help="SQLite database"),
    period: Period = typer.Option(
        Period.day, "--period", "-p", help="Aggregation period"
    ),
    smooth: int | None = typer.Option(
        None, "--smooth", "-s", help="Rolling mean window in periods (omit to disable)"
    ),
    colorblind: bool = typer.Option(
        False, "--colorblind", help="Use colorblind-friendly palette"
    ),
    bw: bool = typer.Option(False, "--bw", help="Render in grayscale/black-and-white"),
    export: bool = typer.Option(
        False, "--export", help="Print CSV to stdout instead of plotting"
    ),
    since: str | None = typer.Option(
        None,
        "--since",
        help="Only include messages on/after this date (e.g. 2024-06-01)",
    ),
    save: Path | None = typer.Option(
        None, "--save", help="Save the plot to this file instead of displaying it"
    ),
) -> None:
    """Plot message count per day, week, or month."""
    import csv
    import sys

    if colorblind and not bw:
        sns.set_palette("colorblind")
    index = _load_timestamps(db, _parse_since(since))
    counts = pd.Series(1, index=index).resample(_FREQ[period]).sum()

    if export:
        out = (
            counts.rolling(smooth, min_periods=1).mean()
            if smooth is not None
            else counts
        )
        writer = csv.writer(sys.stdout)
        writer.writerow(["date", "count"])
        for ts, val in out.items():
            writer.writerow([ts.date(), val])
        return

    _, ax = plt.subplots(figsize=(14, 5))
    sns.lineplot(
        x=counts.index,
        y=counts.values,
        alpha=0.4,
        label="raw",
        color="0.5" if bw else None,
        ax=ax,
    )
    if smooth is not None:
        smoothed = counts.rolling(smooth, min_periods=1).mean()
        sns.lineplot(
            x=smoothed.index,
            y=smoothed.values,
            label=f"{smooth}-period avg",
            color="0.0" if bw else None,
            linestyle="--" if bw else "-",
            ax=ax,
        )
        ax.legend()
    ax.set_title(f"Messages per {period.value}")
    ax.set_xlabel("Date")
    ax.set_ylabel("Messages")
    plt.tight_layout()
    if save is not None:
        plt.savefig(save)
    else:
        plt.show()


@app.command()
def sliding(
    db: Path = typer.Argument(Path("cats.db"), help="SQLite database"),
    window: int = typer.Option(12, "--window", "-w", help="Window size in hours"),
    colorblind: bool = typer.Option(
        False, "--colorblind", help="Use colorblind-friendly palette"
    ),
    bw: bool = typer.Option(False, "--bw", help="Render in grayscale/black-and-white"),
    since: str | None = typer.Option(
        None,
        "--since",
        help="Only include messages on/after this date (e.g. 2024-06-01)",
    ),
    save: Path | None = typer.Option(
        None, "--save", help="Save the plot to this file instead of displaying it"
    ),
) -> None:
    """Plot message count using a sliding window sum."""
    if colorblind and not bw:
        sns.set_palette("colorblind")
    index = _load_timestamps(db, _parse_since(since))
    hourly = pd.Series(1, index=index).resample("h").sum()
    rolled = hourly.rolling(window, min_periods=1).sum()

    _, ax = plt.subplots(figsize=(14, 5))
    sns.lineplot(x=rolled.index, y=rolled.values, color="0.0" if bw else None, ax=ax)
    ax.set_title(f"Messages — {window}-hour sliding window")
    ax.set_xlabel("Date")
    ax.set_ylabel("Messages")
    plt.tight_layout()
    if save is not None:
        plt.savefig(save)
    else:
        plt.show()


@app.command()
def by_sender(
    db: Path = typer.Argument(Path("cats.db"), help="SQLite database"),
    top: int = typer.Option(6, "--top", "-n", help="Number of top senders to show"),
    period: Period = typer.Option(
        Period.month, "--period", "-p", help="Aggregation period"
    ),
    smooth: int | None = typer.Option(
        None, "--smooth", "-s", help="Rolling mean window in periods (omit to disable)"
    ),
    stacked: bool = typer.Option(False, "--stacked", help="Stacked area chart"),
    normalized: bool = typer.Option(
        False, "--normalized", help="Normalize to 100%% (implies --stacked)"
    ),
    colorblind: bool = typer.Option(
        False, "--colorblind", help="Use colorblind-friendly palette"
    ),
    bw: bool = typer.Option(False, "--bw", help="Render in grayscale/black-and-white"),
    since: str | None = typer.Option(
        None,
        "--since",
        help="Only include messages on/after this date (e.g. 2024-06-01)",
    ),
    save: Path | None = typer.Option(
        None, "--save", help="Save the plot to this file instead of displaying it"
    ),
) -> None:
    """Plot message count per sender per day, week, or month."""
    cutoff = _parse_since(since)

    con = sqlite3.connect(db)
    df = pd.read_sql_query(
        "SELECT ts, sender FROM messages WHERE is_system = 0 AND sender IS NOT NULL",
        con,
    )
    con.close()

    df["ts"] = pd.to_datetime(df["ts"], format="ISO8601")
    if cutoff is not None:
        df = df[df["ts"] >= cutoff]
    df = df.set_index("ts")

    top_senders = df["sender"].value_counts().nlargest(top).index.tolist()
    df = df[df["sender"].isin(top_senders)]

    pivoted = (
        pd.get_dummies(df["sender"])
        .resample(_FREQ[period])
        .sum()
        .rename_axis(None, axis="columns")
    )

    if smooth is not None:
        pivoted = pivoted.rolling(smooth, min_periods=1).mean()

    pivoted = pivoted[pivoted.sum().sort_values(ascending=False).index]

    if normalized:
        stacked = True
        totals = pivoted.sum(axis=1).replace(0, 1)
        pivoted = pivoted.div(totals, axis=0) * 100

    pivoted.columns = [str(get_display(c)) for c in pivoted.columns]

    _, ax = plt.subplots(figsize=(14, 5))

    if bw:
        palette = _bw_palette(len(pivoted.columns))
    else:
        palette = sns.color_palette(
            "colorblind" if colorblind else "Set2", n_colors=len(pivoted.columns)
        )

    if stacked:
        polys = ax.stackplot(
            pivoted.index,
            pivoted.T.values,
            labels=list(pivoted.columns),
            colors=palette,
        )
        if bw:
            hatches = itertools.cycle(["", "//", "\\\\", "xx", "..", "oo"])
            for poly, hatch in zip(polys, hatches):
                poly.set_hatch(hatch)
                poly.set_edgecolor("black")
                poly.set_linewidth(0.5)
    else:
        melted = pivoted.reset_index().melt(
            id_vars="ts", var_name="sender", value_name="count"
        )
        n = len(pivoted.columns)
        if bw:
            sns.lineplot(
                data=melted,
                x="ts",
                y="count",
                hue="sender",
                style="sender",
                palette=palette,
                dashes=[_BW_DASHES[i % len(_BW_DASHES)] for i in range(n)],
                ax=ax,
            )
        else:
            sns.lineplot(
                data=melted, x="ts", y="count", hue="sender", palette=palette, ax=ax
            )

    title = f"Messages per sender ({period.value})"
    if normalized:
        title += " — share (%)"
    elif smooth is not None:
        title += f" — {smooth}-period avg"
    ax.set_title(title)
    ax.set_xlabel("Date")
    ax.set_ylabel("Messages")
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.12),
        ncols=top,
        frameon=False,
    )
    plt.tight_layout()
    if save is not None:
        plt.savefig(save)
    else:
        plt.show()


if __name__ == "__main__":
    app()
