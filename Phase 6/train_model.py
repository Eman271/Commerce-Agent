"""Train the optional intent model (Phase 3 baseline).

TF-IDF (word 1-2 grams) + Logistic Regression on the dev split of
conversations.json, predicting expected_action. Saves models/intent_model.pkl
and models/metrics.json. The engine uses this only as a fallback signal —
Phase 4 showed rules + guardrails beat the ML model on their own, so the
rules stay primary.

Needs scikit-learn (an optional extra, not a runtime dependency):
    pip install scikit-learn
    python train_model.py
"""
import json
import pickle
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent


def main():
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import accuracy_score, classification_report
        from sklearn.pipeline import Pipeline
    except ImportError:
        print("scikit-learn is not installed, so the intent model was not "
              "trained. The agent runs fine without it (rules are primary). "
              "To train it: pip install scikit-learn && python train_model.py")
        return 0

    data = json.loads((BASE / "data" / "conversations.json")
                      .read_text(encoding="utf-8-sig"))
    convs = data["conversations"]

    def text_of(c):
        return " ".join(t["text"] for t in c["turns"] if t["speaker"] == "customer")

    dev = [c for c in convs if c.get("split") == "dev"]
    test = [c for c in convs if c.get("split") == "test"]
    model = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1)),
        ("clf", LogisticRegression(max_iter=1000, class_weight="balanced")),
    ])
    model.fit([text_of(c) for c in dev],
              [c["expected"]["expected_action"] for c in dev])
    pred = model.predict([text_of(c) for c in test])
    y = [c["expected"]["expected_action"] for c in test]
    acc = accuracy_score(y, pred)
    report = classification_report(y, pred, zero_division=0, output_dict=True)
    (BASE / "models").mkdir(exist_ok=True)
    with open(BASE / "models" / "intent_model.pkl", "wb") as f:
        pickle.dump(model, f)
    metrics = {"test_accuracy": round(float(acc), 4), "n_dev": len(dev),
               "n_test": len(test), "classification_report": report}
    (BASE / "models" / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(f"Trained on {len(dev)} dev conversations. "
          f"Test action accuracy: {acc:.4f} ({len(test)} conversations)")
    print("Saved models/intent_model.pkl and models/metrics.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
