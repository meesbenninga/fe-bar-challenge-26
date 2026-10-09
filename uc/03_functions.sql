-- Deterministic decision functions. The LLM may only quote these outputs.

CREATE OR REPLACE FUNCTION serverless_stable_ob2uyb_catalog.fe_bar_spike.hedge_size(p_sub_book STRING)
RETURNS BIGINT
COMMENT 'Barrels to sell so VaR utilisation returns to ~1.00. Owned by CRO limit policy, not the LLM.'
RETURN (
  SELECT CAST(GREATEST(0, exposure_bbl - (exposure_bbl * (limit_usd / var_95_usd))) AS BIGINT)
  FROM serverless_stable_ob2uyb_catalog.fe_bar_spike.desk_risk
  WHERE sub_book = p_sub_book
  LIMIT 1
);

CREATE OR REPLACE FUNCTION serverless_stable_ob2uyb_catalog.fe_bar_spike.post_action_util(
  p_sub_book STRING,
  p_hedge_bbl BIGINT
)
RETURNS DOUBLE
COMMENT 'Projected limit utilisation after selling p_hedge_bbl. CRO metric.'
RETURN (
  SELECT ROUND((var_95_usd * ((exposure_bbl - p_hedge_bbl) * 1.0 / exposure_bbl)) / limit_usd, 4)
  FROM serverless_stable_ob2uyb_catalog.fe_bar_spike.desk_risk
  WHERE sub_book = p_sub_book
  LIMIT 1
);

CREATE OR REPLACE FUNCTION serverless_stable_ob2uyb_catalog.fe_bar_spike.reroute_econ(
  p_cargo_id STRING,
  p_alt_port STRING
)
RETURNS TABLE (
  cargo_id STRING,
  alt_port STRING,
  orig_port STRING,
  delta_eta_days DOUBLE,
  delta_cost_usd DOUBLE,
  recommendation STRING
)
COMMENT 'Deterministic cargo reroute economics vs current destination.'
RETURN
  SELECT
    cargo_id,
    p_alt_port AS alt_port,
    destination AS orig_port,
    ROUND(
      CASE
        WHEN p_alt_port = 'Rotterdam' THEN eta_days * 0.85
        WHEN p_alt_port = 'Mongstad' THEN eta_days * 1.10
        ELSE eta_days
      END - eta_days, 2
    ) AS delta_eta_days,
    ROUND(
      CASE
        WHEN p_alt_port = 'Rotterdam' THEN cargo_bbl * -0.12
        WHEN p_alt_port = 'Mongstad' THEN cargo_bbl * 0.08
        ELSE 0
      END, 2
    ) AS delta_cost_usd,
    CASE
      WHEN p_alt_port = destination THEN 'NO_CHANGE'
      WHEN p_alt_port = 'Rotterdam' THEN 'FAVORABLE'
      ELSE 'UNFAVORABLE'
    END AS recommendation
  FROM serverless_stable_ob2uyb_catalog.fe_bar_spike.ais_cargo
  WHERE cargo_id = p_cargo_id
  QUALIFY ROW_NUMBER() OVER (PARTITION BY cargo_id ORDER BY event_ts DESC) = 1;
