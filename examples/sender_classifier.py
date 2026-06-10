# /// script
# dependencies = ["scikit-learn", "fire"]
# ///

import sqlite3
from collections import Counter
from pathlib import Path

import fire
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline, FeatureUnion

_OMITTED = {"<media omitted>", "null", "this message was deleted"}


def load_messages(db: str, top_senders: int) -> tuple[list[str], list[str]]:
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.execute(
        "SELECT body, sender FROM messages"
        " WHERE is_system = 0 AND sender IS NOT NULL"
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


def print_top_features(
    pipeline: Pipeline, label_names: list[str], n: int
) -> None:
    union: FeatureUnion = pipeline.named_steps["features"]
    feature_names = union.get_feature_names_out()
    clf: LogisticRegression = pipeline.named_steps["clf"]

    print(f"\nTop {n} tokens per sender:")
    print("-" * 50)
    for i, label in enumerate(clf.classes_):
        coefs = clf.coef_[i]
        top_idx = coefs.argsort()[-n:][::-1]
        tokens = ", ".join(feature_names[j] for j in top_idx)
        print(f"  {short_name(label):<20} {tokens}")


def classify(
    db: str = "cats.db",
    top_senders: int = 5,
    top_features: int = 10,
    test_size: float = 0.2,
    seed: int = 42,
) -> None:
    """Train a sender attribution classifier on a whatsdb SQLite database.

    Args:
        db:           Path to the SQLite database (default: cats.db).
        top_senders:  Number of most active senders to classify (default: 5).
        top_features: Number of top discriminating tokens to show per sender.
        test_size:    Fraction of data held out for evaluation (default: 0.2).
        seed:         Random seed for reproducibility.
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

    pipeline = Pipeline([
        ("features", FeatureUnion([
            ("word", TfidfVectorizer(
                token_pattern=r"[֐-׿\w]{2,}",
                min_df=5,
                max_features=50_000,
                sublinear_tf=True,
            )),
            ("char", TfidfVectorizer(
                analyzer="char_wb",
                ngram_range=(2, 5),
                min_df=5,
                max_features=100_000,
                sublinear_tf=True,
            )),
        ])),
        ("clf", LogisticRegression(max_iter=1000, C=5.0, random_state=seed)),
    ])

    print(f"\nTraining on {len(X_train):,} messages, evaluating on {len(X_test):,}...")
    pipeline.fit(X_train, y_train)

    y_pred = pipeline.predict(X_test)
    target_names = [short_name(s) for s in pipeline.named_steps["clf"].classes_]
    print("\n" + classification_report(y_test, y_pred, target_names=target_names))

    print_top_features(pipeline, target_names, top_features)


if __name__ == "__main__":
    fire.Fire(classify)
