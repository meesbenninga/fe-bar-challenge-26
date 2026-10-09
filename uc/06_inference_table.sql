-- GenAI governance: every decision-card narrative is logged next to the numbers
-- it was allowed to see. Complements Lakebase decision_audit (Approve/Decline).

CREATE TABLE IF NOT EXISTS serverless_stable_ob2uyb_catalog.fe_bar_spike.decision_narrative (
  narrative_id STRING,
  run_ts TIMESTAMP,
  who STRING,
  hedge_bbl BIGINT,
  current_util DOUBLE,
  post_action_util DOUBLE,
  var_95_usd DOUBLE,
  endpoint STRING,
  narrative STRING
)
COMMENT 'LLM narration audit. Numbers are inputs; prose is the only model output.';
