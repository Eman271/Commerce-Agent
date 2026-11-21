"""Natural-language understanding: pure stdlib.

Normalizes Roman Urdu / English code-mixed text, then extracts entities:
product, color, size, quantity, city, phone, name, address, order id, budget.
Synonym tables come from the Phase 2 dataset work (kala/blk -> Black,
safaid -> White, mdm -> M, ...). Product matching is token-overlap plus
difflib fuzzy matching, so 'kurtta' still finds 'Kurta'.
"""
import difflib
import re

COLOR_SYNONYMS = {
    "black": ["black", "blk", "blak", "kala", "kaala"],
    "white": ["white", "wht", "safaid", "safed", "sufaid"],
    "pink": ["pink", "gulabi"],
    "blue": ["blue", "neela"],
    "navy": ["navy", "navi", "navy blue"],
    "dark blue": ["dark blue"],
    "sky blue": ["sky blue", "aasmaani"],
    "light blue": ["light blue"],
    "green": ["green", "sabz", "hara"],
    "emerald": ["emerald"],
    "red": ["red", "surkh", "laal"],
    "maroon": ["maroon", "marun", "mahroon"],
    "yellow": ["yellow", "peela"],
    "brown": ["brown", "bhura", "bhoora"],
    "grey": ["grey", "gray", "surmai"],
    "beige": ["beige"],
    "cream": ["cream"],
    "gold": ["gold", "golden", "sunahra"],
    "mustard": ["mustard"],
    "olive": ["olive"],
    "peach": ["peach"],
    "lilac": ["lilac"],
    "mint": ["mint"],
    "teal": ["teal"],
    "burgundy": ["burgundy", "wine"],
    "wine": ["wine"],
    "camel": ["camel"],
    "charcoal": ["charcoal"],
    "ivory": ["ivory"],
    "khaki": ["khaki"],
    "tan": ["tan"],
}
# canonical color name (as in catalog.csv) keyed by lowercase
COLOR_CANON = {}
for _name in ["Black", "White", "Pink", "Blue", "Navy", "Dark Blue", "Sky Blue",
              "Light Blue", "Green", "Emerald", "Red", "Maroon", "Yellow",
              "Brown", "Grey", "Beige", "Cream", "Gold", "Mustard", "Olive",
              "Peach", "Lilac", "Mint", "Teal", "Burgundy", "Wine", "Camel",
              "Charcoal", "Ivory", "Khaki", "Tan"]:
    COLOR_CANON[_name.lower()] = _name

SIZE_SYNONYMS = {
    "s": ["small", "s", "chota", "chhota"],
    "m": ["medium", "m", "mdm", "med", "midium"],
    "l": ["large", "l", "bara", "barra"],
    "xl": ["xl", "extra large", "extralarge"],
    "free": ["free", "free size", "one size"],
}
SIZE_CANON = {"s": "S", "m": "M", "l": "L", "xl": "XL", "free": "Free"}

WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "panch": 5,
    "paanch": 5, "chay": 6, "chhe": 6, "saat": 7, "aath": 8, "nau": 9,
    "das": 10, "gyarah": 11, "barah": 12,
}

CITIES = ["Lahore", "Gujranwala", "Sialkot", "Sheikhupura", "Faisalabad",
          "Islamabad", "Rawalpindi", "Karachi", "Peshawar", "Multan",
          "Quetta", "Bahawalpur", "Hyderabad", "Sargodha", "Gujrat",
          "Sukkur", "Larkana", "Abbottabad", "Mardan", "Kasur", "Okara",
          "Sahiwal", "Jhang", "Rahim Yar Khan", "Dera Ghazi Khan"]

URDU_WORDS = set("""hai hain mein main me ka ki ke ko se par pe aur ya kya kitna
kitne kitni kab kahan kyun chahiye chahta chahti karo kar karna karni do dena
de bhej bhejo batao bata dikhao nahi haan ji acha theek sahi bhai mujhe mera
meri mera hai wala wali ye yeh wo woh bhi tu tum aap ne to hi gaya liya tha
thi pehle abhi jaldi suno arre yaar pata""".split())

PRODUCT_WORD_FIX = {"tshirt": "t-shirt", "t": "t-shirt", "kurtta": "kurta",
                    "kurti": "kurti", "shalwar": "shalwar", "kameez": "kameez",
                    "jootay": "shoes", "joota": "shoes", "juti": "khussa"}


def normalize(text):
    t = str(text or "").lower().strip()
    # 0300-1234567 / 0300 1234567 -> 03001234567
    t = re.sub(r"\b(03\d{2})[-\s](\d{7})\b", r"\1\2", t)
    t = re.sub(r"\b(03\d{2})\s(\d{3})\s(\d{4})\b", r"\1\2\3", t)
    t = re.sub(r"[^\w\s\-]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def urdu_share(text):
    words = [w for w in normalize(text).split() if w.isalpha()]
    if not words:
        return 0.0
    return sum(1 for w in words if w in URDU_WORDS) / len(words)


def extract_phone(text):
    t = re.sub(r"[-\s]", "", str(text or ""))
    m = re.search(r"(03\d{9})", t)
    return m.group(1) if m else None


def extract_order_id(text):
    t = normalize(text)
    m = re.search(r"\border\D{0,12}?(\d{5})\b", t) or re.search(r"\b(1\d{4})\b", t)
    return int(m.group(1)) if m else None


def extract_budget(text):
    t = normalize(text)
    m = re.search(r"(?:budget|tak|around|under|below|max)\D{0,6}?(\d{3,6})", t) or \
        re.search(r"(\d{3,6})\s*(?:tak|ke around|budget)", t)
    return int(m.group(1)) if m else None


def extract_city(text):
    t = " " + normalize(text) + " "
    for city in sorted(CITIES, key=len, reverse=True):
        if f" {city.lower()} " in t or t.strip().endswith(city.lower()):
            return city
    return None


def _color_in(text):
    t = " " + normalize(text) + " "
    hits = []
    for canon_low, syns in COLOR_SYNONYMS.items():
        for s in syns:
            if f" {s} " in t or t.startswith(f"{s} ") or t.strip().endswith(s):
                hits.append((t.find(s), COLOR_CANON.get(canon_low, canon_low.title())))
                break
    hits.sort()
    return hits[0][1] if hits else None


def all_colors_in(text):
    t = " " + normalize(text) + " "
    found = []
    for canon_low, syns in COLOR_SYNONYMS.items():
        if any(f" {s} " in t for s in syns):
            found.append(COLOR_CANON.get(canon_low, canon_low.title()))
    return found


def extract_size(text):
    t = normalize(text)
    m = re.search(r"\b(\d{1,2})\s*-\s*(\d)\s*y\b", t)
    if m:
        return f"{m.group(1)}-{m.group(2)}Y"
    m = re.search(r"\bsize\s+(\d{1,2}|s|m|l|xl|free)\b", t)
    if m:
        tok = m.group(1)
        return SIZE_CANON.get(tok, tok)
    # standalone numeric size (shoes / waist): 30-56 or 8-11, not a phone/qty
    words = t.split()
    for i, w in enumerate(words):
        if w in SIZE_SYNONYMS and w not in ("s", "m", "l"):
            return SIZE_CANON[w]
    for syn, canon in (("extra large", "XL"), ("free size", "Free"),
                       ("medium", "M"), ("mdm", "M"), ("small", "S"),
                       ("large", "L")):
        if re.search(rf"\b{syn}\b", t):
            return canon
    # single letter size as its own word
    m = re.search(r"(?:^|\s)(xl|s|m|l)(?:\s|$)", t)
    if m:
        return SIZE_CANON[m.group(1)]
    m = re.search(r"\b(3[0-9]|4[01]|5[246]|2[0-9]|1[0-1]|[89])\b(?!\d)", t)
    if m and not re.search(r"\b(order|rs|rupees)\b", t):
        # only treat as size when the word 'size' or a product context exists
        if "size" in t or "number" in t:
            return m.group(1)
    return None


def extract_qty(text):
    t = normalize(text)
    m = re.search(r"\b(\d{1,3})\s*(?:pieces?|pcs|items?|qty|quantity|chahiye|order|bhej|same)\b", t)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d{1,3})\s+(?:same\s+)?(?:bhej|order|chahiye)", t)
    if m:
        return int(m.group(1))
    for w, n in WORD_NUMBERS.items():
        if re.search(rf"\b{w}\s+(?:chahiye|bhej|order|piece|same)", t):
            return n
    m = re.search(r"^\s*(\d{1,3})\s*(?:order|bhej)", t)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d{1,2})\s*$", t)
    return None


def match_product(text, product_names):
    """Return best-matching catalog product name, or None."""
    t = normalize(text)
    words = [PRODUCT_WORD_FIX.get(w, w) for w in t.split()]
    t2 = " ".join(words)
    best, best_score = None, 0
    for name in product_names:
        # numeric / one-letter tokens ('2' in 'Lawn 2-Piece') never count —
        # they collide with quantities and sizes in customer messages
        name_words = [w for w in re.split(r"[\s\-]+", name.lower())
                      if w.isalpha() and len(w) > 1]
        score = 0
        for nw in name_words:
            if nw in words:
                score += 2
            elif difflib.get_close_matches(nw, words, n=1, cutoff=0.83):
                score += 1
        # a distinctive token (not generic 'women/men/kids') must hit exactly
        generic = {"women", "men", "kids", "wear"}
        distinctive = [w for w in name_words if w not in generic]
        if distinctive and not any(w in words for w in distinctive):
            score = 0
        if score > best_score:
            best, best_score = name, score
    return best if best_score >= 2 else None


def extract_name_address(text):
    """Heuristics for the order-details turn."""
    raw = str(text or "")
    phone = extract_phone(raw)
    city = extract_city(raw)
    name = None
    m = re.search(r"mera naam\s+([A-Za-z ]+?)(?:\s+hai\b|,|$)", raw, re.I)
    if m:
        name = m.group(1).strip().title()
    elif phone:
        before = raw[:raw.find(phone[:4])] if phone[:4] in raw else ""
        before = re.sub(r"[^A-Za-z ,]", " ", before).strip(" ,")
        cand = before.split(",")[0].strip()
        if 2 <= len(cand) <= 40 and len(cand.split()) <= 4:
            name = cand.title()
    address = None
    addr_match = re.search(r"((?:house|flat|shop|plot|street|road|mohalla|block|sector|town|gulberg|cantt|model|dha|phase|colony|chowk|bazaar|market)[^,]*)",
                           raw, re.I)
    if addr_match:
        address = re.sub(r"\s+", " ", raw[addr_match.start():]).strip(" ,")
        address = re.sub(r"\b03\d{9}\b", "", address).strip(" ,")
        if city and address.lower().endswith(city.lower()):
            address = address[: -len(city)].strip(" ,")
    if not address and phone and name:
        # fallback: whatever is left after removing name / phone / city /
        # filler is the address ("Nida Rauf 03041112222 DHA phase 5 Lahore")
        rest = raw
        rest = re.sub(r"03\d{9}|03\d{2}[-\s]\d{7}", " ", rest)
        rest = re.sub(re.escape(name), " ", rest, flags=re.I)
        if city:
            rest = re.sub(re.escape(city), " ", rest, flags=re.I)
        rest = re.sub(r"mera naam|hai|number|address|phone|mera|deta hun|"
                      r"ye raha|ye hai", " ", rest, flags=re.I)
        rest = re.sub(r"[^A-Za-z0-9 ]", " ", rest)
        rest = re.sub(r"\s+", " ", rest).strip(" ,")
        if len(rest) >= 4:
            address = rest.title()
    return {"name": name, "phone": phone, "city": city, "address": address}


def extract(text, product_names):
    """Full entity extraction for one customer message."""
    return {
        "product": match_product(text, product_names),
        "color": _color_in(text),
        "colors": all_colors_in(text),
        "size": extract_size(text),
        "qty": extract_qty(text),
        "city": extract_city(text),
        "phone": extract_phone(text),
        "order_id": extract_order_id(text),
        "budget": extract_budget(text),
        "details": extract_name_address(text),
    }
