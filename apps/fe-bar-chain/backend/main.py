"""FastAPI application — FE Bar model-chain spike.

Endpoints:
  POST /trigger   — run the M1→M2 chain for a single metocean event
  GET  /healthz   — liveness (models loaded, Lakebase reachable)
  GET  /           — root redirect to /docs
"""
import logging

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(
    title="fe-bar-chain",
    description="FE Bar spike: M1 metocean → M2 VaR model chain",
    version="0.1.0",
)


# ---- request / response models ----------------------------------------

class TriggerRequest(BaseModel):
    wind_speed_kn: float = Field(..., description="Wind speed in knots")
    wave_height_m: float = Field(..., description="Significant wave height (m)")
    sea_temp_c: float = Field(..., description="Sea surface temperature (°C)")
    visibility_nm: float = Field(..., description="Visibility (nautical miles)")
    brent_spot_usd: float = Field(..., description="Brent spot price (USD/bbl)")
    brent_m1_usd: float = Field(..., description="Brent M+1 futures (USD/bbl)")
    crack_spread_usd: float = Field(..., description="Crack spread (USD/bbl)")
    curve_id: str = Field(default="NS_BRENT", description="Curve identifier")
    region: str = Field(default="UK", description="Region")


class TriggerResponse(BaseModel):
    run_id: str
    curve_id: str
    region: str
    m1: dict
    m2: dict
    total_ms: int


# ---- endpoints ---------------------------------------------------------

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/docs")


@app.get("/healthz")
def healthz():
    """Liveness: models loaded, Lakebase pool open."""
    from .chain import _m1, _m2  # noqa: F811
    from .lakebase import get_pool
    pool = get_pool()
    return {
        "status": "ok",
        "m1_loaded": _m1 is not None,
        "m2_loaded": _m2 is not None,
        "pool_size": pool.get_stats().pool_size,
    }


@app.post("/trigger-dry")
def trigger_dry(req: TriggerRequest):
    """Run M1→M2 without Lakebase writes (evidence endpoint)."""
    import time, uuid, traceback
    try:
        import pandas as pd
        import numpy as np
        from .chain import _m1, _m2
        t0 = time.perf_counter()
        run_id = str(uuid.uuid4())
        # M1
        t1 = time.perf_counter()
        m1_in = pd.DataFrame([{"wind_speed_kn": req.wind_speed_kn, "wave_height_m": req.wave_height_m,
                               "sea_temp_c": req.sea_temp_c, "visibility_nm": req.visibility_nm}])
        doc = float(_m1.predict(m1_in)[0])
        m1_ms = int((time.perf_counter() - t1) * 1000)
        # M2
        t2 = time.perf_counter()
        m2_in = pd.DataFrame([{"days_of_cover": doc, "brent_spot_usd": req.brent_spot_usd,
                               "brent_m1_usd": req.brent_m1_usd, "crack_spread_usd": req.crack_spread_usd}])
        var_d = float(_m2.predict(m2_in)[0])
        m2_ms = int((time.perf_counter() - t2) * 1000)
        total_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "run_id": run_id, "curve_id": req.curve_id, "region": req.region,
            "m1": {"days_of_cover": round(doc, 4), "latency_ms": m1_ms},
            "m2": {"var_delta_usd": round(var_d, 4), "latency_ms": m2_ms},
            "total_ms": total_ms, "dry_run": True,
        }
    except Exception as exc:
        log.exception("trigger-dry failed")
        raise HTTPException(status_code=500, detail=traceback.format_exc()[-500:]) from exc


@app.post("/trigger", response_model=TriggerResponse)
def trigger(req: TriggerRequest):
    """Run the M1→M2 model chain for a single metocean event.

    The <2s clock starts when this endpoint receives the POST.
    """
    from .chain import run_chain
    try:
        result = run_chain(req.model_dump())
        return TriggerResponse(**result)
    except Exception as exc:
        log.exception("Chain failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
