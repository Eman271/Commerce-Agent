"""Guardrail layer, driven by data/policy_rules.json.

Runs before any tool that changes state. Returns (reason, detail) for the
first rule that fires, else None. The AI never approves refunds, never
confirms COD orders above the limit, and never takes quantities above the
per-item limit — those always go to a human.
"""
import json
import re
from pathlib import Path

from .nlu import normalize

RULES_PATH = Path(__file__).resolve().parent.parent / "data" / "policy_rules.json"


def load_rules(path=None):
    return json.loads(Path(path or RULES_PATH).read_text(encoding="utf-8-sig"))


PATTERNS = [
    ("legal_threat", r"\b(court|wakeel|lawyer|legal|police|fia|consumer court)\b|bakwas.*(court|police)"),
    ("angry_customer", r"\b(bakwas|fraud|bekar|ghatiya|bewakoof|cheat|dhoka|loot|worst|thug|pagal|sharam)\b"),
    ("damaged_or_wrong_item", r"\b(damaged|defective|torn|broken)\b|phat|kharab|wrong item|ghalat (item|cheez|size|color)"),
    ("refund_request", r"\brefund\b|paisay wapas|paise wapas|paisay wapis|money back|\breturn\b.*(money|pais)|wapas kar.*pais"),
    ("return_request", r"\breturn karna\b|\breturn\b(?!.*exchange)"),
    ("human_request", r"insan|owner se|human|banda (bula|se|chahiye)|staff se baat|manager se|real banda|bot se nahi|real person"),
    ("wrong_item_received", r"mangwaya tha|galat (bhej|aaya|aya)|wrong (bhej|sent)"),
    ("discount_bargaining", r"\b(discount|bargain)\b|kam karo|sasta karo|rate kam|special price|deal karo"),
    ("online_payment_request", r"easypaisa|jazzcash|bank transfer|account number|online payment|card se pay"),
    ("order_cancel_request", r"\bcancel\b|order band|mansookh"),
    ("order_change_request", r"address change|\bchange\b[^.]*\border\b|\border\b[^.]*\bchange\b|galat address"),
]


def check_text(text, rules=None):
    t = normalize(text)
    for reason, pat in PATTERNS:
        if re.search(pat, t):
            # 'return' inside an exchange request is an exchange, not a refund
            if reason in ("return_request",) and "exchange" in t:
                continue
            return reason, f"guardrail matched: {reason}"
    # escalation keywords straight from policy_rules.json as a backstop
    if rules:
        for kw in rules.get("escalation_keywords", []):
            if kw in t and kw not in ("return", "human"):
                return "policy_keyword_" + kw.replace(" ", "_"), f"keyword: {kw}"
    return None


def check_order_totals(product_total, delivery, qty_per_item, rules):
    """Return (reason, detail) if an order about to be confirmed breaks a rule."""
    if qty_per_item and qty_per_item > rules["order"]["max_qty_per_item"]:
        return ("quantity_above_limit",
                f"qty {qty_per_item} > max {rules['order']['max_qty_per_item']}")
    grand = product_total + delivery
    if grand > rules["payment"]["cod_max_total_without_human"]:
        return ("cod_above_limit",
                f"grand total {grand} > COD limit "
                f"{rules['payment']['cod_max_total_without_human']}")
    return None
