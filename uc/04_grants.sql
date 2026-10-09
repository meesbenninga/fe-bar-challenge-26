-- App service principals. Names are the Databricks App SP client ids.
-- Oil desk:  a3bbd7fc-6104-4ccc-b1b3-7a0def4e1710
-- Chain:     80975e8e-3594-4559-8e64-8530191b8bf4
-- Producer:  ca8a8140-9be1-4fe5-95b0-8ec8c09319ca

GRANT USE CATALOG ON CATALOG serverless_stable_ob2uyb_catalog TO `a3bbd7fc-6104-4ccc-b1b3-7a0def4e1710`;
GRANT USE CATALOG ON CATALOG serverless_stable_ob2uyb_catalog TO `80975e8e-3594-4559-8e64-8530191b8bf4`;
GRANT USE CATALOG ON CATALOG serverless_stable_ob2uyb_catalog TO `ca8a8140-9be1-4fe5-95b0-8ec8c09319ca`;

GRANT USE SCHEMA ON SCHEMA serverless_stable_ob2uyb_catalog.fe_bar_spike TO `a3bbd7fc-6104-4ccc-b1b3-7a0def4e1710`;
GRANT USE SCHEMA ON SCHEMA serverless_stable_ob2uyb_catalog.fe_bar_spike TO `80975e8e-3594-4559-8e64-8530191b8bf4`;
GRANT USE SCHEMA ON SCHEMA serverless_stable_ob2uyb_catalog.fe_bar_spike TO `ca8a8140-9be1-4fe5-95b0-8ec8c09319ca`;

GRANT SELECT ON SCHEMA serverless_stable_ob2uyb_catalog.fe_bar_spike TO `a3bbd7fc-6104-4ccc-b1b3-7a0def4e1710`;
GRANT SELECT ON SCHEMA serverless_stable_ob2uyb_catalog.fe_bar_spike TO `80975e8e-3594-4559-8e64-8530191b8bf4`;
GRANT SELECT ON SCHEMA serverless_stable_ob2uyb_catalog.fe_bar_spike TO `ca8a8140-9be1-4fe5-95b0-8ec8c09319ca`;

GRANT EXECUTE ON FUNCTION serverless_stable_ob2uyb_catalog.fe_bar_spike.hedge_size TO `a3bbd7fc-6104-4ccc-b1b3-7a0def4e1710`;
GRANT EXECUTE ON FUNCTION serverless_stable_ob2uyb_catalog.fe_bar_spike.post_action_util TO `a3bbd7fc-6104-4ccc-b1b3-7a0def4e1710`;
GRANT EXECUTE ON FUNCTION serverless_stable_ob2uyb_catalog.fe_bar_spike.reroute_econ TO `a3bbd7fc-6104-4ccc-b1b3-7a0def4e1710`;

GRANT EXECUTE ON MODEL serverless_stable_ob2uyb_catalog.fe_bar_spike.m1_metocean TO `80975e8e-3594-4559-8e64-8530191b8bf4`;
GRANT EXECUTE ON MODEL serverless_stable_ob2uyb_catalog.fe_bar_spike.m2_var TO `80975e8e-3594-4559-8e64-8530191b8bf4`;
GRANT EXECUTE ON MODEL serverless_stable_ob2uyb_catalog.fe_bar_spike.m3_risk TO `80975e8e-3594-4559-8e64-8530191b8bf4`;
