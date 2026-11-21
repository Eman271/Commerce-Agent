"""F26-07 — AI Sales & Customer Support Agent for Saira Fashion House.

Deliverable 5 consolidated code file (Track A).

This single file is the runnable summary of our project. It imports the
project's own `agent` package (the same code the web app in app.py serves),
runs a scripted demo of the scenarios our dataset labels as the key cases,
and then replays the full evaluation over all 172 labelled conversations.

How to run (from the project root, next to app.py):

    pip install -r requirements.txt
    python F26-07.py

The demo uses a temporary database, so running it never changes the shop's
real data (shop.db). The evaluation harness also gives every conversation a
fresh temporary store, exactly as the dataset notes require.

Team: Eman Fatima (24L-3008), Rabia (24L-3093), Abdullah Tahir (24L-3061),
Shahzaib Zia (24L-3057). Instructor: Muhammad Abdullah Shahid.
"""
import sys
import tempfile
from pathlib import Path

# --- make the project's agent package importable wherever we are run from ---
HERE = Path(__file__).resolve().parent
CANDIDATES = [HERE, HERE.parent, Path.home() / "workspace" / "ai_f26_07"]
for cand in CANDIDATES:
    if (cand / "agent" / "engine.py").exists():
        sys.path.insert(0, str(cand))
        PROJECT_ROOT = cand
        break
else:  # pragma: no cover
    raise SystemExit("Could not find the project folder (agent/engine.py). "
                     "Run this file from the project root.")

from agent.data_store import Store   # noqa: E402
from agent.engine import Engine      # noqa: E402

CHECKS = []


def check(label, cond, detail=""):
    CHECKS.append(bool(cond))
    print(f"  [{'OK' if cond else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    return cond


def fresh_engine(tmpdir, name):
    store = Store(str(Path(tmpdir) / name))
    return store, Engine(store)


def say(eng, sid, *messages):
    out = None
    for m in messages:
        out = eng.handle(sid, m)
    return out


def show(title, reply):
    print(f"\n--- {title} ---")
    print("Agent:", reply)


def demo(tmpdir):
    print("=" * 72)
    print("DEMO — the labelled key scenarios from our dataset")
    print("=" * 72)

    # 1) C001 — stock check: Black Linen Kurta M = 12 available, Rs 2499
    store, eng = fresh_engine(tmpdir, "demo1.db")
    r = say(eng, "d1", "Salam, black linen kurta M mein available hai?")
    tool = r["trace"]["tools"][0]["result"]
    show("1. Stock check: Black Linen Kurta, size M", r["reply"])
    check("action is check_stock", r["trace"]["action"] == "check_stock")
    check("12 available at Rs 2499",
          tool["available"] == 12 and tool["price"] == 2499,
          f"available={tool['available']}, price={tool['price']}")
    store.close()

    # 2) C003 — out of stock: White Cotton Kurta M, alternatives offered
    store, eng = fresh_engine(tmpdir, "demo2.db")
    r = say(eng, "d2", "White cotton kurta M available hai?")
    tool = r["trace"]["tools"][0]["result"]
    show("2. Out of stock: White Cotton Kurta, size M", r["reply"])
    check("0 available, alternatives offered",
          tool["available"] == 0 and len(tool.get("alternatives", [])) > 0,
          f"alternatives={len(tool.get('alternatives', []))}")
    store.close()

    # 3) C007 — full order: 2x Black Linen Kurta M to Lahore = Rs 5248
    store, eng = fresh_engine(tmpdir, "demo3.db")
    say(eng, "d3", "Black linen kurta M mein hai?")
    say(eng, "d3", "2 order kar do")
    r = say(eng, "d3", "Mera naam Ali Raza hai, 03001234567, "
                       "house 12 street 4 Model Town Lahore")
    show("3. Order summary: 2x Black Linen Kurta M, Lahore", r["reply"])
    check("summary asks for confirmation with total Rs 5248 "
          "(4998 + 250 delivery)",
          r["trace"]["action"] == "request_confirmation" and "5248" in r["reply"])
    r = say(eng, "d3", "Haan confirm")
    show("Order confirmed", r["reply"])
    check("order created", r["trace"]["action"] == "create_order")
    check("stock fell from 12 to 10", store.available("SKU0002") == 10,
          f"available now={store.available('SKU0002')}")
    store.close()

    # 4) C012 — order status, correct phone: 10231 = Shipped, TCS884201
    store, eng = fresh_engine(tmpdir, "demo4.db")
    say(eng, "d4", "Mera order kahan hai?")
    say(eng, "d4", "order number 10231")
    r = say(eng, "d4", "03001234567")
    show("4. Order status: order 10231, correct phone", r["reply"])
    check("status shown: Shipped with tracking TCS884201",
          r["trace"]["action"] == "get_order_status"
          and "Shipped" in r["reply"] and "TCS884201" in r["reply"])
    store.close()

    # 5) C013 — order status, wrong phone: denied, nothing leaked
    store, eng = fresh_engine(tmpdir, "demo5.db")
    say(eng, "d5", "order 10231 ka status batao")
    r = say(eng, "d5", "mera number 03459998888 hai")
    show("5. Order status: order 10231, WRONG phone", r["reply"])
    check("denied on phone mismatch",
          r["trace"]["action"] == "deny_status_mismatch")
    check("no details leaked (no status, no tracking number)",
          "TCS884201" not in r["reply"] and "Shipped" not in r["reply"])
    store.close()

    # 6) C014 — exchange eligible: order 10198 -> replacement SKU0303
    store, eng = fresh_engine(tmpdir, "demo6.db")
    say(eng, "d6", "Mujhe exchange karna hai, size chota hai")
    say(eng, "d6", "order 10198")
    say(eng, "d6", "03214567890")
    r = say(eng, "d6", "L size chahiye")
    tool = r["trace"]["tools"][0]["result"] if r["trace"]["tools"] else {}
    show("6. Exchange: order 10198, wants size L", r["reply"])
    check("exchange created with replacement SKU0303",
          r["trace"]["action"] == "create_exchange"
          and tool.get("replacement_sku") == "SKU0303",
          f"replacement={tool.get('replacement_sku')}")
    check("exchange courier charge is Rs 250",
          tool.get("exchange_courier_charge") == 250,
          f"charge={tool.get('exchange_courier_charge')}")
    store.close()

    # 7) C015 — exchange of a sale item: escalated, never auto-approved
    store, eng = fresh_engine(tmpdir, "demo7.db")
    say(eng, "d7", "order 10120 ka exchange karna hai")
    say(eng, "d7", "03335551234")
    r = say(eng, "d7", "L size chahiye")
    show("7. Exchange: order 10120 (a sale item)", r["reply"])
    check("sale item exchange escalates to a human",
          r["trace"]["action"] == "escalate"
          and r["trace"]["reason"] == "sale_item_not_exchangeable",
          f"reason={r['trace']['reason']}")
    store.close()

    # 8) Refund request: the AI never approves refunds — human handoff
    store, eng = fresh_engine(tmpdir, "demo8.db")
    r = say(eng, "d8", "Mujhe refund chahiye, paisay wapas karo")
    show("8. Refund request", r["reply"])
    check("refund escalates (HANDOFF) and lands in the human queue",
          r["trace"]["action"] == "escalate"
          and r["trace"]["decision"] == "HANDOFF"
          and len(store.list_escalations()) == 1)
    store.close()


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        demo(tmpdir)

    print("\n" + "=" * 72)
    print("EVALUATION — replaying all 172 labelled conversations")
    print("(fresh store per conversation; prediction = final turn's action)")
    print("=" * 72)
    sys.path.insert(0, str(PROJECT_ROOT))
    from evaluation import run_evaluation
    result = run_evaluation()
    for split in ("dev", "test", "overall"):
        m = result[split]
        print(f"{split:>7}: n={m['n']:>3}  action accuracy={m['action_accuracy']:.4f}  "
              f"escalation P={m['escalation_precision']:.4f} "
              f"R={m['escalation_recall']:.4f} F1={m['escalation_f1']:.4f}")
    ov = result["overall"]
    print(f"\nEvaluation summary: action accuracy {ov['action_accuracy']:.4f} overall "
          f"(dev {result['dev']['action_accuracy']:.4f}, "
          f"test {result['test']['action_accuracy']:.4f}); "
          f"escalation F1 {ov['escalation_f1']:.4f}.")
    print("Note: dev/test are the conversations the system was developed "
          "against, so these are replay scores, not a blind test. Our Phase 4 "
          "blind estimate on 38 unseen conversations was 0.763.")

    print(f"\nDemo checks: {sum(CHECKS)}/{len(CHECKS)} passed.")
    return 0 if all(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
