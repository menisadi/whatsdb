# /// script
# dependencies = ["scikit-learn", "fire"]
# ///

import re
import sqlite3
from collections import Counter
from pathlib import Path

import fire
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, accuracy_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline, FeatureUnion

_OMITTED = {"<media omitted>", "null", "this message was deleted"}
_WORD_RE = re.compile(r"[֐-׿\w]+")

_LENGTH_BINS = [(1, 3), (4, 9), (10, 19), (20, None)]


def load_messages(db: str, top_senders: int) -> tuple[list[str], list[str]]:
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.execute(
        "SELECT body, sender FROM messages WHERE is_system = 0 AND sender IS NOT NULL"
    )
    rows = [
        (body, sender)
        for body, sender in cur.fetchall()
        if body.strip().lower() not in _OMITTED
    ]
    con.close()

    counts = Counter(sender for _, sender in rows)
    top = {sender for sender, _ in counts.most_common(top_senders)}
    filtered = [(body, sender) for body, sender in rows if sender in top]

    texts = [body for body, _ in filtered]
    labels = [sender for _, sender in filtered]
    return texts, labels


def short_name(name: str) -> str:
    return name.split()[0]


def word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def build_pipeline(char: bool, seed: int) -> Pipeline:
    word_vec = TfidfVectorizer(
        token_pattern=r"[֐-׿\w]{2,}",
        min_df=5,
        max_features=50_000,
        sublinear_tf=True,
    )
    clf = LogisticRegression(max_iter=1000, C=5.0, random_state=seed)
    if not char:
        return Pipeline([("tfidf", word_vec), ("clf", clf)])
    return Pipeline(
        [
            (
                "features",
                FeatureUnion(
                    [
                        ("word", word_vec),
                        (
                            "char",
                            TfidfVectorizer(
                                analyzer="char_wb",
                                ngram_range=(2, 5),
                                min_df=5,
                                max_features=100_000,
                                sublinear_tf=True,
                            ),
                        ),
                    ]
                ),
            ),
            ("clf", clf),
        ]
    )


def get_word_features(pipeline: Pipeline) -> tuple[list[str], list]:
    """Return (display_names, coef_matrix) using only word-level features."""
    clf: LogisticRegression = pipeline.named_steps["clf"]
    if "tfidf" in pipeline.named_steps:
        vec: TfidfVectorizer = pipeline.named_steps["tfidf"]
        return list(vec.get_feature_names_out()), clf.coef_
    union: FeatureUnion = pipeline.named_steps["features"]
    all_names = union.get_feature_names_out()
    word_mask = [name.startswith("word__") for name in all_names]
    display_names = [
        name[len("word__") :] for name, m in zip(all_names, word_mask) if m
    ]
    word_indices = [i for i, m in enumerate(word_mask) if m]
    coef = clf.coef_[:, word_indices]
    return display_names, coef


def print_top_features(pipeline: Pipeline, n: int) -> None:
    feature_names, coef = get_word_features(pipeline)
    clf: LogisticRegression = pipeline.named_steps["clf"]

    # Binary logistic regression stores only 1 coefficient row (positive class).
    # The negative class's signal is the mirror.
    if coef.shape[0] == 1:
        coef = np.vstack([coef, -coef])

    print(f"\nTop {n} words per sender:")
    print("-" * 50)
    for i, label in enumerate(clf.classes_):
        top_idx = coef[i].argsort()[-n:][::-1]
        tokens = ", ".join(feature_names[j] for j in top_idx)
        print(f"  {short_name(label):<20} {tokens}")


def print_lengths(X_test: list[str], y_test: list[str], y_pred: list[str]) -> None:
    print("\nAccuracy by message length:")
    print("-" * 50)
    for lo, hi in _LENGTH_BINS:
        label = f"{lo}–{hi}" if hi else f"{lo}+"
        mask = [lo <= word_count(t) <= (hi if hi else 10**9) for t in X_test]
        yt = [y for y, m in zip(y_test, mask) if m]
        yp = [y for y, m in zip(y_pred, mask) if m]
        if not yt:
            continue
        acc = accuracy_score(yt, yp)
        print(f"  {label + ' words':<16} n={len(yt):>6,}   accuracy={acc:.0%}")


def classify(
    db: str = "cats.db",
    top_senders: int = 5,
    top_features: int = 10,
    test_size: float = 0.2,
    seed: int = 42,
    char: bool = True,
    report: bool = True,
    features: bool = True,
    lengths: bool = True,
) -> None:
    """Train a sender attribution classifier on a whatsdb SQLite database.

    Args:
        db:                Path to the SQLite database (default: cats.db).
        top_senders:       Number of most active senders to classify (default: 5).
        top_features:      Number of top discriminating words to show per sender.
        test_size:         Fraction of data held out for evaluation (default: 0.2).
        seed:              Random seed for reproducibility.
        char:              Use character n-gram features in addition to words (default: True).
        report:            Show per-sender classification report (default: True).
        features:          Show top discriminating words per sender (default: True).
        lengths:           Show accuracy broken down by message length (default: True).
    """
    db_path = Path(db)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db}")

    print(f"Loading messages from {db}...")
    texts, labels = load_messages(db, top_senders)

    counts = Counter(labels)
    print(f"Loaded {len(texts):,} messages across {len(counts)} senders:")
    for sender, cnt in counts.most_common():
        print(f"  {short_name(sender):<20} {cnt:>6,} messages")

    X_train, X_test, y_train, y_test = train_test_split(
        texts, labels, test_size=test_size, stratify=labels, random_state=seed
    )

    model_desc = "word + char n-grams" if char else "word n-grams only"
    print(
        f"\nTraining on {len(X_train):,} messages, evaluating on {len(X_test):,} ({model_desc})..."
    )
    pipeline = build_pipeline(char, seed)
    pipeline.fit(X_train, y_train)

    y_pred = pipeline.predict(X_test)
    target_names = [short_name(s) for s in pipeline.named_steps["clf"].classes_]

    if report:
        print("\n" + classification_report(y_test, y_pred, target_names=target_names))

    if lengths:
        print_lengths(X_test, y_test, y_pred)

    if features:
        print_top_features(pipeline, top_features)


if __name__ == "__main__":
    fire.Fire(classify)
