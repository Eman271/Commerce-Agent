"""Structured backend tools. Deterministic lookups over the SQLite store —
the agent never invents a price, a stock count or an order status.
"""
from datetime import date


def _parse(d):
    return date.fromisoformat(d) if d else None


class Tools:
    def __init__(self, store, rules, today="2026-10-17"):
        self.store = store
        self.rules = rules
        self.today = _parse(today)

    # ---------------------------------------------------------------- stock
    def check_stock(self, product, color=None, size=None):
        v = self.store.find_variant(product, color, size) if (color or size) else None
        if v is None:
            variants = self.store.variants_of(product)
            if not variants:
                return {"found": False, "product": product}
            if color and size:
                return {"found": False, "product": product,
                        "alternatives": self._alternatives(product, color, size)}
            v = variants[0]
        avail = self.store.available(v["sku"])
        result = {"found": True, "sku": v["sku"], "product": v["name"],
                  "color": v["color"], "size": v["size"], "price": v["price"],
                  "is_sale": bool(v["is_sale"]), "available": avail,
                  "in_stock": avail > 0}
        if avail <= 0:
            result["alternatives"] = self._alternatives(product, v["color"], v["size"])
        return result

    def _alternatives(self, product, color=None, size=None):
        alts = []
        for v in self.store.variants_of(product):
            if (v["color"], v["size"]) == (color, size):
                continue
            avail = self.store.available(v["sku"])
            if avail > 0:
                alts.append({"sku": v["sku"], "color": v["color"],
                             "size": v["size"], "price": v["price"],
                             "available": avail})
        # prefer same color (different size), then same size (different color)
        alts.sort(key=lambda a: (a["color"] != color, a["size"] != size))
        return alts[:4]

    # ------------------------------------------------------------ recommend
    def recommend_products(self, budget=None, category=None, limit=5):
        lo = int(budget * 0.75) if budget else 0
        hi = int(budget * 1.25) if budget else 10 ** 9
        rows = self.store.catalog_search(limit=1000)["items"]
        seen, out = set(), []
        for r in rows:
            if r["name"] in seen or not (lo <= r["price"] <= hi):
                continue
            if category and category.lower() not in r["category"].lower() \
                    and category.lower() not in r["name"].lower():
                continue
            if r["available"] <= 0:
                continue
            seen.add(r["name"])
            out.append({"sku": r["sku"], "product": r["name"],
                        "category": r["category"], "color": r["color"],
                        "size": r["size"], "price": r["price"],
                        "available": r["available"]})
            if len(out) >= limit:
                break
        return out

    # ------------------------------------------------------------- delivery
    def delivery_charge(self, city, product_total):
        d = self.rules["delivery"]
        if product_total >= d["free_delivery_min_product_total"]:
            return 0
        if city and city.lower() in [c.lower() for c in d["tier_a_cities"]]:
            return d["tier_a_charge"]
        return d["default_charge"]

    def delivery_eta(self, city):
        d = self.rules["delivery"]
        if city and city.lower() in [c.lower() for c in d["tier_a_cities"]]:
            return tuple(d["eta_days_tier_a"])
        return tuple(d["eta_days_other"])

    # ---------------------------------------------------------- order status
    def get_order_status(self, order_id, phone):
        order = self.store.get_order(order_id)
        if not order:
            return {"found": False}
        if not phone or order["phone"] != phone:
            # privacy rule: share nothing at all on a mismatch
            return {"found": True, "phone_match": False}
        return {"found": True, "phone_match": True, "status": order["status"],
                "courier": order["courier"], "tracking_no": order["tracking_no"],
                "city": order["city"], "total": order["total"],
                "order_date": order["order_date"]}

    # -------------------------------------------------------------- exchange
    def check_exchange(self, order_id, phone, want_size=None, want_color=None):
        order = self.store.get_order(order_id)
        if not order:
            return {"eligible": False, "reason": "order_not_found"}
        if not phone or order["phone"] != phone:
            return {"eligible": False, "reason": "phone_mismatch"}
        if order["status"] != "Delivered" or not order["delivered_date"]:
            return {"eligible": False, "reason": "order_not_delivered"}
        item = self.store.variant(order["sku"])
        if not item:
            return {"eligible": False, "reason": "item_not_found"}
        ex = self.rules["exchange"]
        days = (self.today - _parse(order["delivered_date"])).days
        if days > ex["window_days"]:
            return {"eligible": False, "reason": "outside_7_day_window",
                    "days_since_delivery": days}
        if item["is_sale"] and not ex["sale_items_allowed"]:
            return {"eligible": False, "reason": "sale_item_not_exchangeable",
                    "days_since_delivery": days}
        if item["category"] in ex["non_exchangeable_categories"]:
            return {"eligible": False, "reason": "category_not_exchangeable",
                    "days_since_delivery": days}
        size = want_size or item["size"]
        color = want_color or item["color"]
        repl = self.store.find_variant(item["name"], color, size)
        if not repl or repl["sku"] == item["sku"]:
            return {"eligible": False, "reason": "replacement_not_specified",
                    "days_since_delivery": days}
        if self.store.available(repl["sku"]) <= 0:
            return {"eligible": False, "reason": "replacement_out_of_stock",
                    "days_since_delivery": days}
        return {"eligible": True, "days_since_delivery": days,
                "replacement_sku": repl["sku"], "product": item["name"],
                "old_sku": item["sku"],
                "exchange_courier_charge": ex["exchange_courier_charge"]}
