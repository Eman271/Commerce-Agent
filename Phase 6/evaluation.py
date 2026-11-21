"""Evaluation harness: replay conversations.json through the engine.

The dataset note says the DB must be reset before each conversation, so every
conversation gets a fresh temporary store. The prediction for a conversation
is the action of its final turn. Reports action accuracy plus escalation
precision/recall/F1, overall and per split (dev/test).
"""
import json
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent


def run_evaluation(store_factory=None):
    from agent.data_store import Store
    from agent.engine import Engine
    factory = store_factory or (lambda p: Store(p))
    data = json.loads((BASE / "data" / "conversations.json")
                      .read_text(encoding="utf-8-sig"))
    convs = data["conversations"]
    rows = []
    for c in convs:
        with tempfile.TemporaryDirectory() as td:
            st = factory(str(Path(td) / "eval.db"))
            eng = Engine(st)
            pred = None
            for turn in c["turns"]:
                if turn["speaker"] == "customer":
                    pred = eng.handle(f"eval-{c['conv_id']}", turn["text"])["trace"]
            st.close()
        exp = c["expected"]
        rows.append({
            "conv_id": c["conv_id"], "split": c.get("split"),
            "expected_action": exp["expected_action"],
            "predicted_action": pred["action"] if pred else None,
            "should_escalate": bool(exp["should_escalate"]),
            "predicted_escalate": bool(pred and pred["action"] == "escalate"),
        })

    def metrics(sub):
        n = len(sub) or 1
        acc = sum(r["expected_action"] == r["predicted_action"] for r in sub) / n
        tp = sum(r["should_escalate"] and r["predicted_escalate"] for r in sub)
        fp = sum(not r["should_escalate"] and r["predicted_escalate"] for r in sub)
        fn = sum(r["should_escalate"] and not r["predicted_escalate"] for r in sub)
        prec = tp / (tp + fp) if tp + fp else 1.0
        rec = tp / (tp + fn) if tp + fn else 1.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        return {"n": len(sub), "action_accuracy": round(acc, 4),
                "escalation_precision": round(prec, 4),
                "escalation_recall": round(rec, 4),
                "escalation_f1": round(f1, 4)}

    result = {"overall": metrics(rows),
              "dev": metrics([r for r in rows if r["split"] == "dev"]),
              "test": metrics([r for r in rows if r["split"] == "test"]),
              "rows": rows}
    (BASE / "evaluation_result.json").write_text(
        json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    return result


if __name__ == "__main__":
    r = run_evaluation()
    print(json.dumps({k: v for k, v in r.items() if k != "rows"}, indent=2))
