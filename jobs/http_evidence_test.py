# Databricks notebook source
# DBTITLE 1,HTTP Evidence Test — SP-authenticated calls to fe-bar-chain
"""HTTP Evidence Test

This notebook runs as a serverless job (OAuth JWT, not PAT).
It proves the M1→M2 chain works via real HTTP to the fe-bar-chain App,
not via in-process Python calls.

Outputs are written to the notebook task result for retrieval.
"""
import json, time, random, uuid, requests
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

# ── Auth check: must be OAuth JWT, not PAT ────────────────────────────
headers = w.config._header_factory()
auth_val = headers.get("Authorization", "")
assert auth_val.startswith("Bearer ey"), (
    f"Expected OAuth JWT (ey…), got: {auth_val[:30]}… — "
    "run this from a serverless job, not a notebook"
)
print(f"✅ Auth token is OAuth JWT (length={len(auth_val)})")

APP_URL = "https://fe-bar-chain-7474658263595816.aws.databricksapps.com"

# ═══════════════════════════════════════════════════════════════════════
# 1. GET /healthz
# ═══════════════════════════════════════════════════════════════════════
t0 = time.perf_counter()
resp_h = requests.get(f"{APP_URL}/healthz", headers=headers, timeout=30)
healthz_ms = int((time.perf_counter() - t0) * 1000)

print(f"\nGET {APP_URL}/healthz")
print(f"  Status: {resp_h.status_code}")
print(f"  Content-Type: {resp_h.headers.get('content-type')}")
print(f"  Wall clock: {healthz_ms} ms")
try:
    healthz_json = resp_h.json()
    print(f"  Body: {json.dumps(healthz_json, indent=2)}")
except Exception:
    healthz_json = {"raw": resp_h.text[:500]}
    print(f"  Body (raw): {resp_h.text[:500]}")

assert resp_h.status_code == 200, f"healthz failed: {resp_h.status_code}"

# ═══════════════════════════════════════════════════════════════════════
# 2. POST /trigger
# ═══════════════════════════════════════════════════════════════════════
random.seed(int(time.time()))
payload = {
    "wind_speed_kn": round(random.uniform(28, 38), 1),
    "wave_height_m": round(random.uniform(4.5, 7.5), 2),
    "sea_temp_c": round(random.uniform(5, 12), 1),
    "visibility_nm": round(random.uniform(2, 8), 1),
    "brent_spot_usd": round(random.uniform(80, 92), 2),
    "brent_m1_usd": round(random.uniform(78, 90), 2),
    "crack_spread_usd": round(random.uniform(12, 22), 2),
    "curve_id": "NS_BRENT",
    "region": "UK",
}

req_headers = {**headers, "Content-Type": "application/json"}
t1 = time.perf_counter()
resp_t = requests.post(
    f"{APP_URL}/trigger",
    headers=req_headers,
    json=payload,
    timeout=60,
)
trigger_ms = int((time.perf_counter() - t1) * 1000)

print(f"\nPOST {APP_URL}/trigger")
print(f"  Status: {resp_t.status_code}")
print(f"  Content-Type: {resp_t.headers.get('content-type')}")
print(f"  Wall clock: {trigger_ms} ms")
try:
    trigger_json = resp_t.json()
    print(f"  Body: {json.dumps(trigger_json, indent=2)}")
except Exception:
    trigger_json = {"raw": resp_t.text[:500]}
    print(f"  Body (raw): {resp_t.text[:500]}")

assert resp_t.status_code == 200, f"trigger failed: {resp_t.status_code}"

# ═══════════════════════════════════════════════════════════════════════
# 3. Verify in Lakebase
# ═══════════════════════════════════════════════════════════════════════
import psycopg

ep = w.postgres.get_endpoint(
    name="projects/fe-bar-lakebase/branches/production/endpoints/primary")
lb_host = ep.status.hosts.host
username = w.current_user.me().user_name
token = w.postgres.generate_database_credential(
    endpoint="projects/fe-bar-lakebase/branches/production/endpoints/primary").token

run_id = trigger_json.get("run_id", "")
print(f"\nLakebase verification for run_id={run_id}")

with psycopg.connect(host=lb_host, dbname="databricks_postgres",
                     user=username, password=token, sslmode="require") as conn:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT run_id, model_id, latency_ms FROM fe_bar_chain.model_outputs "
            "WHERE run_id = %s ORDER BY model_id", (run_id,))
        outputs = cur.fetchall()
        cur.execute(
            "SELECT * FROM fe_bar_chain.run_state WHERE run_id = %s", (run_id,))
        run_state = cur.fetchall()
        rs_cols = [d.name for d in cur.description]

print("\n=== model_outputs ===")
for r in outputs:
    print(f"  run_id={r[0]}, model_id={r[1]}, latency_ms={r[2]}")

print("\n=== run_state ===")
for r in run_state:
    row = dict(zip(rs_cols, r))
    print(f"  {row}")

# ═══════════════════════════════════════════════════════════════════════
# 4. Summary (notebook task value for retrieval)
# ═══════════════════════════════════════════════════════════════════════
evidence = {
    "auth_type": "OAuth JWT (serverless job)",
    "healthz": {
        "url": f"{APP_URL}/healthz",
        "method": "GET",
        "status_code": resp_h.status_code,
        "wall_clock_ms": healthz_ms,
        "response": healthz_json,
    },
    "trigger": {
        "url": f"{APP_URL}/trigger",
        "method": "POST",
        "status_code": resp_t.status_code,
        "wall_clock_ms": trigger_ms,
        "request_body": payload,
        "response": trigger_json,
    },
    "lakebase_run_id": run_id,
    "lakebase_outputs": [{"run_id": str(r[0]), "model_id": r[1], "latency_ms": r[2]} for r in outputs],
    "lakebase_run_state": [{k: str(v) for k, v in dict(zip(rs_cols, r)).items()} for r in run_state],
}

print("\n" + "="*72)
print("EVIDENCE JSON (for EVIDENCE_SPIKE.md)")
print("="*72)
print(json.dumps(evidence, indent=2))

# Exit with the evidence as the task value
dbutils.notebook.exit(json.dumps(evidence))