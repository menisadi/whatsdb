#!/usr/bin/env python3
"""Plot WhatsApp message frequency over time (seaborn version)."""

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


def _load_timestamps(db: Path) -> pd.DatetimeIndex:
    con = sqlite3.connect(db)
    df = pd.read_sql_query("SELECT ts FROM messages WHERE is_system = 0", con)
    con.close()
    return pd.DatetimeIndex(pd.to_datetime(df["ts"], format="%Y-%m-%d %H:%M"))


@app.command()
def per_period(
    db: Path = typer.Argument(Path("cats.db"), help="SQLite database"),
    period: Period = typer.Option(
        Period.day, "--period", "-p", help="Aggregation period"
    ),
    smooth: int | None = typer.Option(
        None, "--smooth", "-s", help="Rolling mean window in periods (omit to disable)"
    ),
) -> None:
    """Plot message count per day, week, or month."""
    index = _load_timestamps(db)
    counts = pd.Series(1, index=index).resample(_FREQ[period]).sum()

    _, ax = plt.subplots(figsize=(14, 5))
    sns.lineplot(x=counts.index, y=counts.values, alpha=0.4, label="raw", ax=ax)
    if smooth is not None:
        smoothed = counts.rolling(smooth, min_periods=1).mean()
        sns.lineplot(
            x=smoothed.index,
            y=smoothed.values,
            label=f"{smooth}-period avg",
            ax=ax,
        )
        ax.legend()
    ax.set_title(f"Messages per {period.value}")
    ax.set_xlabel("Date")
    ax.set_ylabel("Messages")
    plt.tight_layout()
    plt.show()


@app.command()
def sliding(
    db: Path = typer.Argument(Path("cats.db"), help="SQLite database"),
    window: int = typer.Option(12, "--window", "-w", help="Window size in hours"),
) -> None:
    """Plot message count using a sliding window sum."""
    index = _load_timestamps(db)
    hourly = pd.Series(1, index=index).resample("h").sum()
    rolled = hourly.rolling(window, min_periods=1).sum()

    _, ax = plt.subplots(figsize=(14, 5))
    sns.lineplot(x=rolled.index, y=rolled.values, ax=ax)
    ax.set_title(f"Messages — {window}-hour sliding window")
    ax.set_xlabel("Date")
    ax.set_ylabel("Messages")
    plt.tight_layout()
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
) -> None:
    """Plot message count per sender per day, week, or month."""
    con = sqlite3.connect(db)
    senders_df = pd.read_sql_query(
        "SELECT sender, COUNT(*) AS cnt FROM messages"
        " WHERE is_system = 0 AND sender IS NOT NULL"
        " GROUP BY sender",
        con,
    )
    con.close()

    top_senders = senders_df.nlargest(top, "cnt")["sender"].tolist()

    con = sqlite3.connect(db)
    df = pd.read_sql_query(
        f"SELECT ts, sender FROM messages WHERE is_system = 0"
        f" AND sender IN ({','.join('?' * top)})",
        con,
        params=top_senders,
    )
    con.close()

    df["ts"] = pd.to_datetime(df["ts"], format="%Y-%m-%d %H:%M")
    df = df.set_index("ts")

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

    if stacked:
        palette = sns.color_palette("tab10", n_colors=len(pivoted.columns))
        ax.stackplot(
            pivoted.index,
            pivoted.T.values,
            labels=list(pivoted.columns),
            colors=palette,
        )
    else:
        melted = pivoted.reset_index().melt(
            id_vars="ts", var_name="sender", value_name="count"
        )
        sns.lineplot(data=melted, x="ts", y="count", hue="sender", ax=ax)

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
    plt.show()


if __name__ == "__main__":
    app()
