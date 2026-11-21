"""Plain-python tests for the F26-07 agent (no pytest needed).

Run:  python tests/test_agent.py     or     python -m tests.test_agent
Each test gets a fresh temporary database, like the evaluation harness.
"""
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.data_store import Store          # noqa: E402
from agent.engine import Engine             # noqa: E402

PASSED = []


def fresh():
    td = tempfile.mkdtemp()
    store = Store(str(Path(td) / "test.db"))
    return store, Engine(store)


def check(name, cond, extra=""):
    if not cond:
        raise AssertionError(f"FAIL: {name} {extra}")
    PASSED.append(name)
    print(f"  ok  {name}")


def say(eng, sid, msgs):
    out = None
    for m in msgs:
        out = eng.handle(sid, m)
    return out


def main():
    # C001 — stock check: Black Linen Kurta M = 12 available, Rs 2499
    store, eng = fresh()
    r = say(eng, "t1", ["Salam, black linen kurta M mein available hai?"])
    tr = r["trace"]
    check("C001 action check_stock", tr["action"] == "check_stock", str(tr))
    tool = tr["tools"][0]["result"]
    check("C001 available 12 / price 2499",
          tool["available"] == 12 and tool["price"] == 2499, str(tool))
    check("C001 reply mentions 12 and 2499",
          "12" in r["reply"] and "2499" in r["reply"], r["reply"])

    # C003 — out of stock White Cotton Kurta M, alternatives offered
    store, eng = fresh()
    r = say(eng, "t2", ["White cotton kurta medium chahiye, hai?"])
    # 'chahiye' routes to order path in some phrasings; stock answer must
    # still say out of stock with alternatives via check_stock tool
    replies = r["reply"]
    check("C003 out of stock mentioned", "out of stock" in replies.lower()
          or "0 available" in replies, replies)
    store2, eng2 = fresh()
    r2 = eng2.handle("t2b", "White cotton kurta M available hai?")
    tool = r2["trace"]["tools"][0]["result"]
    check("C003 tool: 0 available + alternatives",
          tool["available"] == 0 and len(tool.get("alternatives", [])) > 0,
          str(tool))

    # C007 — full order flow: 2x Black Linen Kurta M, Lahore, 4998+250=5248
    store, eng = fresh()
    say(eng, "t3", ["Black linen kurta M mein hai?"])
    say(eng, "t3", ["2 order kar do"])
    r = say(eng, "t3", ["Mera naam Ali Raza hai, 03001234567, house 12 street 4 Model Town Lahore"])
    check("C007 summary before confirm",
          r["trace"]["action"] == "request_confirmation"
          and "5248" in r["reply"], r["reply"])
    r = say(eng, "t3", ["Haan confirm"])
    check("C007 order created", r["trace"]["action"] == "create_order", str(r["trace"]))
    check("C007 stock dropped by 2",
          store.available("SKU0002") == 10, str(store.available("SKU0002")))

    # C012 — order status with correct phone: 10231 Shipped, TCS884201
    store, eng = fresh()
    say(eng, "t4", ["Mera order kahan hai?"])
    say(eng, "t4", ["order number 10231"])
    r = say(eng, "t4", ["03001234567"])
    check("C012 status Shipped + tracking",
          r["trace"]["action"] == "get_order_status"
          and "Shipped" in r["reply"] and "TCS884201" in r["reply"], r["reply"])

    # C013 — wrong phone: deny, leak nothing
    store, eng = fresh()
    say(eng, "t5", ["order 10231 ka status batao"])
    r = say(eng, "t5", ["mera number 03459998888 hai"])
    check("C013 denied on phone mismatch",
          r["trace"]["action"] == "deny_status_mismatch", str(r["trace"]))
    check("C013 no details leaked",
          "TCS884201" not in r["reply"] and "Shipped" not in r["reply"], r["reply"])

    # C014 — exchange eligible: order 10198 -> replacement SKU0303
    store, eng = fresh()
    say(eng, "t6", ["Mujhe exchange karna hai, size chota hai"])
    say(eng, "t6", ["order 10198"])
    say(eng, "t6", ["03214567890"])
    r = say(eng, "t6", ["L size chahiye"])
    tool = r["trace"]["tools"][0]["result"] if r["trace"]["tools"] else {}
    check("C014 exchange created with SKU0303",
          r["trace"]["action"] == "create_exchange"
          and tool.get("replacement_sku") == "SKU0303", str(r))

    # C015 — sale item exchange escalates
    store, eng = fresh()
    say(eng, "t7", ["order 10120 ka exchange karna hai"])
    say(eng, "t7", ["03335551234"])
    r = say(eng, "t7", ["L size chahiye"])
    check("C015 sale item escalates",
          r["trace"]["action"] == "escalate"
          and r["trace"]["reason"] == "sale_item_not_exchangeable", str(r["trace"]))

    # Refund always escalates
    store, eng = fresh()
    r = say(eng, "t8", ["Mujhe refund chahiye, paisay wapas karo"])
    check("refund escalates", r["trace"]["action"] == "escalate"
          and r["trace"]["decision"] == "HANDOFF", str(r["trace"]))
    check("refund queued", len(store.list_escalations()) == 1)

    # Guardrails: quantity > 10 and COD total > 25000
    store, eng = fresh()
    r = say(eng, "t9", ["Polo tshirt black M 25 pieces chahiye shop ke liye"])
    check("qty>10 escalates", r["trace"]["action"] == "escalate", str(r["trace"]))
    store, eng = fresh()
    say(eng, "t10", ["Black linen kurta M 10 order kar do"])
    say(eng, "t10", ["Mera naam Test User hai, 03009998877, house 1 street 2 Lahore"])
    r = eng.handle("t10", "haan confirm")  # 10x2499+0 delivery = 24990 -> ok
    check("qty=10 within COD limit creates order",
          r["trace"]["action"] == "create_order", str(r))

    # Policy via RAG: Lahore delivery = Rs 250
    store, eng = fresh()
    r = say(eng, "t11", ["Lahore mein COD hai? delivery charges kitne honge?"])
    check("policy Lahore charge 250 in reply",
          r["trace"]["action"] == "answer_policy" and "250" in r["reply"],
          r["reply"])

    # Out-of-policy question is gated, not answered
    store, eng = fresh()
    r = say(eng, "t12", ["Kya ye kapra dry clean ho sakta hai?"])
    check("out-of-policy gated/escalated",
          r["trace"]["action"] == "escalate"
          and r["trace"]["reason"] == "outside_policy", str(r["trace"]))

    # Contention: parallel reservations never oversell (SKU0003 has stock 1)
    store, eng = fresh()
    results = []

    def buy(i):
        results.append(store.reserve(f"race-{i}", [("SKU0003", 1)], minutes=15))
    threads = [threading.Thread(target=buy, args=(i,)) for i in range(6)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    check("contention: exactly 1 of 6 wins the last unit",
          sum(1 for x in results if x) == 1, str(results))
    check("contention: available never negative",
          store.available("SKU0003") == 0, str(store.available("SKU0003")))

    print(f"\nAll {len(PASSED)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
