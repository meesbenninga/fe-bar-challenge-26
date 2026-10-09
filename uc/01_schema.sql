-- Unity Catalog schema for the FE Bar oil-desk spike.
-- Catalog already exists on FEVM: serverless_stable_ob2uyb_catalog
-- Do not CREATE CATALOG here (shared FEVM catalog).

CREATE SCHEMA IF NOT EXISTS serverless_stable_ob2uyb_catalog.fe_bar_spike
COMMENT 'FE Bar spike: synthetic North Sea physical-oil world state. CRO owns risk metrics; Head of Oil Trading owns P&L.';

-- FEVM tag policies lock keys like data_class / project. Ownership is in COMMENTs.

COMMENT ON TABLE serverless_stable_ob2uyb_catalog.fe_bar_spike.desk_risk IS
  'Book-level VaR 95 vs limit. Accountable executive: Chief Risk Officer. Source of desk_risk_mv.';

COMMENT ON TABLE serverless_stable_ob2uyb_catalog.fe_bar_spike.desk_pnl IS
  'Daily P&L by leg (flat_price, crack, freight). Accountable executive: Head of Oil Trading. Source of desk_pnl_mv.';

COMMENT ON TABLE serverless_stable_ob2uyb_catalog.fe_bar_spike.desk_positions IS
  'Synthetic open legs by sub-book. Row-filtered by book_entitlements.';

COMMENT ON TABLE serverless_stable_ob2uyb_catalog.fe_bar_spike.metocean_events IS
  'Synthetic North Sea metocean readings that drive M1 days-of-cover.';
