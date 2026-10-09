# Databricks notebook source
# DBTITLE 1,FE Bar History: Lakebase → Delta
"""Copy model_outputs, run_state, control_metrics from Lakebase into Delta history tables.
Scheduled every 5 minutes via fe-bar-history job.
"""
import psycopg
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
CATALOG = "serverless_stable_ob2uyb_catalog"
SCHEMA = "fe_bar_spike"

ep = w.postgres.get_endpoint(name="projects/fe-bar-lakebase/branches/production/endpoints/primary")
lb_host = ep.status.hosts.host
username = w.current_user.me().user_name
token = w.postgres.generate_database_credential(
    endpoint="projects/fe-bar-lakebase/branches/production/endpoints/primary").token

with psycopg.connect(host=lb_host, dbname="databricks_postgres",
                     user=username, password=token, sslmode="require") as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT run_id::text, model_id, version, result::text, latency_ms, created_at::text FROM fe_bar_chain.model_outputs")
        mo_rows = cur.fetchall()
        cur.execute("SELECT run_id::text, status, started_at::text, completed_at::text, total_ms FROM fe_bar_chain.run_state")
        rs_rows = cur.fetchall()
        cur.execute("SELECT run_id, hop, ms, ts::text FROM fe_bar_chain.control_metrics")
        cm_rows = cur.fetchall()

for name, rows, cols in [
    ("history_model_outputs", mo_rows, ["run_id","model_id","version","result","latency_ms","created_at"]),
    ("history_run_state", rs_rows, ["run_id","status","started_at","completed_at","total_ms"]),
    ("history_control_metrics", cm_rows, ["run_id","hop","ms","ts"]),
]:
    df = spark.createDataFrame(rows, cols)
    df.write.mode("overwrite").saveAsTable(f"{CATALOG}.{SCHEMA}.{name}")
    print(f"✅ {name}: {df.count()}")

# COMMAND ----------

