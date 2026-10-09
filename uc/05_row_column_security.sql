-- Fine-grained access: a physical-oil trader should not see every book's marks.
-- Entitlements table + row filter on desk_positions + column mask on entry_price.
-- desk_risk / desk_pnl stay unfiltered so the CRO and Head of Oil Trading views
-- (desk_risk_mv, desk_pnl_mv) keep working for the oil-desk app SP.

CREATE TABLE IF NOT EXISTS serverless_stable_ob2uyb_catalog.fe_bar_spike.book_entitlements (
  principal STRING COMMENT 'Email or App SP application id',
  sub_book  STRING COMMENT 'CRUDE | PRODUCTS | FREIGHT | * for all books'
)
COMMENT 'Maps principals to sub-books they may see on desk_positions.';

DELETE FROM serverless_stable_ob2uyb_catalog.fe_bar_spike.book_entitlements;

INSERT INTO serverless_stable_ob2uyb_catalog.fe_bar_spike.book_entitlements (principal, sub_book) VALUES
  ('mees.benninga@databricks.com', '*'),
  ('a3bbd7fc-6104-4ccc-b1b3-7a0def4e1710', '*'),
  ('80975e8e-3594-4559-8e64-8530191b8bf4', '*'),
  ('ca8a8140-9be1-4fe5-95b0-8ec8c09319ca', '*');

CREATE OR REPLACE FUNCTION serverless_stable_ob2uyb_catalog.fe_bar_spike.visible_sub_book(p_sub_book STRING)
RETURNS BOOLEAN
COMMENT 'TRUE if current_user() is entitled to this sub-book (or *).'
RETURN EXISTS (
  SELECT 1
  FROM serverless_stable_ob2uyb_catalog.fe_bar_spike.book_entitlements e
  WHERE (e.principal = current_user() OR e.principal = session_user())
    AND (e.sub_book = p_sub_book OR e.sub_book = '*')
);

ALTER TABLE serverless_stable_ob2uyb_catalog.fe_bar_spike.desk_positions
  DROP ROW FILTER;

ALTER TABLE serverless_stable_ob2uyb_catalog.fe_bar_spike.desk_positions
  SET ROW FILTER serverless_stable_ob2uyb_catalog.fe_bar_spike.visible_sub_book ON (sub_book);

CREATE OR REPLACE FUNCTION serverless_stable_ob2uyb_catalog.fe_bar_spike.mask_entry_price(p_price DOUBLE)
RETURNS DOUBLE
COMMENT 'Show marks only to entitled principals; others see NULL.'
RETURN CASE
  WHEN serverless_stable_ob2uyb_catalog.fe_bar_spike.visible_sub_book('CRUDE') THEN p_price
  ELSE CAST(NULL AS DOUBLE)
END;

ALTER TABLE serverless_stable_ob2uyb_catalog.fe_bar_spike.desk_positions
  ALTER COLUMN entry_price DROP MASK;

ALTER TABLE serverless_stable_ob2uyb_catalog.fe_bar_spike.desk_positions
  ALTER COLUMN entry_price SET MASK serverless_stable_ob2uyb_catalog.fe_bar_spike.mask_entry_price;
