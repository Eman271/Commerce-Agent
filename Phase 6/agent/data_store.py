"""SQLite data store for Saira Fashion House.

Pure stdlib (sqlite3/csv). One Store object owns one connection guarded by a
lock; order creation and reservations run inside BEGIN IMMEDIATE transactions
so two customers can never reserve the same last unit.
"""
import csv
import json
import sqlite3
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"

SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog(
  sku TEXT PRIMARY KEY, product_id TEXT, name TEXT, category TEXT, color TEXT,
  size TEXT, original_price INTEGER, price INTEGER, stock INTEGER,
  is_sale INTEGER, description TEXT);
CREATE TABLE IF NOT EXISTS orders(
  order_id INTEGER PRIMARY KEY, customer_name TEXT, phone TEXT, sku TEXT,
  qty INTEGER, city TEXT, status TEXT, order_date TEXT, delivered_date TEXT,
  courier TEXT, tracking_no TEXT, total INTEGER, session_id TEXT);
CREATE TABLE IF NOT EXISTS reservations(
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, sku TEXT,
  qty INTEGER, expires_at REAL, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS conversations(
  session_id TEXT PRIMARY KEY, started_at REAL, turns INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT,
  text TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS escalations(
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, reason TEXT,
  detail TEXT, status TEXT DEFAULT 'open', created_at REAL);
CREATE TABLE IF NOT EXISTS exchanges(
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, old_sku TEXT,
  replacement_sku TEXT, courier_charge INTEGER, created_at REAL);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, session_id TEXT,
  action TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT UNIQUE,
  phone TEXT, salt TEXT, pass_hash TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS auth_tokens(
  token TEXT PRIMARY KEY, user_id INTEGER, created_at REAL);
CREATE TABLE IF NOT EXISTS reviews(
  id INTEGER PRIMARY KEY AUTOINCREMENT, stars INTEGER, user_name TEXT,
  created_at REAL);
"""


class Store:
    def __init__(self, db_path=None, data_dir=None):
        self.db_path = str(db_path or (BASE / "shop.db"))
        self.data_dir = Path(data_dir or DATA)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False,
                                    isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.executescript(SCHEMA)
            if self.conn.execute("SELECT COUNT(*) c FROM catalog").fetchone()["c"] == 0:
                self._seed()

    # ------------------------------------------------------------------ seed
    def _seed(self):
        with open(self.data_dir / "catalog.csv", newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        self.conn.executemany(
            "INSERT OR REPLACE INTO catalog VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [(r["sku"], r["product_id"], r["name"], r["category"], r["color"],
              r["size"], int(r["original_price"]), int(r["price"]),
              int(r["stock"]), 1 if r["is_sale"] == "True" else 0,
              r["description"]) for r in rows])
        with open(self.data_dir / "orders.csv", newline="", encoding="utf-8-sig") as f:
            orows = list(csv.DictReader(f))
        self.conn.executemany(
            "INSERT OR REPLACE INTO orders(order_id,customer_name,phone,sku,qty,"
            "city,status,order_date,delivered_date,courier,tracking_no,total,"
            "session_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
            [(int(r["order_id"]), r["customer_name"], r["phone"], r["sku"],
              int(r["qty"]), r["city"], r["status"], r["order_date"],
              r["delivered_date"] or None, r["courier"] or None,
              r["tracking_no"] or None, int(r["total"])) for r in orows])

    def reset(self):
        with self.lock:
            for t in ("catalog", "orders", "reservations", "conversations",
                      "messages", "escalations", "exchanges", "audit", "kv"):
                self.conn.execute(f"DELETE FROM {t}")
            self._seed()

    def close(self):
        with self.lock:
            self.conn.close()

    # --------------------------------------------------------------- catalog
    def variant(self, sku):
        with self.lock:
            r = self.conn.execute("SELECT * FROM catalog WHERE sku=?", (sku,)).fetchone()
            return dict(r) if r else None

    def find_variant(self, name, color=None, size=None):
        q = "SELECT * FROM catalog WHERE lower(name)=lower(?)"
        args = [name]
        if color:
            q += " AND lower(color)=lower(?)"; args.append(color)
        if size:
            q += " AND upper(size)=upper(?)"; args.append(size)
        with self.lock:
            r = self.conn.execute(q, args).fetchone()
            return dict(r) if r else None

    def variants_of(self, name):
        with self.lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT * FROM catalog WHERE lower(name)=lower(?)", (name,))]

    def product_names(self):
        with self.lock:
            return [r["name"] for r in self.conn.execute(
                "SELECT DISTINCT name FROM catalog ORDER BY name")]

    def catalog_search(self, q=None, category=None, in_stock=None, limit=50, offset=0):
        sql = "SELECT * FROM catalog WHERE 1=1"
        args = []
        if q:
            sql += " AND (lower(name) LIKE ? OR lower(category) LIKE ? OR lower(color) LIKE ?)"
            args += [f"%{q.lower()}%"] * 3
        if category:
            sql += " AND lower(category)=lower(?)"; args.append(category)
        if in_stock:
            sql += " AND stock>0"
        total = self.conn.execute(sql.replace("SELECT *", "SELECT COUNT(*) c"), args).fetchone()["c"]
        rows = [dict(r) for r in self.conn.execute(
            sql + " ORDER BY name,color,size LIMIT ? OFFSET ?", args + [limit, offset])]
        for r in rows:
            r["available"] = self.available(r["sku"])
        return {"total": total, "items": rows}

    # ----------------------------------------------------------- reservations
    def _expire(self):
        self.conn.execute(
            "UPDATE reservations SET active=0 WHERE active=1 AND expires_at<?",
            (time.time(),))

    def reserved_qty(self, sku):
        with self.lock:
            self._expire()
            r = self.conn.execute(
                "SELECT COALESCE(SUM(qty),0) s FROM reservations "
                "WHERE sku=? AND active=1", (sku,)).fetchone()
            return r["s"]

    def available(self, sku):
        v = self.variant(sku)
        if not v:
            return 0
        return v["stock"] - self.reserved_qty(sku)

    def reserve(self, session_id, items, minutes=15):
        """items: list of (sku, qty). Atomic: all-or-nothing."""
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                self._expire()
                for sku, qty in items:
                    if self.available(sku) < qty:
                        self.conn.execute("ROLLBACK")
                        return False
                exp = time.time() + minutes * 60
                for sku, qty in items:
                    self.conn.execute(
                        "INSERT INTO reservations(session_id,sku,qty,expires_at)"
                        " VALUES(?,?,?,?)", (session_id, sku, qty, exp))
                self.conn.execute("COMMIT")
                return True
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def release(self, session_id):
        with self.lock:
            self.conn.execute(
                "UPDATE reservations SET active=0 WHERE session_id=? AND active=1",
                (session_id,))

    def create_orders(self, session_id, customer, items, city, grand_total):
        """Convert this session's active reservations into orders.

        items: list of dicts {sku, qty, price}. Stock is decremented inside the
        same IMMEDIATE transaction, so reserved units cannot be double-sold.
        Returns list of new order ids.
        """
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                self._expire()
                ids = []
                next_id = (self.conn.execute(
                    "SELECT COALESCE(MAX(order_id),20000) m FROM orders"
                ).fetchone()["m"] + 1)
                for it in items:
                    res = self.conn.execute(
                        "SELECT id FROM reservations WHERE session_id=? AND sku=?"
                        " AND active=1", (session_id, it["sku"])).fetchone()
                    if not res:
                        self.conn.execute("ROLLBACK")
                        return []
                    self.conn.execute("UPDATE reservations SET active=0 WHERE id=?",
                                      (res["id"],))
                    self.conn.execute(
                        "UPDATE catalog SET stock=stock-? WHERE sku=? AND stock>=?",
                        (it["qty"], it["sku"], it["qty"]))
                    total = grand_total if len(items) == 1 else it["price"] * it["qty"]
                    self.conn.execute(
                        "INSERT INTO orders(order_id,customer_name,phone,sku,qty,"
                        "city,status,order_date,delivered_date,courier,tracking_no,"
                        "total,session_id) VALUES(?,?,?,?,?,?,'Placed',date('now'),"
                        "NULL,NULL,NULL,?,?)",
                        (next_id, customer.get("name"), customer.get("phone"),
                         it["sku"], it["qty"], city, total, session_id))
                    ids.append(next_id)
                    next_id += 1
                self.conn.execute("COMMIT")
                return ids
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    # ---------------------------------------------------------------- orders
    def get_order(self, order_id):
        with self.lock:
            r = self.conn.execute("SELECT * FROM orders WHERE order_id=?",
                                  (int(order_id),)).fetchone()
            return dict(r) if r else None

    def list_orders(self, limit=100):
        with self.lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT * FROM orders ORDER BY order_id DESC LIMIT ?", (limit,))]

    def add_exchange(self, order_id, old_sku, replacement_sku, charge):
        with self.lock:
            self.conn.execute(
                "INSERT INTO exchanges(order_id,old_sku,replacement_sku,"
                "courier_charge,created_at) VALUES(?,?,?,?,?)",
                (order_id, old_sku, replacement_sku, charge, time.time()))

    # ------------------------------------------------------- logs / dashboard
    def log_message(self, session_id, role, text):
        with self.lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO conversations VALUES(?,?,0)", (session_id, time.time()))
            self.conn.execute(
                "UPDATE conversations SET turns=turns+1 WHERE session_id=?", (session_id,))
            self.conn.execute(
                "INSERT INTO messages(session_id,role,text,ts) VALUES(?,?,?,?)",
                (session_id, role, text, time.time()))

    def audit(self, session_id, action, detail):
        if isinstance(detail, (dict, list)):
            detail = json.dumps(detail)
        with self.lock:
            self.conn.execute(
                "INSERT INTO audit(ts,session_id,action,detail) VALUES(?,?,?,?)",
                (time.time(), session_id, action, str(detail)[:500]))

    def add_escalation(self, session_id, reason, detail):
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO escalations(session_id,reason,detail,created_at)"
                " VALUES(?,?,?,?)", (session_id, reason, str(detail)[:500], time.time()))
            return cur.lastrowid

    def list_escalations(self, status=None):
        sql = "SELECT * FROM escalations"
        args = []
        if status:
            sql += " WHERE status=?"; args.append(status)
        with self.lock:
            return [dict(r) for r in self.conn.execute(
                sql + " ORDER BY id DESC LIMIT 200", args)]

    def resolve_escalation(self, esc_id):
        with self.lock:
            cur = self.conn.execute(
                "UPDATE escalations SET status='resolved' WHERE id=?", (esc_id,))
            return cur.rowcount == 1

    def set_kv(self, key, value):
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO kv VALUES(?,?)",
                              (key, json.dumps(value)))

    def get_kv(self, key):
        with self.lock:
            r = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            return json.loads(r["value"]) if r else None

    def dashboard(self):
        with self.lock:
            c = self.conn
            conv = c.execute("SELECT COUNT(*) n FROM conversations").fetchone()["n"]
            ords = c.execute("SELECT COUNT(*) n, COALESCE(SUM(total),0) rev FROM orders").fetchone()
            esc = c.execute("SELECT COUNT(*) n FROM escalations WHERE status='open'").fetchone()["n"]
            esc_total = c.execute("SELECT COUNT(*) n FROM escalations").fetchone()["n"]
            low = [dict(r) for r in c.execute(
                "SELECT sku,name,color,size,stock FROM catalog WHERE stock BETWEEN 1 AND 4 ORDER BY stock LIMIT 20")]
            out = [dict(r) for r in c.execute(
                "SELECT sku,name,color,size,stock FROM catalog WHERE stock=0 LIMIT 20")]
            top = [dict(r) for r in c.execute(
                "SELECT cat.name, COUNT(*) n FROM orders o JOIN catalog cat ON cat.sku=o.sku"
                " GROUP BY cat.name ORDER BY n DESC LIMIT 5")]
            intents = {}
            for r in c.execute("SELECT detail FROM audit WHERE action='decision'"):
                try:
                    intents[json.loads(r["detail"]).get("intent", "?")] = \
                        intents.get(json.loads(r["detail"]).get("intent", "?"), 0) + 1
                except Exception:
                    pass
            handled = round(100.0 * (conv - esc_total) / conv, 1) if conv else 100.0
            return {
                "conversations": conv,
                "orders": ords["n"],
                "revenue": ords["rev"],
                "open_escalations": esc,
                "total_escalations": esc_total,
                "handled_percent": max(handled, 0.0),
                "intent_counts": intents,
                "top_products": top,
                "low_stock": low,
                "out_of_stock": out,
                "recent_escalations": self.list_escalations()[:10],
                "recent_audit": [dict(r) for r in c.execute(
                    "SELECT * FROM audit ORDER BY id DESC LIMIT 20")],
            }

    # ------------------------------------------------------------- accounts
    def create_user(self, name, email, phone, password):
        import hashlib, os
        salt = os.urandom(16).hex()
        h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 60000).hex()
        with self.lock:
            try:
                cur = self.conn.execute(
                    "INSERT INTO users(name,email,phone,salt,pass_hash,created_at)"
                    " VALUES(?,?,?,?,?,?)",
                    (name, email.lower(), phone, salt, h, time.time()))
            except sqlite3.IntegrityError:
                return None
            return cur.lastrowid

    def verify_user(self, email, password):
        import hashlib
        with self.lock:
            r = self.conn.execute("SELECT * FROM users WHERE email=?",
                                  (email.lower(),)).fetchone()
            if not r:
                return None
            h = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                    bytes.fromhex(r["salt"]), 60000).hex()
            if h != r["pass_hash"]:
                return None
            return {"id": r["id"], "name": r["name"], "email": r["email"],
                    "phone": r["phone"]}

    def new_token(self, user_id):
        import secrets
        tok = secrets.token_hex(24)
        with self.lock:
            self.conn.execute("INSERT INTO auth_tokens VALUES(?,?,?)",
                              (tok, user_id, time.time()))
        return tok

    def user_by_token(self, token):
        if not token:
            return None
        with self.lock:
            r = self.conn.execute(
                "SELECT u.id,u.name,u.email,u.phone FROM auth_tokens t"
                " JOIN users u ON u.id=t.user_id WHERE t.token=?",
                (token,)).fetchone()
            return dict(r) if r else None

    def orders_for_phone(self, phone):
        digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
        if not digits:
            return []
        with self.lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT * FROM orders WHERE phone=? ORDER BY order_id DESC",
                (digits,))]

    # -------------------------------------------------------------- reviews
    def add_review(self, stars, user_name=None):
        with self.lock:
            self.conn.execute("INSERT INTO reviews(stars,user_name,created_at)"
                              " VALUES(?,?,?)", (int(stars), user_name, time.time()))

    def reviews_summary(self):
        with self.lock:
            rows = [r["stars"] for r in self.conn.execute("SELECT stars FROM reviews")]
        if not rows:
            return {"count": 0, "average": None, "distribution": {}}
        dist = {}
        for st in rows:
            dist[st] = dist.get(st, 0) + 1
        return {"count": len(rows), "average": round(sum(rows) / len(rows), 2),
                "distribution": dist}
