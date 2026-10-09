# FE Bar — Oil Desk World-State Model Chain
## Business Buyer Deck

**Accountable executives**
- **Chief Risk Officer** — owns the VaR limit, utilisation, and breach. Measured on staying inside the risk mandate.
- **Head of Oil Trading** — owns MTD P&L by leg and the decision to hedge. Measured on P&L without sitting blind on a blown limit.

All figures below are synthetic and illustrative.

---

### Slide 1: The Problem (desk)

A North Sea storm disrupts cargo flow. Within hours, days-of-cover drops, VaR spikes through the CRUDE limit (2.11×), and the desk is blind to which P&L leg is moving. Today this takes 45 minutes of spreadsheet work. The desk needs it in under 5 seconds.

---

### Slide 2: The Outcome (desk)

| KPI | Before | After |
| --- | --- | --- |
| Reprice latency | 45 min | **200 ms** (p50) |
| CRUDE limit utilisation | 2.11× (breach) | **1.00×** (compliant) |
| P&L explain | manual, next day | **real-time**, by leg |
| Hedge recommendation | trader judgment | **computed**, audited |

---

### Slide 3: The Investment Case (CRO / CFO)

This is the slide for the person who funds it, not the person who clicks Reprice.

**Who owns the number.** The CRO owns the $4.0M Crude VaR limit. Today that limit is already $4.45M over ($8.45M VaR). The Head of Oil Trading owns ~$1.25M MTD P&L. Neither can act while the book is being rebuilt by hand.

**What a breach costs.** Capital is tied to the limit. Sitting 2.11× utilised is not a latency inconvenience — it is unauthorised risk on the book, with the move already in the market. One 45-minute blind window per weather event is the operating loss. The programme return is fewer of those windows, on every stream you later plug in (weather, prices, AIS), not a cheaper sklearn model.

**What you are buying.** A reusable chain: event in → models in order → live recommendation → human approve → ETRM still books. Recommend-only. Audit on every Approve. Governed metrics the CRO can defend.

**What you are not buying.** A new ETRM. Auto-trading. An LLM that invents VaR.

---

### Slide 4: The Chain (< 5 seconds)

Metocean → M1 (days-of-cover, 1ms) → M2 (VaR delta, 1ms) → M3 (book VaR + limit util, <1ms).
Total model inference: 3ms. Total including Lakebase writes and HTTP: 200ms. Budget: 5,000ms. **4% utilised.**

---

### Slide 5: P&L Attribution by Leg (Head of Oil Trading)

MTD P&L decomposed:
* Flat price: $218K — the metocean event moved physical.
* Crack spread: $967K — refining margin still positive.
* Freight: $66K — cargo reroute economics factored.

No LLM computes numbers. All figures from SQL views the Head of Oil Trading owns.

---

### Slide 6: Risk and Limits (Chief Risk Officer)

| Sub-book | VaR 95 | Limit | Utilisation | Status |
| --- | --- | --- | --- | --- |
| CRUDE | $8.45M | $4.0M | **2.11×** | BREACH |
| PRODUCTS | $1.8M | $2.5M | 0.72× | OK |
| FREIGHT | $0.95M | $1.5M | 0.63× | OK |

Recommended hedge: sell 1,369,230 bbl → CRUDE util drops to **1.00×**. Sized by `hedge_size()`, not by the model narrative.

---

### Slide 7: The Desk Surface

One HTML page, four sections:
1. **Live chain**: trigger button, per-hop latency, 5s budget bar.
2. **Risk & P&L**: tables from metric views, CRUDE breach highlighted red.
3. **Ask the desk**: natural-language queries via Genie, grounded in governed views.
4. **Decision card**: LLM narrative (uses only computed numbers), Approve/Decline writes to audit trail.

Banner: "Recommends only — ETRM executes."

---

### Slide 8: Governance (CRO)

* **All data synthetic** — no production data in the spike.
* **Named owners in the catalog** — table comments name the CRO (risk) and Head of Oil Trading (P&L).
* **No secrets in source** — App SP credentials injected by the platform.
* **Audit trail** — Approve/Decline in Lakebase; LLM prose in `decision_narrative`.
* **History** — Lakebase hot-path synced to Delta for lineage.
* **UC functions** — `hedge_size`, `post_action_util`, `reroute_econ` are deterministic SQL.
* **Row/column security** — `desk_positions` filtered by book entitlements; `entry_price` masked.

Implementation: [`uc/`](../uc/).

---

### Slide 9: Production Path

| Spike (FEVM) | Production (Azure) |
| --- | --- |
| App-to-App HTTP | Event Hubs + Function Apps |
| In-process sklearn | Model Serving endpoints |
| Lakebase Postgres | Lakebase Postgres (same) |
| Scheduled Delta sync | Lakeflow continuous |
| Genie for desk queries | Genie for desk queries (same) |

Investment: the model chain, Lakebase schema, UC governance, and Genie space carry forward. Only the transport layer changes.
