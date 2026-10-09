-- FE Bar Ingest Pipeline: governed evidence path for 4 synthetic world streams.
-- Lakeflow SDP evidence path — NOT the <5s hot path (POST /trigger → fe-bar-chain → Lakebase).

-- ════════════════════════════════════════════════════════════════════════════
-- BRONZE LAYER: streaming tables (append-only, raw landing)
-- ════════════════════════════════════════════════════════════════════════════

CREATE OR REFRESH STREAMING TABLE metocean_events_bronze
COMMENT 'Raw North Sea metocean events — synthetic generator output'
AS SELECT *, current_timestamp() AS _ingested_at
FROM STREAM serverless_stable_ob2uyb_catalog.fe_bar_spike.metocean_events;

CREATE OR REFRESH STREAMING TABLE price_fx_ticks_bronze
COMMENT 'Raw price and FX ticks — Brent, gasoil, crack, EURUSD'
AS SELECT *, current_timestamp() AS _ingested_at
FROM STREAM serverless_stable_ob2uyb_catalog.fe_bar_spike.price_fx_ticks;

CREATE OR REFRESH STREAMING TABLE ais_cargo_bronze
COMMENT 'Raw AIS cargo tracking events — vessel positions, ETA, reroute flags'
AS SELECT *, current_timestamp() AS _ingested_at
FROM STREAM serverless_stable_ob2uyb_catalog.fe_bar_spike.ais_cargo;

CREATE OR REFRESH STREAMING TABLE terminal_inventory_bronze
COMMENT 'Raw terminal inventory snapshots — storage levels and throughput'
AS SELECT *, current_timestamp() AS _ingested_at
FROM STREAM serverless_stable_ob2uyb_catalog.fe_bar_spike.terminal_inventory;

-- ════════════════════════════════════════════════════════════════════════════
-- SILVER LAYER: materialized views with EXPECT constraints
-- ════════════════════════════════════════════════════════════════════════════

CREATE OR REFRESH MATERIALIZED VIEW metocean_events_silver (
  CONSTRAINT valid_wind EXPECT (wind_speed_kn BETWEEN 0 AND 120) ON VIOLATION DROP ROW,
  CONSTRAINT valid_wave EXPECT (wave_height_m BETWEEN 0 AND 25) ON VIOLATION DROP ROW,
  CONSTRAINT valid_region EXPECT (region IS NOT NULL) ON VIOLATION DROP ROW
)
COMMENT 'Enriched metocean events with severity score and classification'
AS SELECT
  event_id, curve_id, region, event_ts, wind_speed_kn, wave_height_m,
  sea_temp_c, visibility_nm,
  ROUND(0.4 * wind_speed_kn / 40.0 + 0.35 * wave_height_m / 8.0
        + 0.15 * (1.0 - visibility_nm / 20.0) + 0.1 * (1.0 - sea_temp_c / 18.0), 4)
    AS severity_score,
  CASE
    WHEN wind_speed_kn >= 30 OR wave_height_m >= 5 THEN 'SEVERE'
    WHEN wind_speed_kn >= 20 OR wave_height_m >= 3 THEN 'MODERATE'
    ELSE 'NORMAL'
  END AS severity_class,
  _ingested_at
FROM metocean_events_bronze;

CREATE OR REFRESH MATERIALIZED VIEW price_fx_ticks_silver (
  CONSTRAINT valid_price EXPECT (price > 0) ON VIOLATION DROP ROW,
  CONSTRAINT valid_instrument EXPECT (instrument IS NOT NULL) ON VIOLATION DROP ROW
)
COMMENT 'Validated price/FX ticks with spread calculations'
AS SELECT
  tick_id, instrument, tick_ts, price, ccy,
  _ingested_at
FROM price_fx_ticks_bronze;

CREATE OR REFRESH MATERIALIZED VIEW ais_cargo_silver (
  CONSTRAINT valid_cargo_bbl EXPECT (cargo_bbl > 0) ON VIOLATION DROP ROW,
  CONSTRAINT valid_eta EXPECT (eta_days >= 0) ON VIOLATION DROP ROW
)
COMMENT 'Validated AIS cargo events with reroute flags'
AS SELECT
  event_id, vessel, grade, cargo_bbl, origin, destination,
  lat, lon, status, eta_days, reroute_flagged, cargo_id, event_ts,
  _ingested_at
FROM ais_cargo_bronze;

CREATE OR REFRESH MATERIALIZED VIEW terminal_inventory_silver (
  CONSTRAINT valid_util EXPECT (utilisation BETWEEN 0 AND 1) ON VIOLATION DROP ROW,
  CONSTRAINT valid_capacity EXPECT (capacity_bbl > 0) ON VIOLATION DROP ROW
)
COMMENT 'Validated terminal inventory with utilisation checks'
AS SELECT
  event_id, terminal, capacity_bbl, current_bbl, utilisation,
  daily_throughput_bbl, event_ts,
  _ingested_at
FROM terminal_inventory_bronze;

-- ════════════════════════════════════════════════════════════════════════════
-- GOLD LAYER: world_state_latest — one row per (region, stream)
-- ════════════════════════════════════════════════════════════════════════════

CREATE OR REFRESH MATERIALIZED VIEW world_state_latest
COMMENT 'Latest world-state snapshot: one row per region × stream for the oil desk'
AS
SELECT region, 'metocean' AS stream, event_ts AS last_ts,
  NAMED_STRUCT('wind_kn', wind_speed_kn, 'wave_m', wave_height_m,
               'severity', severity_class) AS payload
FROM metocean_events_silver
QUALIFY ROW_NUMBER() OVER (PARTITION BY region ORDER BY event_ts DESC) = 1

UNION ALL

SELECT 'ALL' AS region, 'price' AS stream, tick_ts AS last_ts,
  NAMED_STRUCT('wind_kn', CAST(NULL AS DOUBLE), 'wave_m', CAST(NULL AS DOUBLE),
               'severity', instrument) AS payload
FROM price_fx_ticks_silver
QUALIFY ROW_NUMBER() OVER (PARTITION BY instrument ORDER BY tick_ts DESC) = 1

UNION ALL

SELECT 'ALL' AS region, 'cargo' AS stream, event_ts AS last_ts,
  NAMED_STRUCT('wind_kn', CAST(NULL AS DOUBLE), 'wave_m', CAST(NULL AS DOUBLE),
               'severity', status) AS payload
FROM ais_cargo_silver
QUALIFY ROW_NUMBER() OVER (PARTITION BY cargo_id ORDER BY event_ts DESC) = 1

UNION ALL

SELECT 'ALL' AS region, 'terminal' AS stream, event_ts AS last_ts,
  NAMED_STRUCT('wind_kn', CAST(NULL AS DOUBLE), 'wave_m', utilisation,
               'severity', terminal) AS payload
FROM terminal_inventory_silver
QUALIFY ROW_NUMBER() OVER (PARTITION BY terminal ORDER BY event_ts DESC) = 1;
