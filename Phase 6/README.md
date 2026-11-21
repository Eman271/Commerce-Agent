# F26-07 — AI Sales & Customer Support Agent

**Saira Fashion House** (fictional store, Gujranwala) sells through chat.
Customers write in Roman Urdu / English mix — *"bhai blk linen kurta mdm mein
hai kya?"* — and this agent turns that into real actions: check stock, place
an order, track an order, start an exchange, answer policy questions, or hand
the chat to a human when the rules say it must.

Team F26-07. This is the Phase 5/6 build: the Phase 4 notebook agent (v3),
rebuilt as a small web service.

## Run it

```bash
pip install -r requirements.txt
python app.py
# open http://127.0.0.1:8000
```

### Deploy

- **Render / Railway / Heroku-style hosts:** set the root directory to
  `Phase 6`, build command `pip install -r requirements.txt`; the `Procfile`
  starts `uvicorn app:app --host 0.0.0.0 --port $PORT`.
- **Docker:** `docker build -t f26-07-agent . && docker run -p 8000:8000 f26-07-agent`.
- Env vars (all optional): `PORT` (default 8000), `HOST` (default 127.0.0.1,
  only for `python app.py`), `DB_PATH` (default `shop.db` next to `app.py`).
  The database is re-seeded from `data/` if missing, so an ephemeral disk is fine.

No other setup. The first run creates `shop.db` (SQLite) and loads
`data/catalog.csv` (572 variants, 50 products) and `data/orders.csv`
(51 orders) into it. `POST /api/reset` wipes runtime state and re-seeds.

## Try it

- `POST /api/chat` — `{"session_id": "s1", "message": "Salam, black linen kurta M mein available hai?"}`.
  Every reply includes a `trace` (intent, action, entities, confidence,
  decision ACT/ASK/BLOCK/HANDOFF, reason, tools used) so you can see *why*
  the agent did what it did.
- Order flow: ask for a product → give quantity → give name / phone /
  address / city → read the summary (stock is reserved for 15 minutes) →
  reply `haan` to confirm. The order is only created after confirmation.
- `GET /api/catalog?q=kurta&in_stock=true`, `GET /api/orders`,
  `GET /api/dashboard` (conversations, orders, revenue, escalations,
  handled %, intent counts, top products, low / out-of-stock alerts),
  `GET /api/escalations`, `POST /api/escalations/{id}/resolve`.
- `POST /api/test/contention` — simulated customers racing to reserve the
  same variant; reservations are atomic, so the last unit is never oversold.

## How it works

```
message → NLU (agent/nlu.py)          synonyms + fuzzy product matching,
                                       entities: product/color/size/qty/
                                       city/phone/order id/budget
        → guardrails (agent/guardrails.py)
                                       rules from data/policy_rules.json:
                                       refund, damaged, discount, angry,
                                       legal, human request, cancel/change,
                                       online payment, qty > 10, COD > Rs 25,000
        → tools / RAG                  check_stock, recommend, delivery
          (agent/tools.py,             charge, order status (order id +
           agent/policy_rag.py)        phone must match), exchange checks;
                                       policy answers retrieved from
                                       policy.md with a TF-IDF gate —
                                       below the gate the agent escalates
                                       instead of inventing an answer
        → dialogue manager (agent/engine.py)
                                       multi-turn order / exchange / status
                                       flows, replies in the customer's
                                       language mix, trace on every reply
```

Everything at runtime is Python stdlib (sqlite3, csv, json, re) except
FastAPI/uvicorn for HTTP. Prices, stock and policy facts only ever come from
the data files — the agent never makes them up.

## Training and evaluation (optional model)

Phase 4's main finding was that rules + guardrails beat the ML classifier on
their own, so the trained model is only a fallback signal:

```bash
pip install scikit-learn     # optional extra
python train_model.py        # -> models/intent_model.pkl + models/metrics.json
python evaluation.py         # replays all 172 labelled conversations
python tests/test_agent.py   # plain-python checks, no pytest needed
```

Evaluation resets the database before every conversation (as the dataset
note requires) and reports action accuracy and escalation
precision/recall/F1, overall and per dev/test split. Results are also
available live at `POST /api/evaluation/run` and `GET /api/evaluation`.

## Layout

```
app.py            FastAPI entry point and routes
agent/            data_store.py (SQLite) · nlu.py · policy_rag.py ·
                  guardrails.py · tools.py · engine.py
data/             catalog.csv · orders.csv · conversations.json ·
                  policy.md · policy_rules.json
train_model.py    optional sklearn intent model
evaluation.py     conversations.json replay harness
tests/            test_agent.py
```
