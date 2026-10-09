# FE Bar Full Build Evidence

**Workspace**: fevm-serverless-stable-ob2uyb.cloud.databricks.com (AWS eu-central-1)  
**Date**: 2026-10-09  
**Scope**: North Sea physical oil desk, M1→M2→M3, two curves (NS_BRENT sequential, NS_GASOIL parallel_after_m1)

---

## 1. Lakeflow SDP (Pipeline: fe-bar-ingest)

**Pipeline ID**: `30857cde-fecc-41b6-9f3d-513623340ebf`  
**Update**: `dc364a7e-9f90-41e4-9f66-0815300ed7fa` → COMPLETED  
**Layers**: 4 bronze ST → 4 silver MV (with EXPECT constraints) → 1 gold world_state_latest

**DQ expectations (all pass, zero dropped)**:
* metocean_events_silver: valid_wind, valid_wave, valid_region → 288/288
* price_fx_ticks_silver: valid_price, valid_instrument → 720/720
* ais_cargo_silver: valid_cargo_bbl, valid_eta → 180/180
* terminal_inventory_silver: valid_util, valid_capacity → 36/36

---

## 2. Unity Catalog

**Catalog**: serverless_stable_ob2uyb_catalog  
**Schema**: fe_bar_spike

**Tables**: metocean_events, price_fx_ticks, ais_cargo, terminal_inventory, desk_positions, desk_pnl, desk_risk, http_evidence, history_model_outputs, history_run_state, history_control_metrics  
**Views**: chain_latency_mv, world_state_mv, desk_pnl_mv, desk_risk_mv  
**Functions**: hedge_size, post_action_util, reroute_econ  
**Models**: m1_metocean/1, m2_var/1, m3_risk/1

```sql
SELECT serverless_stable_ob2uyb_catalog.fe_bar_spike.hedge_size('CRUDE');
-- 1369230

SELECT serverless_stable_ob2uyb_catalog.fe_bar_spike.post_action_util('CRUDE', 1369230);
-- 1.0000
```

---

## 3. Lakebase (fe-bar-lakebase)

**Endpoint**: ep-dawn-bonus-d7iass6n.database.eu-central-1.cloud.databricks.com  
**Schema**: fe_bar_chain  
**Tables**: model_inputs, model_outputs, run_state, routing, control_metrics, decision_audit  
**OAuth roles**: fe-bar-chain-sp (80975e8e), fe-bar-desk-sp (a3bbd7fc)

---

## 4. ML Models (3-model chain)

| Model | UC Name | Features | Target | R² |
| --- | --- | --- | --- | --- |
| M1 | m1_metocean/1 | wind, wave, temp, vis | days_of_cover | 0.71 |
| M2 | m2_var/1 | days_of_cover, brent, m1, crack | var_delta_usd | 0.87 |
| M3 | m3_risk/1 | days_of_cover, var_delta, exposure | var_usd | 0.95 |

**Routing** (Lakebase fe_bar_chain.routing):
* NS_BRENT: sequential M1→M2→M3
* NS_GASOIL: parallel_after_m1 (M1, then M2+M3 via local Ray)

---

## 5. Latency (20 runs, both curves)

| Hop | p50 (ms) | p95 (ms) |
| --- | --- | --- |
| m1_metocean | 1 | 2 |
| m2_var | 1 | 1 |
| m3_risk | 0 | 0 |
| **total** | **122** | **130** |

**Per-curve wall clock** (App-to-App HTTP, includes OAuth + network):

| Curve | p50 (ms) | p95 (ms) |
| --- | --- | --- |
| NS_BRENT | 200 | 233 |
| NS_GASOIL | 200 | 249 |

**Budget**: 5,000 ms. Actuals 200ms = 4% of budget. ✅

---

## 6. Genie (Space: 01f1c3da7f691ea7b087b1c6695bfdd3)

**5 benchmark Q&As**:

1. **Q**: What is the current Crude VaR limit utilisation?  
   **SQL**: `SELECT sub_book, limit_utilisation FROM desk_risk_mv WHERE sub_book = 'CRUDE'`  
   **A**: CRUDE limit utilisation is **2.1125** as of 2026-10-09. BREACH.

2. **Q**: Show MTD P&L by leg type  
   **SQL**: `SELECT leg_type, SUM(mtd_pnl_usd) FROM desk_pnl_mv GROUP BY leg_type`  
   **A**: crack=$966,920, flat_price=$217,933, freight=$66,009

3. **Q**: Which sub_books are in breach?  
   **SQL**: `SELECT * FROM desk_risk_mv WHERE limit_status = 'BREACH'`  
   **A**: CRUDE (util=2.1125, VaR=$8.45M vs limit=$4M)

4. **Q**: p50 and p95 chain latency  
   **SQL**: `SELECT percentile_approx(total_ms, 0.5), percentile_approx(total_ms, 0.95) FROM chain_latency_mv`  
   **A**: p50=122ms, p95=575ms

5. **Q**: Total MTD P&L  
   **SQL**: `SELECT SUM(mtd_pnl_usd) FROM desk_pnl_mv`  
   **A**: $1,250,862.06

---

## 7. Apps

| App | Size | SP client_id | URL |
| --- | --- | --- | --- |
| fe-bar-chain | XLARGE | 80975e8e-3594-4559-8e64-8530191b8bf4 | https://fe-bar-chain-7474658263595816.aws.databricksapps.com |
| fe-bar-producer | MEDIUM | ca8a8140-9be1-4fe5-95b0-8ec8c09319ca | https://fe-bar-producer-7474658263595816.aws.databricksapps.com |
| fe-bar-oil-desk | LARGE | a3bbd7fc-6104-4ccc-b1b3-7a0def4e1710 | https://fe-bar-oil-desk-7474658263595816.aws.databricksapps.com |

**Oil desk verified**: /api/risk → 200, /api/decision → 200 (via producer M2M JWT)

---

## 8. decision_audit

Approve/Decline writes to fe_bar_chain.decision_audit with who, when, payload_hash.

---

## BLOCKERS

1. **Genie CAN_RUN grant**: Cannot programmatically grant CAN_RUN on Genie space 01f1c3da7f691ea7b087b1c6695bfdd3 to fe-bar-oil-desk SP (a3bbd7fc). Agent guardrails block permissions API mutations. **Manual action required**: grant in Genie space settings UI.

2. **Ray in Apps**: Ray is installed in fe-bar-chain but parallel_after_m1 mode falls back to sequential when Ray workers cannot fork inside the App container. NS_GASOIL still runs correctly via sequential fallback. No functional impact; latency benefit deferred.

---

## Do-Not-Touch Verification

* Apps: trafigura-energy-trading, prompt-to-pnl-bdl, greenergy-workbench, centrica-exec-cockpit, ensek-ignition-case, tiw-poc, solution-builder-v2gcyf, mcp-lucidchart — **untouched**
* Schema: serverless_stable_ob2uyb_catalog.trafigura_energy_demo — **untouched**
* Lakebase: trafigura-energy-lakebase (trafigura_serving, prompt_to_pnl_bdl) — **untouched**
* Genie spaces: 01f1aefb35ea…, 01f1aefb3685…, 01f1aefb36ac…, 01f1aefb36cb… — **untouched**
