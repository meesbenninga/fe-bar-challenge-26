# FE Bar — Trafigura World-State Model Chain

## Business Outcome

**Problem**: A North Sea metocean event triggers a cascade: wave disruption shortens supply cover, reprices cargo ETA, and blows the Crude VaR through the desk limit (2.11× utilisation). The desk needs a sub-5-second reprice chain, an explain-by-leg MTD P&L, and a hedge recommendation that brings utilisation back to 1.00×.

**KPIs delivered**:
* Reprice chain: p50=200ms, p95=249ms (4% of 5s budget)
* CRUDE limit utilisation: 2.11× → 1.00× after recommended 1.37M bbl hedge
* MTD P&L explained: flat_price $218K, crack $967K, freight $66K
* 5/5 Genie questions answered correctly against metric views

## Architecture

```
Metocean Event
    │
    ▼
fe-bar-chain App (XLARGE)
    ├─ M1: metocean → days_of_cover (sklearn, 1ms)
    ├─ M2: supply+price → VaR delta (sklearn, 1ms)
    └─ M3: book+M1+M2 → VaR, limit_util (sklearn, <1ms)
    │
    ├─ Lakebase (Postgres): hot-path writes (model_inputs, model_outputs,
    │   run_state, control_metrics, routing, decision_audit)
    │
    └─ UC (Delta): governed history (5-min sync job), metric views,
        UC functions (hedge_size, post_action_util, reroute_econ)
    │
    ▼
fe-bar-oil-desk App (LARGE)
    ├─ Live chain trigger + 5s budget bar
    ├─ Risk & P&L (desk_risk_mv, desk_pnl_mv via SQL warehouse)
    ├─ Ask the Desk (Genie Conversation API)
    └─ Decision card (LLM narrative, Approve/Decline → audit trail)
```

## Decisions and Trade-offs

1. **Warm Apps vs Lakeflow-per-model**: Apps keep models in-process memory (1ms inference). Model Serving would add 50-200ms per hop for cold start, serialization, and HTTP. At 3 hops, that's 150-600ms vs 3ms — Apps win on this latency budget.

2. **FEVM analogue vs Azure Event Hubs / Service Bus production path**: FEVM serverless has no Event Hubs or Kafka. The proven pattern is App-to-App HTTP with platform-injected OAuth JWT (gap-auth header confirms SP identity). In production (Azure), this becomes Event Hubs triggers with AAD MSI — same identity model, different transport.

3. **Lakebase serves, UC governs**: Hot path (sub-second) writes to Lakebase Postgres with idempotent PKs. Cold path (minutes of lag) copies to Delta via scheduled job for governance, lineage, metric views, and Genie grounding. Two stores, one truth.

4. **Why not Model Serving**: FEVM workspace has no custom Model Serving endpoints. Apps with in-process sklearn are the FEVM analogue. Model Serving would be correct in production but adds infra that doesn't exist here.

5. **PAT vs JWT forced App-to-App**: executeCode injects PATs (dkea...). Apps proxy requires OAuth JWT (ey...). Solution: a second App (fe-bar-producer) that auto-gets JWT from platform-injected env vars and proves the M2M HTTP pattern.

6. **Ray parallel mode**: Installed in fe-bar-chain for NS_GASOIL (M2+M3 parallel after M1). Falls back to sequential inside the App container. No functional impact; demonstrates the routing table pattern.

## Live (FEVM)

| Surface | URL |
| --- | --- |
| Oil desk (submit this) | https://fe-bar-oil-desk-7474658263595816.aws.databricksapps.com |
| Model chain | https://fe-bar-chain-7474658263595816.aws.databricksapps.com |
| Producer (App-to-App JWT) | https://fe-bar-producer-7474658263595816.aws.databricksapps.com |
| Workspace | https://fevm-serverless-stable-ob2uyb.cloud.databricks.com/?o=7474658263595816 |
| Genie space | FE Bar — Oil Desk World State (`01f1c3da7f691ea7b087b1c6695bfdd3`) |

All data is synthetic. This is an illustrative Trafigura physical-oil desk, not Trafigura's real book.

## Repo map

- [`docs/EVIDENCE_FULL.md`](docs/EVIDENCE_FULL.md) — text execution evidence (required for the evaluator)
- [`docs/DECK.md`](docs/DECK.md) — business-buyer slides (export to PDF for the form)
- [`docs/AI_USAGE.md`](docs/AI_USAGE.md) — how Cursor + Genie Code were used
- [`apps/`](apps/) — Databricks Apps (`fe-bar-chain`, `fe-bar-producer`, `fe-bar-oil-desk`)
- [`pipelines/`](pipelines/) — Lakeflow SDP SQL
- [`jobs/`](jobs/) — Lakebase→Delta history + producer notebooks

## Submit checklist

1. Grant the oil-desk app SP `a3bbd7fc-6104-4ccc-b1b3-7a0def4e1710` **CAN_RUN** on Genie space `01f1c3da7f691ea7b087b1c6695bfdd3` (Genie UI; agent guardrails blocked this).
2. Attach [`docs/DECK.md`](docs/DECK.md) (or a PDF export) on the submission form.
3. Repo must stay **public** so the evaluator can read it.
4. Optional: paste this Cursor conversation ID on the form.
