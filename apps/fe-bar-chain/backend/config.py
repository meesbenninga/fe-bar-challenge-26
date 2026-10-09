"""Configuration — all from env, no secrets in source."""
import os

CATALOG = os.environ.get("FE_BAR_CATALOG", "serverless_stable_ob2uyb_catalog")
SCHEMA = os.environ.get("FE_BAR_SCHEMA", "fe_bar_spike")

M1_MODEL_URI = os.environ.get(
    "M1_MODEL_URI",
    f"models:/{CATALOG}.{SCHEMA}.m1_metocean/1",
)
M2_MODEL_URI = os.environ.get(
    "M2_MODEL_URI",
    f"models:/{CATALOG}.{SCHEMA}.m2_var/1",
)

LAKEBASE_ENDPOINT = os.environ.get(
    "LAKEBASE_ENDPOINT",
    "projects/fe-bar-lakebase/branches/production/endpoints/primary",
)
LAKEBASE_HOST = os.environ.get(
    "LAKEBASE_HOST",
    "ep-dawn-bonus-d7iass6n.database.eu-central-1.cloud.databricks.com",
)
LAKEBASE_DB = os.environ.get("LAKEBASE_DB", "databricks_postgres")
LAKEBASE_SCHEMA = os.environ.get("LAKEBASE_SCHEMA", "fe_bar_chain")
