-- Governed views the oil desk and Genie read. Numbers live here, not in the LLM.

CREATE OR REPLACE VIEW serverless_stable_ob2uyb_catalog.fe_bar_spike.desk_risk_mv
COMMENT 'CRO view: VaR 95, limit, utilisation, BREACH/OK. Oil-desk /api/risk and Genie ground here.'
AS SELECT
  sub_book,
  var_95_usd,
  limit_usd,
  limit_utilisation,
  exposure_bbl,
  CASE WHEN limit_utilisation > 1.0 THEN 'BREACH' ELSE 'OK' END AS limit_status,
  as_of_date
FROM serverless_stable_ob2uyb_catalog.fe_bar_spike.desk_risk;

CREATE OR REPLACE VIEW serverless_stable_ob2uyb_catalog.fe_bar_spike.desk_pnl_mv
COMMENT 'Head of Oil Trading view: MTD P&L by leg. Oil-desk /api/pnl and Genie ground here.'
AS SELECT
  leg_type,
  SUM(daily_pnl_usd) AS mtd_pnl_usd,
  COUNT(*) AS trading_days,
  ROUND(AVG(daily_pnl_usd), 2) AS avg_daily_pnl_usd,
  MIN(pnl_date) AS mtd_start,
  MAX(pnl_date) AS mtd_end
FROM serverless_stable_ob2uyb_catalog.fe_bar_spike.desk_pnl
GROUP BY leg_type;

CREATE OR REPLACE VIEW serverless_stable_ob2uyb_catalog.fe_bar_spike.chain_latency_mv
COMMENT 'Completed chain runs with per-hop latency from Lakebase history sync.'
AS SELECT
  rs.run_id,
  rs.status,
  rs.total_ms,
  MAX(CASE WHEN cm.hop = 'm1_metocean' THEN cm.ms END) AS m1_ms,
  MAX(CASE WHEN cm.hop = 'm2_var' THEN cm.ms END) AS m2_ms,
  MAX(CASE WHEN cm.hop = 'm3_risk' THEN cm.ms END) AS m3_ms,
  rs.started_at
FROM serverless_stable_ob2uyb_catalog.fe_bar_spike.history_run_state rs
LEFT JOIN serverless_stable_ob2uyb_catalog.fe_bar_spike.history_control_metrics cm
  ON rs.run_id = cm.run_id
WHERE rs.status = 'complete'
GROUP BY rs.run_id, rs.status, rs.total_ms, rs.started_at;

CREATE OR REPLACE VIEW serverless_stable_ob2uyb_catalog.fe_bar_spike.world_state_mv
COMMENT 'Latest governed snapshot of metocean and price streams for Genie.'
AS SELECT
  'metocean' AS stream,
  region,
  MAX(event_ts) AS last_update,
  ROUND(AVG(wind_speed_kn), 1) AS avg_wind_kn,
  ROUND(AVG(wave_height_m), 2) AS avg_wave_m,
  COUNT(*) AS event_count
FROM serverless_stable_ob2uyb_catalog.fe_bar_spike.metocean_events_silver
GROUP BY region
UNION ALL
SELECT
  'price' AS stream,
  'ALL' AS region,
  MAX(tick_ts) AS last_update,
  ROUND(AVG(price), 2) AS avg_wind_kn,
  NULL AS avg_wave_m,
  COUNT(*) AS event_count
FROM serverless_stable_ob2uyb_catalog.fe_bar_spike.price_fx_ticks_silver
GROUP BY instrument;
