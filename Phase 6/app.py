"""F26-07 — Saira Fashion House AI Sales & Customer Support Agent.

Run:  pip install -r requirements.txt
      python app.py
Then open http://127.0.0.1:8000

The runtime agent is pure stdlib (see agent/); FastAPI only serves HTTP.
"""
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, Header, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from agent.data_store import Store
from agent.engine import Engine

BASE = Path(__file__).resolve().parent
store = Store(BASE / "shop.db")
engine = Engine(store)

app = FastAPI(title="Saira Fashion House")


class ChatIn(BaseModel):
    session_id: str = "web-1"
    message: str


class AuthIn(BaseModel):
    name: str | None = None
    email: str
    phone: str | None = None
    password: str


class ReviewIn(BaseModel):
    stars: int
    user_name: str | None = None


class ContentionIn(BaseModel):
    sku: str | None = None
    product_id: str | None = None
    size: str | None = None
    customers: int = 5
    qty: int = 1


@app.get("/")
def home():
    idx = BASE / "static" / "index.html"
    return FileResponse(idx) if idx.exists() else JSONResponse(
        {"service": "F26-07 agent", "docs": "/docs"})


@app.get("/assets/{name}")
def asset(name: str):
    p = BASE / "static" / "assets" / Path(name).name
    return FileResponse(p) if p.exists() else JSONResponse(
        {"error": "asset not found"}, status_code=404)


@app.post("/api/auth/signup")
def signup(body: AuthIn):
    if not body.name or not body.phone:
        return JSONResponse({"error": "name and phone are required"}, status_code=400)
    pw = body.password
    if len(pw) < 8:
        return JSONResponse({"error": "Password must be at least 8 characters long."}, status_code=400)
    if not any(c.isdigit() for c in pw):
        return JSONResponse({"error": "Password must contain a number."}, status_code=400)
    if not any(not c.isalnum() for c in pw):
        return JSONResponse({"error": "Password must contain a symbol such as @ # or !"}, status_code=400)
    uid = store.create_user(body.name, body.email, body.phone, body.password)
    if uid is None:
        return JSONResponse({"error": "an account with this email already exists"}, status_code=409)
    user = {"id": uid, "name": body.name, "email": body.email.lower(), "phone": body.phone}
    return {"token": store.new_token(uid), "user": user}


@app.post("/api/auth/login")
def login(body: AuthIn):
    user = store.verify_user(body.email, body.password)
    if not user:
        return JSONResponse({"error": "email or password is incorrect"}, status_code=401)
    return {"token": store.new_token(user["id"]), "user": user}


@app.get("/api/auth/me")
def me(authorization: str | None = Header(default=None)):
    user = store.user_by_token((authorization or "").replace("Bearer ", ""))
    return {"user": user}


@app.get("/api/my/orders")
def my_orders(authorization: str | None = Header(default=None)):
    user = store.user_by_token((authorization or "").replace("Bearer ", ""))
    if not user:
        return JSONResponse({"error": "login required"}, status_code=401)
    return {"user": user, "orders": store.orders_for_phone(user["phone"])}


@app.post("/api/reviews")
def add_review(body: ReviewIn, authorization: str | None = Header(default=None)):
    if not store.user_by_token((authorization or "").replace("Bearer ", "")):
        return JSONResponse({"error": "first sign in"}, status_code=401)
    if body.stars < 1 or body.stars > 5:
        return JSONResponse({"error": "stars must be 1 to 5"}, status_code=400)
    store.add_review(body.stars, body.user_name)
    return {"ok": True, "summary": store.reviews_summary()}


@app.get("/api/reviews")
def reviews():
    return store.reviews_summary()


@app.post("/api/chat")
def chat(body: ChatIn):
    return engine.handle(body.session_id, body.message)


@app.get("/api/status")
def status():
    return {"ok": True, "service": "F26-07 Saira Fashion House Agent",
            "products": len(store.product_names()),
            "variants": store.catalog_search(limit=1)["total"],
            "ml_model_loaded": engine.ml_model is not None}


@app.get("/api/catalog")
def catalog(q: str | None = None, category: str | None = None,
            in_stock: bool = False, limit: int = Query(50, le=500),
            offset: int = 0):
    return store.catalog_search(q=q, category=category,
                                in_stock=in_stock, limit=limit, offset=offset)


@app.get("/api/orders")
def orders(limit: int = 100):
    return {"orders": store.list_orders(limit)}


@app.get("/api/dashboard")
def dashboard():
    return store.dashboard()


@app.get("/api/escalations")
def escalations(status: str | None = None):
    return {"escalations": store.list_escalations(status)}


@app.post("/api/escalations/{esc_id}/resolve")
def resolve(esc_id: int):
    ok = store.resolve_escalation(esc_id)
    return {"resolved": ok, "id": esc_id}


@app.post("/api/evaluation/run")
def evaluation_run():
    from evaluation import run_evaluation
    result = run_evaluation(store_factory=lambda p: Store(p))
    store.set_kv("last_evaluation", result)
    return result


@app.get("/api/evaluation")
def evaluation_last():
    return store.get_kv("last_evaluation") or {
        "status": "not run yet — POST /api/evaluation/run"}


@app.post("/api/test/contention")
def contention(body: ContentionIn):
    """N simulated customers race to reserve the same variant.

    The atomic reserve (BEGIN IMMEDIATE + stock check) must guarantee that
    total reserved never exceeds the stock on hand.
    """
    sku = body.sku
    if not sku and body.product_id:
        rows = [r for r in store.catalog_search(limit=1000)["items"]
                if r["product_id"] == body.product_id
                and (not body.size or r["size"] == body.size)]
        sku = rows[0]["sku"] if rows else None
    if not sku:
        return JSONResponse({"error": "sku or product_id not found"}, 404)
    before = store.available(sku)

    def try_buy(i):
        return store.reserve(f"contention-{threading.get_ident()}-{i}",
                             [(sku, body.qty)], minutes=15)

    with ThreadPoolExecutor(max_workers=body.customers) as ex:
        results = list(ex.map(try_buy, range(body.customers)))
    won = sum(1 for r in results if r)
    return {"sku": sku, "customers": body.customers, "qty_each": body.qty,
            "available_before": before, "reservations_won": won,
            "reserved_units": won * body.qty,
            "available_after": store.available(sku),
            "oversold": won * body.qty > before}


@app.post("/api/reset")
def reset():
    engine.reset()
    return {"reset": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
