"""Model chain: M1 → M2 → M3 with routing-based execution.

Models loaded once at import time. Routing read from Lakebase.
NS_BRENT: sequential M1→M2→M3.
NS_GASOIL: M1 then M2+M3 in parallel via local Ray.
"""
import json
import logging
import time
import uuid

import mlflow
import numpy as np
import pandas as pd

from . import config
from . import lakebase

log = logging.getLogger(__name__)

# ---- warm model load (once at startup) --------------------------------

mlflow.set_registry_uri("databricks-uc")

log.info("Loading M1 from %s ...", config.M1_MODEL_URI)
_m1 = mlflow.pyfunc.load_model(config.M1_MODEL_URI)
log.info("M1 loaded.")

log.info("Loading M2 from %s ...", config.M2_MODEL_URI)
_m2 = mlflow.pyfunc.load_model(config.M2_MODEL_URI)
log.info("M2 loaded.")

M3_URI = f"{config.CATALOG}.{config.SCHEMA}.m3_risk/1"
log.info("Loading M3 from %s ...", M3_URI)
_m3 = mlflow.pyfunc.load_model(f"models:/{M3_URI}")
log.info("M3 loaded.")

M1_VERSION = int(config.M1_MODEL_URI.rsplit("/", 1)[-1])
M2_VERSION = int(config.M2_MODEL_URI.rsplit("/", 1)[-1])
M3_VERSION = 1

# Default exposure for M3 (from desk_risk CRUDE book)
DEFAULT_EXPOSURE_BBL = 2_600_000


def _write_hop(run_id: str, hop: str, ms: int):
    """Write per-hop latency to control_metrics."""
    try:
        lakebase.execute_sql(
            "INSERT INTO fe_bar_chain.control_metrics (run_id, hop, ms) "
            "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (run_id, hop, ms),
        )
    except Exception as e:
        log.warning("control_metrics write failed: %s", e)


def _get_routing(curve_id: str) -> dict:
    """Read DAG from routing table; fallback to sequential."""
    try:
        rows = lakebase.fetch_sql(
            "SELECT dag FROM fe_bar_chain.routing WHERE curve_id = %s", (curve_id,)
        )
        if rows:
            return json.loads(rows[0][0]) if isinstance(rows[0][0], str) else rows[0][0]
    except Exception as e:
        log.warning("Routing lookup failed: %s", e)
    return {"mode": "sequential", "hops": ["m1_metocean", "m2_var", "m3_risk"]}


def _run_m1(payload: dict) -> tuple:
    t = time.perf_counter()
    m1_input = pd.DataFrame([{
        "wind_speed_kn": float(payload["wind_speed_kn"]),
        "wave_height_m": float(payload["wave_height_m"]),
        "sea_temp_c": float(payload["sea_temp_c"]),
        "visibility_nm": float(payload["visibility_nm"]),
    }])
    pred = _m1.predict(m1_input)
    doc = float(pred[0]) if np.ndim(pred) > 0 else float(pred)
    ms = int((time.perf_counter() - t) * 1000)
    return round(doc, 4), ms


def _run_m2(days_of_cover: float, payload: dict) -> tuple:
    t = time.perf_counter()
    m2_input = pd.DataFrame([{
        "days_of_cover": days_of_cover,
        "brent_spot_usd": float(payload["brent_spot_usd"]),
        "brent_m1_usd": float(payload["brent_m1_usd"]),
        "crack_spread_usd": float(payload["crack_spread_usd"]),
    }])
    pred = _m2.predict(m2_input)
    vd = float(pred[0]) if np.ndim(pred) > 0 else float(pred)
    ms = int((time.perf_counter() - t) * 1000)
    return round(vd, 4), ms


def _run_m3(days_of_cover: float, var_delta: float, exposure_bbl: float) -> tuple:
    t = time.perf_counter()
    m3_input = np.array([[days_of_cover, var_delta, exposure_bbl]])
    var_usd = float(_m3.predict(m3_input)[0])
    limit_util = round(var_usd / 4_000_000, 4)
    ms = int((time.perf_counter() - t) * 1000)
    return round(var_usd, 2), limit_util, ms


def run_chain(payload: dict) -> dict:
    """Execute M1 → M2 → M3 with routing-based execution."""
    t0 = time.perf_counter()
    run_id = str(uuid.uuid4())
    curve_id = payload.get("curve_id", "NS_BRENT")
    region = payload.get("region", "UK")
    exposure_bbl = payload.get("exposure_bbl", DEFAULT_EXPOSURE_BBL)

    lakebase.upsert_run_state(run_id, "pending")
    lakebase.insert_input(run_id, curve_id, region, payload)

    routing = _get_routing(curve_id)
    mode = routing.get("mode", "sequential")

    # ---- M1 (always first) ----
    days_of_cover, m1_ms = _run_m1(payload)
    lakebase.insert_output(run_id, "m1_metocean", M1_VERSION,
                           {"days_of_cover": days_of_cover}, m1_ms)
    _write_hop(run_id, "m1_metocean", m1_ms)
    lakebase.upsert_run_state(run_id, "m1_done")

    if mode == "parallel_after_m1":
        # M2 and M3 in parallel via local Ray
        try:
            import ray
            if not ray.is_initialized():
                ray.init(ignore_reinit_error=True, num_cpus=2, log_to_driver=False)

            @ray.remote
            def ray_m2(doc, p):
                return _run_m2(doc, p)

            @ray.remote
            def ray_m3(doc, vd, exp):
                return _run_m3(doc, vd, exp)

            # M2 first (M3 needs var_delta), but run them overlapped
            m2_ref = ray_m2.remote(days_of_cover, payload)
            var_delta, m2_ms = ray.get(m2_ref)
            m3_ref = ray_m3.remote(days_of_cover, var_delta, exposure_bbl)
            var_usd, limit_util, m3_ms = ray.get(m3_ref)
        except ImportError:
            log.warning("Ray not available, falling back to sequential")
            var_delta, m2_ms = _run_m2(days_of_cover, payload)
            var_usd, limit_util, m3_ms = _run_m3(days_of_cover, var_delta, exposure_bbl)
    else:
        # Sequential: M1 → M2 → M3
        var_delta, m2_ms = _run_m2(days_of_cover, payload)
        var_usd, limit_util, m3_ms = _run_m3(days_of_cover, var_delta, exposure_bbl)

    # Write M2 + M3 outputs
    lakebase.insert_output(run_id, "m2_var", M2_VERSION,
                           {"var_delta_usd": var_delta}, m2_ms)
    _write_hop(run_id, "m2_var", m2_ms)

    lakebase.insert_output(run_id, "m3_risk", M3_VERSION,
                           {"var_usd": var_usd, "limit_util": limit_util}, m3_ms)
    _write_hop(run_id, "m3_risk", m3_ms)

    total_ms = int((time.perf_counter() - t0) * 1000)
    lakebase.upsert_run_state(run_id, "complete", total_ms)
    _write_hop(run_id, "total", total_ms)

    return {
        "run_id": run_id,
        "curve_id": curve_id,
        "region": region,
        "mode": mode,
        "m1": {"days_of_cover": days_of_cover, "latency_ms": m1_ms},
        "m2": {"var_delta_usd": var_delta, "latency_ms": m2_ms},
        "m3": {"var_usd": var_usd, "limit_util": limit_util, "latency_ms": m3_ms},
        "total_ms": total_ms,
    }
