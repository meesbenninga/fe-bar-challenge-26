# Databricks notebook source
# DBTITLE 1,FE Bar Producer — Generate Synthetic Weather & Trigger Chain
"""FE Bar Producer: generates a synthetic North Sea metocean event,
writes it to Delta (governed evidence path) and to Lakebase model_inputs
(hot path), then runs the M1→M2 chain directly.

Dual-sink: same event lands in both Delta (for Lakeflow SDP) and Lakebase
(for the <2s model chain). This notebook runs as a serverless job.
"""
import json, random, time, uuid
import psycopg
from pyspark.sql import SparkSession
from databricks.sdk import WorkspaceClient

spark = SparkSession.builder.getOrCreate()
w = WorkspaceClient()

CATALOG = "serverless_stable_ob2uyb_catalog"
SCHEMA = "fe_bar_spike"

# ── Generate one synthetic metocean event ─────────────────────────────
random.seed(int(time.time()))
event = {
    "event_id": f"evt_{uuid.uuid4().hex[:8]}",
    "curve_id": "NS_BRENT",
    "region": "UK",
    "event_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "wind_speed_kn": round(random.uniform(8, 38), 1),
    "wave_height_m": round(random.uniform(0.8, 7.5), 2),
    "sea_temp_c": round(random.uniform(5, 15), 1),
    "visibility_nm": round(random.uniform(2, 18), 1),
    "source": "fe-bar-producer",
}
print(f"Generated event: {event['event_id']}")
print(json.dumps(event, indent=2))

# ── Sink 1: Delta table (governed evidence) ──────────────────────────
df = spark.createDataFrame([event])
df.write.mode("append").saveAsTable(f"{CATALOG}.{SCHEMA}.metocean_events")
print(f"\n✅ Written to Delta: {CATALOG}.{SCHEMA}.metocean_events")

# ── Sink 2: Lakebase model_inputs (hot path) ─────────────────────────
ep = w.postgres.get_endpoint(
    name="projects/fe-bar-lakebase/branches/production/endpoints/primary"
)
host = ep.status.hosts.host
username = w.current_user.me().user_name
token = w.postgres.generate_database_credential(
    endpoint="projects/fe-bar-lakebase/branches/production/endpoints/primary"
).token

run_id = str(uuid.uuid4())
with psycopg.connect(
    host=host, dbname="databricks_postgres",
    user=username, password=token, sslmode="require"
) as conn:
    conn.autocommit = True
    conn.execute(
        "INSERT INTO fe_bar_chain.model_inputs (run_id, curve_id, region, payload) "
        "VALUES (%s, %s, %s, %s)",
        (run_id, event["curve_id"], event["region"], json.dumps(event))
    )
print(f"✅ Written to Lakebase: fe_bar_chain.model_inputs (run_id={run_id})")

# ── Prices (latest synthetic tick) ───────────────────────────────────
price = {
    "brent_spot_usd": round(random.uniform(75, 95), 2),
    "brent_m1_usd": round(random.uniform(73, 93), 2),
    "crack_spread_usd": round(random.uniform(10, 22), 2),
}
print(f"\nPrice context: {price}")
print(f"\nrun_id={run_id} ready for chain trigger.")