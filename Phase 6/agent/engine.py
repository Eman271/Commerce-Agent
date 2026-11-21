"""Dialogue manager (Phase 4 v3 design): rules first, ML as fallback only.

Flow per message: normalize/extract -> session stage handling -> guardrails
-> intent routing -> tools/RAG -> reply in the customer's language mix.
Every reply carries a trace {intent, action, entities, confidence, decision,
reason, tools[]} so the UI, the evaluation and the teacher can all see *why*.
"""
import pickle
import re
import threading
from pathlib import Path

from . import guardrails, nlu
from .policy_rag import PolicyRAG
from .tools import Tools

BASE = Path(__file__).resolve().parent.parent
CONFIRM_WORDS = {"yes", "haan", "han", "confirm", "theek", "sahi", "bhej",
                 "ji", "ok", "okay", "bilkul", "done", "kar"}
POLICY_HINTS = ["delivery", "cod", "cash on delivery", "charge", "charges",
                "kitne din", "deliver", "policy", "bahar", "abroad", "mulk",
                "exchange ho sakta", "sale wale", "shipping", "courier charge",
                "free delivery", "payment", "working hours", "staff available",
                "showroom", "walk in", "location kahan"]


class Engine:
    def __init__(self, store, data_dir=None, today="2026-10-17"):
        self.store = store
        self.data_dir = Path(data_dir or (BASE / "data"))
        self.rules = guardrails.load_rules(self.data_dir / "policy_rules.json")
        self.rag = PolicyRAG(self.data_dir / "policy.md")
        self.tools = Tools(store, self.rules, today=today)
        self.sessions = {}
        self.lock = threading.RLock()
        self.ml_model = None
        pkl = BASE / "models" / "intent_model.pkl"
        if pkl.exists():
            try:
                with open(pkl, "rb") as f:
                    self.ml_model = pickle.load(f)
            except Exception:
                self.ml_model = None

    # ------------------------------------------------------------- sessions
    def _session(self, sid):
        return self.sessions.setdefault(sid, {
            "stage": None, "items": [], "context": {}, "customer": {},
            "exchange": {}, "status": {}, "unclear": 0, "last_action": None})

    def reset(self):
        with self.lock:
            self.sessions.clear()
            self.store.reset()

    # -------------------------------------------------------------- helpers
    def _ml_action(self, text):
        if not self.ml_model:
            return None
        try:
            return str(self.ml_model.predict([nlu.normalize(text)])[0])
        except Exception:
            return None

    def _out(self, sid, s, reply, intent, action, conf, decision, reason="",
             tools=None, entities=None):
        trace = {"intent": intent, "action": action,
                 "entities": entities or {}, "confidence": round(conf, 2),
                 "decision": decision, "reason": reason, "tools": tools or []}
        s["last_action"] = action
        self.store.log_message(sid, "agent", reply)
        self.store.audit(sid, "decision",
                         {"intent": intent, "action": action})
        return {"reply": reply, "trace": trace}

    def _escalate(self, sid, s, reason, intent, entities, mix, detail=""):
        self.store.add_escalation(sid, reason, detail or reason)
        self.store.audit(sid, "escalate", reason)
        s["stage"] = None
        s["escalated"] = reason  # sticky: a handed-off chat stays handed off
        reply = ("Ye wala case main apni staff team ko forward kar raha hoon — "
                 "wo working hours (10 AM - 8 PM) mein aap ko reply karenge. "
                 "Shukriya for your patience."
                 if mix else
                 "I am forwarding this to our staff team — they will reply "
                 "during working hours (10 AM - 8 PM). Thank you for your patience.")
        return self._out(sid, s, reply, intent, "escalate", 0.9, "HANDOFF",
                         reason=reason, entities=entities)

    # ----------------------------------------------------------------- main
    def handle(self, session_id, message):
        with self.lock:
            return self._handle(session_id, str(message or ""))

    def _handle(self, sid, message):
        s = self._session(sid)
        self.store.log_message(sid, "customer", message)
        t = nlu.normalize(message)
        mix = nlu.urdu_share(message) > 0.2
        names = self.store.product_names()
        e = nlu.extract(message, names)
        entities = {k: v for k, v in e.items()
                    if v not in (None, [], {}) and k != "details"}
        # keep a running context item (product/color/size last mentioned) —
        # but not from a details turn, where addresses pollute product matching
        if s["stage"] not in ("order_details", "confirm"):
            for k in ("product", "color", "size"):
                if e.get(k):
                    s["context"][k] = e[k]

        # ---- stage: waiting for order confirmation
        if s["stage"] == "confirm":
            words = set(t.split())
            if words & CONFIRM_WORDS or "bhej do" in t or "kar do" in t:
                return self._create_order(sid, s, e, mix)
            if "nahi" in words or "cancel" in words or "rehne" in t:
                self.store.release(sid)
                s["stage"] = None; s["items"] = []
                return self._out(sid, s, "Theek hai, order cancel kar diya — "
                                 "reservation release ho gayi hai.",
                                 "place_order", "request_missing_info", 0.9,
                                 "ASK", entities=entities)
            return self._out(sid, s, "Summary confirm kar dein — 'haan' likhein "
                             "order place karne ke liye.",
                             "place_order", "request_confirmation", 0.8, "ASK",
                             entities=entities)

        # ---- a handed-off conversation stays handed off
        if s.get("escalated"):
            return self._out(sid, s, "Aap ka case pehle hi staff ko forward "
                             "hai — wo working hours (10 AM - 8 PM) mein reply "
                             "karenge.", "escalation", "escalate", 0.9,
                             "HANDOFF", reason=s["escalated"], entities=entities)

        # ---- topics the policy simply does not cover: never invent an answer
        if re.search(r"dry clean|shrink|warranty|guarantee|fade|stitching|"
                     r"alteration|rent par|iron hota", t):
            return self._escalate(sid, s, "outside_policy", "policy_question",
                                  entities, mix, "topic not in policy.md")

        # ---- guardrails (before any state-changing flow)
        hit = guardrails.check_text(message, self.rules)
        if hit and s["stage"] not in ("status", "exchange"):
            # a cancel/change of an *unconfirmed* cart is not an escalation
            if not (hit[0].startswith("order_") and s["stage"] == "order_details"):
                return self._escalate(sid, s, hit[0], "escalation", entities,
                                      mix, hit[1])

        # ---- exchange flow
        if s["stage"] == "exchange" or "exchange" in t or "tabdeel" in t:
            return self._exchange_flow(sid, s, e, t, mix, entities)
        # ---- order status flow
        if s["stage"] == "status" or re.search(
                r"order kahan|order status|status batao|mera order|track", t) \
                or (e.get("order_id") and ("kahan" in t or "status" in t)):
            return self._status_flow(sid, s, e, t, mix, entities)

        # ---- policy questions
        if any(h in t for h in POLICY_HINTS) and not e.get("product"):
            return self._policy_answer(sid, s, e, t, mix, entities)

        # ---- recommendations ('dikhao' alone, with no product/budget
        # context, is a vague message — not a recommendation request)
        want_recs = e.get("budget") or re.search(r"suggest|recommend", t) or (
            re.search(r"dikhao|dikha do", t)
            and (e.get("product") or self._category_hint(t)))
        if want_recs:
            recs = self.tools.recommend_products(
                e.get("budget"), self._category_hint(t))
            tools = [{"name": "recommend_products",
                      "result": {"count": len(recs), "budget": e.get("budget")}}]
            if recs:
                lines = "; ".join(f"{r['product']} ({r['color']}, {r['size']}) "
                                  f"Rs {r['price']}" for r in recs)
                reply = (f"Budget ke hisaab se ye options hain: {lines}. "
                         "Koi pasand aye to color/size bata dein, order kar dunga."
                         if mix else f"Here are in-stock options in your budget: "
                         f"{lines}. Tell me a color and size to order one.")
                s["unclear"] = 0
                return self._out(sid, s, reply, "recommend", "recommend", 0.9,
                                 "ACT", tools=tools, entities=entities)
            return self._out(sid, s, "Is budget mein filhaal koi in-stock item "
                             "nahi mila. Budget thora barha kar try karein?",
                             "recommend", "recommend", 0.6, "ASK",
                             tools=tools, entities=entities)

        # ---- product / order / stock
        if e.get("product") or s["stage"] == "order_details" or \
                (s["context"].get("product") and
                 re.search(r"order|bhej|chahiye|same|lena|buy", t)):
            return self._product_flow(sid, s, e, t, mix, entities)

        # ---- a question we could not route: try RAG, gate decides
        if "?" in message or re.search(r"\bkya\b|\bhai kya\b|sakta|sakti", t):
            return self._policy_answer(sid, s, e, t, mix, entities)

        # ---- optional ML fallback signal (Phase 4: rules stay primary; the
        # trained classifier only gets a say when rules found nothing, and
        # only to route a policy question — it can never trigger an action)
        ml_action = self._ml_action(message)
        if ml_action == "answer_policy":
            entities = dict(entities); entities["ml_action"] = ml_action
            return self._policy_answer(sid, s, e, t, mix, entities)

        # ---- unclear
        s["unclear"] += 1
        if s["unclear"] >= 3:
            return self._escalate(sid, s, "unclear_after_two_attempts",
                                  "unknown", entities, mix)
        reply = ("Thora sa aur clear bata dein — aap ko product check karna hai, "
                 "order karna hai, order status dekhna hai ya exchange? "
                 "Product ka naam, color aur size likh dein."
                 if mix else "Could you clarify a little? I can check stock, "
                 "place an order, track an order or start an exchange — "
                 "please share the product name, color and size.")
        return self._out(sid, s, reply, "unknown", "request_missing_info", 0.4,
                         "ASK", reason="unclear_message", entities=entities)

    def _category_hint(self, t):
        for hint, cat in (("kurti", "Women Kurti"), ("kurta", "Kurta"),
                          ("jootay", "Footwear"), ("shoes", "Footwear"),
                          ("chappal", "Footwear"), ("khussa", "Footwear"),
                          ("abaya", "Women Modest"), ("hijab", "Women Modest")):
            if hint in t:
                return cat
        return None

    # --------------------------------------------------------- policy (RAG)
    def _policy_answer(self, sid, s, e, t, mix, entities):
        answer, chunk = self.rag.grounded_answer(t)
        tools = [{"name": "policy_rag",
                  "result": {"section": chunk["title"], "score": chunk["score"]}}]
        if answer is None:
            return self._escalate(sid, s, "outside_policy", "policy_question",
                                  entities, mix,
                                  f"RAG score {chunk['score']} below gate")
        extra = ""
        if e.get("city") and ("charge" in t or "delivery" in t):
            charge = self.tools.delivery_charge(e["city"], 0)
            tools.append({"name": "delivery_charge",
                          "result": {"city": e["city"], "charge": charge}})
            extra = f" {e['city']} ke liye delivery charge Rs {charge} hai."
        s["unclear"] = 0
        return self._out(sid, s, answer + extra, "policy_question",
                         "answer_policy", 0.85, "ACT", tools=tools,
                         entities=entities)

    # ------------------------------------------------------------ status flow
    def _status_flow(self, sid, s, e, t, mix, entities):
        st = s["status"]
        if e.get("order_id"):
            st["order_id"] = e["order_id"]
        if e.get("phone"):
            st["phone"] = e["phone"]
        if not st.get("order_id"):
            s["stage"] = "status"
            return self._out(sid, s, "Order status ke liye apna order number "
                             "bata dein (masalan 10231).", "order_status",
                             "request_missing_info", 0.8, "ASK", entities=entities)
        if not st.get("phone"):
            s["stage"] = "status"
            return self._out(sid, s, "Privacy ke liye wo phone number bhi bata "
                             "dein jo order par diya tha.", "order_status",
                             "request_missing_info", 0.8, "ASK", entities=entities)
        res = self.tools.get_order_status(st["order_id"], st["phone"])
        tools = [{"name": "get_order_status", "result": {
            "found": res["found"], "phone_match": res.get("phone_match")}}]
        s["stage"] = None; s["status"] = {}
        if not res["found"]:
            return self._escalate(sid, s, "order_not_found", "order_status",
                                  entities, mix)
        if not res["phone_match"]:
            reply = ("Maazrat, di gayi maloomat se order verify nahi ho saka, "
                     "is liye status share nahi kar sakta. Order number aur "
                     "phone number dobara check kar ke bhejein."
                     if mix else "Sorry, I could not verify the order with "
                     "those details, so I cannot share its status. Please "
                     "check the order number and phone number.")
            return self._out(sid, s, reply, "order_status",
                             "deny_status_mismatch", 0.95, "BLOCK",
                             reason="phone_mismatch", tools=tools,
                             entities=entities)
        reply = (f"Aap ka order {res['status']} hai."
                 + (f" Courier: {res['courier']}, tracking: {res['tracking_no']}."
                    if res.get("tracking_no") else ""))
        return self._out(sid, s, reply, "order_status", "get_order_status",
                         0.97, "ACT", tools=tools, entities=entities)

    # ---------------------------------------------------------- exchange flow
    def _exchange_flow(self, sid, s, e, t, mix, entities):
        ex = s["exchange"]
        if e.get("order_id"):
            ex["order_id"] = e["order_id"]
        if e.get("phone"):
            ex["phone"] = e["phone"]
        if e.get("size"):
            ex["want_size"] = e["size"]
        if e.get("color"):
            ex["want_color"] = e["color"]
        s["stage"] = "exchange"
        if not ex.get("order_id"):
            return self._out(sid, s, "Exchange ke liye pehle apna order number "
                             "bata dein.", "exchange", "request_missing_info",
                             0.8, "ASK", entities=entities)
        if not ex.get("phone"):
            return self._out(sid, s, "Order par diya gaya phone number bata dein "
                             "taake order verify ho sake.", "exchange",
                             "request_missing_info", 0.8, "ASK", entities=entities)
        order = self.store.get_order(ex["order_id"])
        if not order:
            return self._escalate(sid, s, "order_not_found", "exchange",
                                  entities, mix)
        if order["phone"] != ex["phone"]:
            s["stage"] = None; s["exchange"] = {}
            return self._out(sid, s, "Di gayi maloomat se order verify nahi ho "
                             "saka, exchange start nahi kar sakta.", "exchange",
                             "deny_status_mismatch", 0.95, "BLOCK",
                             reason="phone_mismatch", entities=entities)
        if not (ex.get("want_size") or ex.get("want_color")):
            return self._out(sid, s, "Aap ko konsa size ya color chahiye "
                             "replacement mein? Bata dein.", "exchange",
                             "request_missing_info", 0.8, "ASK", entities=entities)
        res = self.tools.check_exchange(ex["order_id"], ex["phone"],
                                        ex.get("want_size"), ex.get("want_color"))
        tools = [{"name": "check_exchange", "result": res}]
        s["stage"] = None; s["exchange"] = {}
        if res["eligible"]:
            self.store.add_exchange(ex["order_id"], res["old_sku"],
                                    res["replacement_sku"],
                                    res["exchange_courier_charge"])
            reply = (f"Exchange eligible hai. Replacement {res['product']} "
                     f"({res['replacement_sku']}) bhej di jayegi — exchange "
                     f"courier charge Rs {res['exchange_courier_charge']} hai. "
                     "Original item wapas bhejne par replacement dispatch hogi.")
            return self._out(sid, s, reply, "exchange", "create_exchange", 0.95,
                             "ACT", tools=tools, entities=entities)
        return self._escalate(sid, s, res["reason"], "exchange", entities, mix,
                              str(res))

    # ----------------------------------------------------------- product flow
    def _product_flow(self, sid, s, e, t, mix, entities):
        if s["stage"] == "order_details":
            # a details turn (name/address) must never re-match the product —
            # street addresses fuzzy-match product names surprisingly often
            e = dict(e); e["product"] = None
        order_words = re.search(r"order|bhej|chahiye|lena|buy|kar do|kardo", t)
        # build / update the working item
        ctx = dict(s["context"])
        item = {"product": e.get("product") or ctx.get("product"),
                "color": e.get("color") or (ctx.get("color") if e.get("product") else None),
                "size": e.get("size") or (ctx.get("size") if e.get("product") else None),
                "qty": e.get("qty")}
        if "same" in t and s["items"]:
            base = dict(s["items"][0])
            base["qty"] = e.get("qty") or 1
            new_items = [base]
            for c in e.get("colors", []):
                if c != base["color"]:
                    extra = dict(base); extra["color"] = c; extra["qty"] = 1
                    new_items.append(extra)
            s["items"] = new_items
        elif e.get("product"):
            if s["stage"] != "order_details" or not s["items"]:
                s["items"] = [item]
            else:
                s["items"][0].update({k: v for k, v in item.items() if v})
        elif s["stage"] == "order_details" and s["items"]:
            cur = s["items"][0]
            for k in ("color", "size"):
                if e.get(k) and not cur.get(k):
                    cur[k] = e[k]
            item = cur
        else:
            item = {"product": ctx.get("product"), "color": ctx.get("color"),
                    "size": ctx.get("size"), "qty": e.get("qty")}
            if item["product"]:
                s["items"] = [item]

        # details turn for an in-progress order
        if s["stage"] == "order_details":
            d = e["details"]
            for k in ("name", "phone", "address", "city"):
                if d.get(k):
                    s["customer"][k] = d[k]
            if e.get("city"):
                s["customer"]["city"] = e["city"]
            if e.get("phone"):
                s["customer"]["phone"] = e["phone"]

        if not order_words and s["stage"] != "order_details":
            # plain stock / price question
            if not item.get("product"):
                return self._out(sid, s, "Konsa product check karun? Naam, color "
                                 "aur size bata dein.", "check_stock",
                                 "request_missing_info", 0.5, "ASK",
                                 entities=entities)
            res = self.tools.check_stock(item["product"], item.get("color"),
                                         item.get("size"))
            tools = [{"name": "check_stock", "result": res}]
            s["unclear"] = 0
            if not res["found"]:
                return self._out(sid, s, f"{item['product']} ki ye variant nahi "
                                 "mili. Available variants check kar ke bataun?",
                                 "check_stock", "check_stock", 0.6, "ASK",
                                 tools=tools, entities=entities)
            if res["in_stock"]:
                reply = (f"Ji, {res['product']} {res['color']} size {res['size']} "
                         f"available hai — {res['available']} pieces hain, price "
                         f"Rs {res['price']} hai. Order karna hai to qty bata dein."
                         if mix else f"Yes — {res['product']} in {res['color']}, "
                         f"size {res['size']} is in stock ({res['available']} "
                         f"available) at Rs {res['price']}.")
            else:
                alts = res.get("alternatives", [])
                alt_txt = "; ".join(f"{a['color']} {a['size']} ({a['available']})"
                                    for a in alts)
                reply = (f"Maazrat, {res['product']} {res['color']} size "
                         f"{res['size']} out of stock hai (0 available)."
                         + (f" Ye alternatives available hain: {alt_txt}." if alts else ""))
            return self._out(sid, s, reply, "check_stock", "check_stock", 0.95,
                             "ACT", tools=tools, entities=entities)

        # ---- order path
        s["stage"] = "order_details"
        cur = s["items"][0] if s["items"] else item
        if e.get("qty"):
            cur["qty"] = e["qty"]
        if not cur.get("qty"):
            cur["qty"] = 1
        if cur["qty"] > self.rules["order"]["max_qty_per_item"]:
            return self._escalate(sid, s, "quantity_above_limit", "place_order",
                                  entities, mix, f"qty {cur['qty']}")
        variants = self.store.variants_of(cur["product"]) if cur.get("product") else []
        sizes = {v["size"] for v in variants}
        colors = {v["color"] for v in variants}
        if cur.get("product") and len(sizes) > 1 and not cur.get("size"):
            return self._out(sid, s, f"{cur['product']} ka size bata dein — "
                             f"available sizes: {', '.join(sorted(sizes))}.",
                             "place_order", "request_missing_info", 0.85, "ASK",
                             reason="missing_size", entities=entities)
        if cur.get("product") and len(colors) > 1 and not cur.get("color"):
            return self._out(sid, s, f"{cur['product']} ka color bata dein — "
                             f"available colors: {', '.join(sorted(colors))}.",
                             "place_order", "request_missing_info", 0.85, "ASK",
                             reason="missing_color", entities=entities)
        # stock must be checked before we take any order details
        v = self.store.find_variant(cur["product"], cur.get("color"),
                                    cur.get("size")) if cur.get("product") else None
        if v and self.store.available(v["sku"]) < cur["qty"]:
            res = self.tools.check_stock(cur["product"], cur.get("color"),
                                         cur.get("size"))
            tools = [{"name": "check_stock", "result": res}]
            alts = res.get("alternatives", [])
            alt_txt = "; ".join(f"{a['color']} {a['size']} ({a['available']})"
                                for a in alts)
            s["stage"] = None
            reply = (f"Maazrat, {res['product']} {res['color']} size "
                     f"{res['size']} out of stock hai (0 available), is liye "
                     "order nahi ho sakta."
                     + (f" Ye alternatives available hain: {alt_txt}." if alts else ""))
            return self._out(sid, s, reply, "check_stock", "check_stock", 0.95,
                             "ACT", tools=tools, entities=entities)
        cust = s["customer"]
        missing = [k for k in ("name", "phone", "address", "city") if not cust.get(k)]
        if missing:
            return self._out(sid, s, "Order ke liye apna naam, phone number, "
                             "poora address aur city bata dein (ek hi message "
                             "mein likh dein).", "place_order",
                             "request_missing_info", 0.85, "ASK",
                             reason="missing_" + "_".join(missing),
                             entities=entities)
        return self._summarize(sid, s, mix, entities)

    def _summarize(self, sid, s, mix, entities):
        items, product_total, ok = [], 0, True
        for it in s["items"]:
            v = self.store.find_variant(it["product"], it.get("color"), it.get("size"))
            if not v or self.store.available(v["sku"]) < it["qty"]:
                ok = False; break
            items.append({"sku": v["sku"], "qty": it["qty"], "price": v["price"],
                          "name": v["name"], "color": v["color"], "size": v["size"]})
            product_total += v["price"] * it["qty"]
        if not ok:
            return self._escalate(sid, s, "insufficient_stock", "place_order",
                                  entities, mix)
        delivery = self.tools.delivery_charge(s["customer"]["city"], product_total)
        grand = product_total + delivery
        hit = guardrails.check_order_totals(
            product_total, delivery, max(i["qty"] for i in items), self.rules)
        if hit:
            return self._escalate(sid, s, hit[0], "place_order", entities, mix, hit[1])
        if not self.store.reserve(sid, [(i["sku"], i["qty"]) for i in items],
                                   self.rules["order"]["reservation_minutes"]):
            return self._escalate(sid, s, "insufficient_stock", "place_order",
                                  entities, mix)
        s["pending"] = {"items": items, "product_total": product_total,
                        "delivery": delivery, "grand": grand}
        s["stage"] = "confirm"
        lines = "; ".join(f"{i['name']} {i['color']} {i['size']} x{i['qty']} "
                          f"(Rs {i['price'] * i['qty']})" for i in items)
        reply = (f"Order summary: {lines}. Product total Rs {product_total}, "
                 f"delivery Rs {delivery}, grand total Rs {grand} (COD). "
                 "Stock 15 minutes ke liye reserve kar diya hai — confirm "
                 "karne ke liye 'haan' likhein.")
        tools = [{"name": "reserve_stock",
                  "result": {"items": [i["sku"] for i in items]}},
                 {"name": "delivery_charge", "result": {"charge": delivery}}]
        return self._out(sid, s, reply, "place_order", "request_confirmation",
                         0.95, "ACT", tools=tools, entities=entities)

    def _create_order(self, sid, s, e, mix):
        p = s.get("pending", {})
        ids = self.store.create_orders(sid, s["customer"], p.get("items", []),
                                       s["customer"].get("city"), p.get("grand", 0))
        if not ids:
            return self._escalate(sid, s, "reservation_expired_or_failed",
                                  "place_order", {}, mix)
        grand = p.get("grand")
        s["stage"] = None; s["items"] = []; s["pending"] = {}
        reply = (f"Shukriya! Aap ka order confirm ho gaya hai — order number "
                 f"{ids[0]}. Grand total Rs {grand} COD par courier ko ada "
                 "karna hai. Delivery 2-6 working days mein hogi."
                 if mix else f"Thank you! Your order is confirmed — order "
                 f"number {ids[0]}, grand total Rs {grand} payable COD.")
        tools = [{"name": "create_order", "result": {"order_ids": ids,
                                                     "grand_total": grand}}]
        return self._out(sid, s, reply, "place_order", "create_order", 0.98,
                         "ACT", tools=tools)
