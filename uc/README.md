# Unity Catalog — `serverless_stable_ob2uyb_catalog.fe_bar_spike`

This folder is the **governed layer** of the build. Lakeflow lands bronze/silver/gold in
[`pipelines/ingest_bronze_silver.sql`](../pipelines/ingest_bronze_silver.sql). These files
define what the oil desk, Genie, and the hedge recommendation are allowed to trust.

Apply in order against warehouse `0e54af629ab8456e`.

| File | What it creates |
| --- | --- |
| `01_schema.sql` | Schema comments, table comments, tags |
| `02_views.sql` | `desk_risk_mv`, `desk_pnl_mv`, `chain_latency_mv`, `world_state_mv` |
| `03_functions.sql` | Deterministic `hedge_size`, `post_action_util`, `reroute_econ` |
| `04_grants.sql` | USE/SELECT/EXECUTE for the three App service principals |
| `05_row_column_security.sql` | Book entitlements, row filter, column mask |
| `06_inference_table.sql` | GenAI narrative audit table (`decision_narrative`) |

**Owners of the numbers**

* **Chief Risk Officer** — owns the VaR limit and utilisation (`desk_risk`, `desk_risk_mv`).
* **Head of Oil Trading** — owns MTD P&L by leg (`desk_pnl`, `desk_pnl_mv`).
* The LLM never writes these tables. It only narrates values already computed here.
