# FE Bar — Oil Desk World-State Model Chain
## Business Buyer Deck (8 slides)

---

### Slide 1: The Problem

A North Sea storm disrupts cargo flow. Within hours, days-of-cover drops, VaR spikes through the CRUDE limit (2.11×), and the desk is blind to which P&L leg is moving. Today this takes 45 minutes of spreadsheet work. The desk needs it in under 5 seconds.

---

### Slide 2: The Outcome

| KPI | Before | After |
| --- | --- | --- |
| Reprice latency | 45 min | **200 ms** (p50) |
| CRUDE limit utilisation | 2.11× (breach) | **1.00×** (compliant) |
| P&L explain | manual, next day | **real-time**, by leg |
| Hedge recommendation | trader judgment | **computed**, audited |

---

### Slide 3: The Chain (< 5 seconds)

Metocean → M1 (days-of-cover, 1ms) → M2 (VaR delta, 1ms) → M3 (book VaR + limit util, <1ms).  
Total model inference: 3ms. Total including Lakebase writes and HTTP: 200ms. Budget: 5,000ms. **4% utilised.**

---

### Slide 4: P&L Attribution by Leg

MTD P&L decomposed:
* Flat price: $218K — the metocean event moved physical.
* Crack spread: $967K — refining margin still positive.
* Freight: $66K — cargo reroute economics factored.

No LLM computes numbers. All figures from SQL metric views.

---

### Slide 5: Risk and Limits

| Sub-book | VaR 95 | Limit | Utilisation | Status |
| --- | --- | --- | --- | --- |
| CRUDE | $8.45M | $4.0M | **2.11×** | BREACH |
| PRODUCTS | $1.8M | $2.5M | 0.72× | OK |
| FREIGHT | $0.95M | $1.5M | 0.63× | OK |

Recommended hedge: sell 1,369,230 bbl → CRUDE util drops to **1.00×**.

---

### Slide 6: The Desk Surface

One HTML page, four sections:
1. **Live chain**: trigger button, per-hop latency, 5s budget bar.
2. **Risk & P&L**: tables from metric views, CRUDE breach highlighted red.
3. **Ask the desk**: natural-language queries via Genie, grounded in governed metric views.
4. **Decision card**: LLM narrative (uses only computed numbers), Approve/Decline writes to audit trail.

Banner: "Recommends only — ETRM executes."

---

### Slide 7: Governance

* **All data synthetic** — no production data in the spike.
* **No secrets in source** — App SP credentials injected by the platform.
* **Audit trail** — every decision (Approve/Decline) written to Lakebase with who, when, payload hash.
* **History** — Lakebase hot-path data synced to Delta every 5 minutes for lineage and compliance.
* **UC functions** — hedge_size and post_action_util are deterministic SQL, not LLM-generated.

---

### Slide 8: Production Path

| Spike (FEVM) | Production (Azure) |
| --- | --- |
| App-to-App HTTP | Event Hubs + Function Apps |
| In-process sklearn | Model Serving endpoints |
| Lakebase Postgres | Lakebase Postgres (same) |
| Scheduled Delta sync | Lakeflow continuous |
| Genie for desk queries | Genie for desk queries (same) |

Investment: the model chain, Lakebase schema, UC governance, and Genie space carry forward unchanged. Only the transport layer changes.
