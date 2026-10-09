"""fe-bar-producer: proves HTTP OAuth M2M auth to fe-bar-chain.
No secrets in source — credentials injected by the platform.
"""
import base64, json, os, random, sys, time, traceback
from typing import Any, Dict

import requests as http_requests
from databricks.sdk import WorkspaceClient
from fastapi import FastAPI

app = FastAPI(title="fe-bar-producer")
_evidence_result: Dict[str, Any] = {}

FE_BAR_CHAIN_URL = os.environ.get(
    "FE_BAR_CHAIN_URL",
    "https://fe-bar-chain-7474658263595816.aws.databricksapps.com",
)


_run_results: list = []


@app.get("/healthz")
def healthz():
    return {"status": "ok", "app": "fe-bar-producer", "evidence": bool(_evidence_result), "runs": len(_run_results)}


@app.get("/run")
def run_triggers(n: int = 20):
    """Fire n triggers across both curves, return p50/p95."""
    global _run_results
    w = WorkspaceClient()
    headers = w.config._header_factory()
    curves = ["NS_BRENT", "NS_GASOIL"]
    results = []
    for i in range(n):
        curve = curves[i % 2]
        payload = {
            "wind_speed_kn": round(random.uniform(28, 38), 1),
            "wave_height_m": round(random.uniform(4.5, 7.5), 2),
            "sea_temp_c": round(random.uniform(5, 12), 1),
            "visibility_nm": round(random.uniform(2, 8), 1),
            "brent_spot_usd": round(random.uniform(80, 92), 2),
            "brent_m1_usd": round(random.uniform(78, 90), 2),
            "crack_spread_usd": round(random.uniform(12, 22), 2),
            "curve_id": curve,
            "region": "UK" if curve == "NS_BRENT" else "NL",
        }
        t0 = time.perf_counter()
        try:
            resp = http_requests.post(
                f"{FE_BAR_CHAIN_URL}/trigger",
                headers={**headers, "Content-Type": "application/json"},
                json=payload, timeout=30, allow_redirects=False,
            )
            wall_ms = int((time.perf_counter() - t0) * 1000)
            body = resp.json() if resp.status_code == 200 else {"error": resp.text[:200]}
            results.append({"i": i, "curve": curve, "status": resp.status_code,
                           "wall_ms": wall_ms, "body": body})
        except Exception as e:
            results.append({"i": i, "curve": curve, "status": 0, "wall_ms": 0, "error": str(e)})
    _run_results = results
    # Compute p50/p95 per curve
    import statistics
    stats = {}
    for c in curves:
        times = [r["wall_ms"] for r in results if r["curve"] == c and r["status"] == 200]
        if times:
            times.sort()
            p50 = times[len(times) // 2]
            p95 = times[int(len(times) * 0.95)]
            stats[c] = {"count": len(times), "p50_ms": p50, "p95_ms": p95,
                        "min_ms": min(times), "max_ms": max(times)}
    return {"total": n, "ok": sum(1 for r in results if r["status"] == 200),
            "stats": stats, "results": results[:5]}


@app.get("/evidence")
def get_evidence():
    return _evidence_result


def _safe_json(resp) -> Any:
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text[:500]}


@app.on_event("startup")
def auto_run_evidence():
    """Runs at startup: fire 20 triggers across both curves, save to Delta."""
    global _evidence_result
    log = []  # Collect all logs

    def _log(msg):
        print(msg, flush=True)
        log.append(msg)

    def _save_to_delta(data_json: str):
        """Write evidence to Delta table via SQL Statement Execution API."""
        w = WorkspaceClient()
        hdrs = w.config._header_factory()
        host = w.config.host
        safe = data_json.replace("'", "''")
        resp = http_requests.post(
            f"{host}/api/2.0/sql/statements",
            headers={**hdrs, "Content-Type": "application/json"},
            json={
                "warehouse_id": "0e54af629ab8456e",
                "statement": f"INSERT INTO serverless_stable_ob2uyb_catalog.fe_bar_spike.http_evidence VALUES (current_timestamp(), '{safe}')",
                "wait_timeout": "30s",
            },
            timeout=35,
        )
        _log(f"  Delta INSERT: {resp.status_code} {resp.text[:200]}")

    try:
        # Step 1: SDK auth
        _log("Step 1: WorkspaceClient()")
        w = WorkspaceClient()
        headers = w.config._header_factory()
        auth_val = headers.get("Authorization", "")
        token_type = "JWT" if auth_val.startswith("Bearer ey") else "PAT" if "dkea" in auth_val else "other"
        _log(f"  Token type: {token_type}, len: {len(auth_val)}")

        # Step 1b: Save marker to Delta immediately
        _save_to_delta(json.dumps({"step": "marker", "token_type": token_type, "ts": time.time()}))

        # Step 2: GET /healthz
        _log("Step 2: GET /healthz")
        t0 = time.perf_counter()
        resp_h = http_requests.get(
            f"{FE_BAR_CHAIN_URL}/healthz",
            headers=headers,
            timeout=30,
            allow_redirects=False,
        )
        healthz_ms = int((time.perf_counter() - t0) * 1000)
        _log(f"  Status: {resp_h.status_code}, {healthz_ms}ms")

        # Step 3: Fire 20 triggers across both curves
        _log("Step 3: Fire 20 triggers")
        random.seed(int(time.time()))
        curves = ["NS_BRENT", "NS_GASOIL"]
        run_results = []
        for i in range(20):
            curve = curves[i % 2]
            payload = {
                "wind_speed_kn": round(random.uniform(28, 38), 1),
                "wave_height_m": round(random.uniform(4.5, 7.5), 2),
                "sea_temp_c": round(random.uniform(5, 12), 1),
                "visibility_nm": round(random.uniform(2, 8), 1),
                "brent_spot_usd": round(random.uniform(80, 92), 2),
                "brent_m1_usd": round(random.uniform(78, 90), 2),
                "crack_spread_usd": round(random.uniform(12, 22), 2),
                "curve_id": curve,
                "region": "UK" if curve == "NS_BRENT" else "NL",
            }
            t1 = time.perf_counter()
            try:
                resp_t = http_requests.post(
                    f"{FE_BAR_CHAIN_URL}/trigger",
                    headers={**headers, "Content-Type": "application/json"},
                    json=payload, timeout=30, allow_redirects=False,
                )
                wall_ms = int((time.perf_counter() - t1) * 1000)
                body = _safe_json(resp_t)
                run_results.append({"i": i, "curve": curve, "status": resp_t.status_code,
                                    "wall_ms": wall_ms, "body": body})
                _log(f"  [{i}] {curve} -> {resp_t.status_code} {wall_ms}ms")
            except Exception as e:
                run_results.append({"i": i, "curve": curve, "status": 0, "error": str(e)})
                _log(f"  [{i}] {curve} -> ERROR {e}")

        # Compute p50/p95 per curve
        import statistics
        stats = {}
        for c in curves:
            times = [r["wall_ms"] for r in run_results if r.get("curve") == c and r.get("status") == 200]
            if times:
                times.sort()
                p50 = times[len(times) // 2]
                p95 = times[int(len(times) * 0.95)]
                stats[c] = {"count": len(times), "p50_ms": p50, "p95_ms": p95}

        _evidence_result = {
            "auth_type": token_type,
            "healthz_status": resp_h.status_code,
            "healthz_ms": healthz_ms,
            "total_triggers": 20,
            "ok": sum(1 for r in run_results if r.get("status") == 200),
            "stats": stats,
            "runs": run_results[:5],
            "log": log,
        }

        # Step 4: Verify oil-desk endpoints
        _log("Step 4: Verify fe-bar-oil-desk")
        DESK_URL = "https://fe-bar-oil-desk-7474658263595816.aws.databricksapps.com"
        desk_risk = http_requests.get(f"{DESK_URL}/api/risk", headers=headers, timeout=30, allow_redirects=False)
        _log(f"  /api/risk: {desk_risk.status_code}")
        desk_decision = http_requests.get(f"{DESK_URL}/api/decision", headers=headers, timeout=60, allow_redirects=False)
        _log(f"  /api/decision: {desk_decision.status_code}")

        _evidence_result["desk_verification"] = {
            "risk_status": desk_risk.status_code,
            "risk_body": desk_risk.text[:300] if desk_risk.status_code == 200 else desk_risk.text[:100],
            "decision_status": desk_decision.status_code,
            "decision_body": desk_decision.text[:500] if desk_decision.status_code == 200 else desk_decision.text[:100],
        }

        # Step 5: Save to Delta
        _log("Step 5: Save to Delta")
        _save_to_delta(json.dumps(_evidence_result))
        _log("DONE")

    except Exception:
        err = traceback.format_exc()
        _log(f"ERROR:\n{err}")
        _evidence_result = {"error": err, "log": log}
        try:
            _save_to_delta(json.dumps(_evidence_result))
        except Exception:
            pass
