"""FE Bar Oil Desk — business surface for Trafigura physical oil desk.
No secrets in source. Credentials injected by platform at App runtime.
"""
import hashlib, json, os, time, uuid
from typing import Any

import psycopg
import requests as http_requests
from databricks.sdk import WorkspaceClient
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="fe-bar-oil-desk")

FE_BAR_CHAIN_URL = os.environ.get("FE_BAR_CHAIN_URL",
    "https://fe-bar-chain-7474658263595816.aws.databricksapps.com")
GENIE_SPACE_ID = os.environ.get("GENIE_SPACE_ID", "01f1c3da7f691ea7b087b1c6695bfdd3")
LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "databricks-claude-opus-4-8")
WAREHOUSE_ID = "0e54af629ab8456e"
LAKEBASE_ENDPOINT = "projects/fe-bar-lakebase/branches/production/endpoints/primary"


def _sdk():
    return WorkspaceClient()


def _headers():
    return _sdk().config._header_factory()


def _sql_query(sql: str) -> list:
    """Execute SQL via Statement Execution API, return rows."""
    w = _sdk()
    host = w.config.host
    hdrs = _headers()
    resp = http_requests.post(f"{host}/api/2.0/sql/statements",
        headers={**hdrs, "Content-Type": "application/json"},
        json={"warehouse_id": WAREHOUSE_ID, "statement": sql, "wait_timeout": "30s"},
        timeout=35)
    data = resp.json()
    if data.get("status", {}).get("state") == "SUCCEEDED":
        result = data.get("result", {})
        cols = [c["name"] for c in data.get("manifest", {}).get("schema", {}).get("columns", [])]
        rows = result.get("data_array", [])
        return [{cols[i]: row[i] for i in range(len(cols))} for row in rows]
    return []


def _lakebase_read(sql: str, params=None) -> list:
    """Read from Lakebase."""
    w = _sdk()
    ep = w.postgres.get_endpoint(name=LAKEBASE_ENDPOINT)
    lb_host = ep.status.hosts.host
    username = w.current_user.me().user_name
    token = w.postgres.generate_database_credential(endpoint=LAKEBASE_ENDPOINT).token
    with psycopg.connect(host=lb_host, dbname="databricks_postgres",
                         user=username, password=token, sslmode="require") as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d.name for d in cur.description]
            return [{cols[i]: str(r[i]) for i in range(len(cols))} for r in cur.fetchall()]


def _lakebase_write(sql: str, params=None):
    w = _sdk()
    ep = w.postgres.get_endpoint(name=LAKEBASE_ENDPOINT)
    lb_host = ep.status.hosts.host
    username = w.current_user.me().user_name
    token = w.postgres.generate_database_credential(endpoint=LAKEBASE_ENDPOINT).token
    with psycopg.connect(host=lb_host, dbname="databricks_postgres",
                         user=username, password=token, sslmode="require") as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql, params)


# ════════════════ API ENDPOINTS ════════════════

@app.get("/healthz")
def healthz():
    return {"status": "ok", "app": "fe-bar-oil-desk"}


@app.get("/api/trigger")
def trigger_chain():
    """Trigger fe-bar-chain with sample data, return per-hop ms."""
    import random
    hdrs = _headers()
    payload = {
        "wind_speed_kn": round(random.uniform(28, 38), 1),
        "wave_height_m": round(random.uniform(4.5, 7.5), 2),
        "sea_temp_c": round(random.uniform(5, 12), 1),
        "visibility_nm": round(random.uniform(2, 8), 1),
        "brent_spot_usd": round(random.uniform(80, 92), 2),
        "brent_m1_usd": round(random.uniform(78, 90), 2),
        "crack_spread_usd": round(random.uniform(12, 22), 2),
        "curve_id": "NS_BRENT", "region": "UK",
    }
    t0 = time.perf_counter()
    resp = http_requests.post(f"{FE_BAR_CHAIN_URL}/trigger",
        headers={**hdrs, "Content-Type": "application/json"},
        json=payload, timeout=30, allow_redirects=False)
    wall_ms = int((time.perf_counter() - t0) * 1000)
    body = resp.json() if resp.status_code == 200 else {"error": resp.text[:200]}
    # Read control_metrics
    run_id = body.get("run_id", "")
    hops = []
    if run_id:
        try:
            hops = _lakebase_read(
                "SELECT hop, ms FROM fe_bar_chain.control_metrics WHERE run_id = %s ORDER BY hop",
                (run_id,))
        except Exception:
            pass
    return {"status": resp.status_code, "wall_ms": wall_ms, "body": body,
            "hops": hops, "budget_ms": 5000}


@app.get("/api/risk")
def get_risk():
    """Desk risk from metric view."""
    rows = _sql_query(
        "SELECT * FROM serverless_stable_ob2uyb_catalog.fe_bar_spike.desk_risk_mv")
    return {"risk": rows}


@app.get("/api/pnl")
def get_pnl():
    """MTD P&L from metric view."""
    rows = _sql_query(
        "SELECT * FROM serverless_stable_ob2uyb_catalog.fe_bar_spike.desk_pnl_mv")
    return {"pnl": rows}


@app.get("/api/outcome")
def get_outcome():
    """Headline business outcome from governed views and UC functions (no LLM)."""
    cat = "serverless_stable_ob2uyb_catalog.fe_bar_spike"
    risk = _sql_query(f"SELECT * FROM {cat}.desk_risk_mv WHERE sub_book = 'CRUDE'")
    pnl = _sql_query(f"SELECT * FROM {cat}.desk_pnl_mv")
    hedge_rows = _sql_query(f"SELECT {cat}.hedge_size('CRUDE') AS hedge_bbl")
    hedge_bbl = int(float(hedge_rows[0]["hedge_bbl"])) if hedge_rows else 0
    post_rows = _sql_query(f"SELECT {cat}.post_action_util('CRUDE', {hedge_bbl}) AS post_util")
    crude = risk[0] if risk else {}
    return {
        "crude_util": float(crude.get("limit_utilisation") or 0),
        "crude_var_usd": float(crude.get("var_95_usd") or 0),
        "crude_limit_usd": float(crude.get("limit_usd") or 0),
        "hedge_bbl": hedge_bbl,
        "post_util": float(post_rows[0]["post_util"]) if post_rows else 0,
        "pnl": [{"leg": p.get("leg_type"), "mtd_usd": float(p.get("mtd_pnl_usd") or 0)} for p in pnl],
    }


@app.get("/api/ask")
def ask_genie(q: str):
    """Proxy to Genie Conversation API."""
    w = _sdk()
    host = w.config.host
    hdrs = _headers()
    resp = http_requests.post(f"{host}/api/2.0/genie/spaces/{GENIE_SPACE_ID}/start-conversation",
        headers={**hdrs, "Content-Type": "application/json"},
        json={"content": q}, timeout=60)
    if resp.status_code != 200:
        return {"error": f"Genie start failed: {resp.status_code}"}
    data = resp.json()
    conv_id = data.get("conversation_id")
    msg_id = data.get("message_id")
    # Poll
    for _ in range(20):
        r2 = http_requests.get(
            f"{host}/api/2.0/genie/spaces/{GENIE_SPACE_ID}/conversations/{conv_id}/messages/{msg_id}",
            headers=hdrs, timeout=30)
        if r2.status_code == 200:
            msg = r2.json()
            if msg.get("status") in ("COMPLETED", "FAILED"):
                atts = msg.get("attachments", [])
                answer = ""
                for att in atts:
                    if att.get("text"):
                        answer = att["text"].get("content", "")
                return {"answer": answer, "status": msg["status"]}
        time.sleep(3)
    return {"error": "timeout"}


@app.get("/api/decision")
def get_decision():
    """Compute hedge recommendation via UC functions + LLM narrative."""
    hedge_rows = _sql_query(
        "SELECT serverless_stable_ob2uyb_catalog.fe_bar_spike.hedge_size('CRUDE') AS hedge_bbl")
    hedge_bbl = int(hedge_rows[0]["hedge_bbl"]) if hedge_rows else 0
    
    util_rows = _sql_query(
        f"SELECT serverless_stable_ob2uyb_catalog.fe_bar_spike.post_action_util('CRUDE', {hedge_bbl}) AS post_util")
    post_util = float(util_rows[0]["post_util"]) if util_rows else 0
    
    risk_rows = _sql_query(
        "SELECT * FROM serverless_stable_ob2uyb_catalog.fe_bar_spike.desk_risk_mv WHERE sub_book = 'CRUDE'")
    current_util = float(risk_rows[0]["limit_utilisation"]) if risk_rows else 0
    var_usd = float(risk_rows[0]["var_95_usd"]) if risk_rows else 0
    
    reroute_rows = _sql_query(
        "SELECT * FROM serverless_stable_ob2uyb_catalog.fe_bar_spike.reroute_econ('CARGO-1005', 'Rotterdam')")
    
    # LLM narrative (3 sentences, numbers only from above)
    w = _sdk()
    host = w.config.host
    hdrs = _headers()
    prompt = (f"Write exactly 3 sentences for an oil desk trader. Use ONLY these numbers: "
              f"Current CRUDE VaR = ${var_usd:,.0f}, limit util = {current_util:.2f}x (BREACH). "
              f"Recommended hedge = {hedge_bbl:,} bbl, which brings util to {post_util:.2f}x. "
              f"Do NOT invent any numbers. State the breach, the recommended action, and the outcome.")
    llm_resp = http_requests.post(f"{host}/serving-endpoints/{LLM_ENDPOINT}/invocations",
        headers={**hdrs, "Content-Type": "application/json"},
        json={"messages": [{"role": "user", "content": prompt}], "max_tokens": 200},
        timeout=30)
    narrative = ""
    if llm_resp.status_code == 200:
        choices = llm_resp.json().get("choices", [])
        if choices:
            narrative = choices[0].get("message", {}).get("content", "")
    
    return {
        "hedge_bbl": hedge_bbl,
        "current_util": current_util,
        "post_action_util": post_util,
        "var_95_usd": var_usd,
        "narrative": narrative,
        "reroute": reroute_rows[0] if reroute_rows else {},
        "banner": "Recommends only \u2014 ETRM executes.",
    }


@app.post("/api/decision/approve")
def approve_decision(action: str = "APPROVE"):
    """Write to decision_audit."""
    decision_id = str(uuid.uuid4())
    w = _sdk()
    who = w.current_user.me().user_name
    payload = json.dumps({"action": action, "ts": time.time()})
    payload_hash = hashlib.sha256(payload.encode()).hexdigest()[:16]
    _lakebase_write(
        "INSERT INTO fe_bar_chain.decision_audit (decision_id, action, who, payload_hash) "
        "VALUES (%s, %s, %s, %s)",
        (decision_id, action, who, payload_hash))
    return {"decision_id": decision_id, "action": action, "who": who}


# ════════════════ HTML PAGE ════════════════

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"><title>North Sea Storm Desk — Physical Oil</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: #0f1117; color: #e0e0e0; padding: 24px 28px 40px; max-width: 1280px; margin: 0 auto; }
    h1 { color: #fff; font-size: 26px; }
    h2 { color: #fff; font-size: 17px; margin-bottom: 4px; }
    .eyebrow { color: #8ab4f8; font-size: 12px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; }
    .sub { color: #9aa0a6; font-size: 13px; margin-top: 4px; }
    .hero { background: linear-gradient(135deg, #16213a 0%, #1a1d27 70%); border: 1px solid #2a3550;
            border-radius: 10px; padding: 24px; margin: 18px 0; }
    .hero .headline { font-size: 24px; font-weight: 700; color: #fff; margin: 8px 0 10px; line-height: 1.3; }
    .hero .valueprop { font-size: 15px; color: #cfd6e4; line-height: 1.55; max-width: 900px; }
    .kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 18px; }
    .kpi { background: #11141c; border: 1px solid #2a2d37; border-radius: 8px; padding: 14px; }
    .kpi .label { color: #9aa0a6; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; }
    .kpi .value { font-size: 22px; font-weight: 700; color: #fff; margin: 6px 0 2px; }
    .kpi .value .from { color: #ff8a80; }
    .kpi .value .to { color: #69f0ae; }
    .kpi .note { color: #8a8f98; font-size: 12px; line-height: 1.4; }
    .pillars { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 0 0 22px; }
    .pillar { background: #1a1d27; border: 1px solid #2a2d37; border-radius: 8px; padding: 14px; }
    .pillar b { color: #fff; display: block; margin-bottom: 4px; }
    .pillar p { color: #b0b6c0; font-size: 13px; line-height: 1.5; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
    .card { background: #1a1d27; border-radius: 10px; padding: 18px; border: 1px solid #2a2d37; }
    .card .why { color: #9aa0a6; font-size: 13px; margin: 2px 0 12px; line-height: 1.45; }
    .takeaway { background: #11141c; border-left: 3px solid #8ab4f8; padding: 10px 12px; border-radius: 4px;
                margin: 10px 0; font-size: 14px; color: #e8eaed; line-height: 1.45; }
    .takeaway.bad { border-left-color: #f44336; }
    .takeaway.good { border-left-color: #4caf50; }
    .btn { background: #1a73e8; color: #fff; border: none; padding: 10px 18px;
           border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 600; margin: 4px 4px 4px 0; }
    .btn:hover { background: #1557b0; }
    .btn:disabled { opacity: 0.6; cursor: wait; }
    .btn-approve { background: #2e7d32; }
    .btn-decline { background: #c62828; }
    .bar { height: 10px; border-radius: 5px; margin: 6px 0; background: #2a2d37; }
    .bar-fill { height: 100%; border-radius: 5px; }
    table { width: 100%; border-collapse: collapse; margin: 6px 0; font-size: 14px; }
    th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid #2a2d37; }
    th { color: #8ab4f8; font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }
    .bad-text { color: #ff8a80; font-weight: 700; }
    .ok-text { color: #69f0ae; }
    #narrative { font-style: italic; color: #cfd6e4; margin: 10px 0; line-height: 1.5; }
    .banner { background: #2a2416; color: #ffb74d; padding: 8px 14px; border-radius: 6px;
              margin: 10px 0; font-weight: 600; font-size: 13px; }
    #genie-input { width: 72%; padding: 9px; background: #11141c; border: 1px solid #2a2d37;
                   color: #e0e0e0; border-radius: 6px; }
    #genie-answer { margin-top: 10px; padding: 12px; background: #11141c; border-radius: 6px;
                    min-height: 40px; white-space: pre-wrap; font-size: 14px; line-height: 1.5; }
    .state { display: inline-block; padding: 3px 9px; border-radius: 4px; font-weight: 700;
             letter-spacing: 0.04em; font-size: 11px; margin-right: 6px; }
    .state-idle { background: #2a2d37; color: #aaa; }
    .state-run { background: #1a3a5c; color: #8ab4f8; }
    .state-ok { background: #14351c; color: #69f0ae; }
    .state-fail { background: #3a1212; color: #ff8a80; }
    .muted { color: #8a8f98; font-size: 12px; }
    details { margin-top: 10px; }
    summary { cursor: pointer; color: #8ab4f8; font-size: 12px; }
    .tech { font-size: 12px; color: #9aa0a6; line-height: 1.6; margin-top: 6px; }
    .footer { margin-top: 20px; padding: 14px; border-top: 1px solid #2a2d37; color: #8a8f98; font-size: 12px; line-height: 1.6; }
    .chips span { display: inline-block; background: #11141c; border: 1px solid #2a2d37; border-radius: 12px;
                  padding: 2px 10px; margin: 2px 4px 2px 0; color: #cfd6e4; font-size: 12px; }
    .flow-wrap { background: #1a1d27; border: 1px solid #2a2d37; border-radius: 10px; padding: 18px 18px 14px; margin: 0 0 22px; }
    .flow-wrap h2 { margin-bottom: 6px; }
    .flow-lede { color: #cfd6e4; font-size: 14px; line-height: 1.5; max-width: 980px; margin-bottom: 14px; }
    .flow-compare { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    .lane { border-radius: 8px; padding: 12px; }
    .lane.today { background: #1c1414; border: 1px solid #3a2222; }
    .lane.now { background: #121c16; border: 1px solid #1e3a28; }
    .lane-head { font-weight: 700; font-size: 13px; margin-bottom: 10px; letter-spacing: 0.02em; }
    .lane.today .lane-head { color: #ff8a80; }
    .lane.now .lane-head { color: #69f0ae; }
    .steps { display: flex; flex-wrap: wrap; gap: 6px; align-items: stretch; }
    .hop { background: #11141c; border: 1px solid #2a2d37; border-radius: 6px; padding: 8px 10px; min-width: 108px; flex: 1 1 108px; }
    .hop .n { display: block; font-size: 10px; font-weight: 700; letter-spacing: 0.06em; color: #8a8f98; margin-bottom: 3px; }
    .hop .t { display: block; font-size: 12px; color: #e8eaed; line-height: 1.3; }
    .hop .d { display: block; font-size: 11px; color: #8a8f98; margin-top: 3px; }
    .lane.now .hop.live { border-color: #4caf50; box-shadow: 0 0 0 1px #4caf50; }
    .lane-end { margin-top: 10px; font-size: 13px; font-weight: 600; padding: 8px 10px; border-radius: 6px; }
    .lane-end.bad { background: #2a1414; color: #ff8a80; }
    .lane-end.good { background: #14351c; color: #69f0ae; }
    .flow-caption { margin-top: 12px; color: #9aa0a6; font-size: 12px; line-height: 1.5; }
    @media (max-width: 900px) {
      .flow-compare, .kpis, .pillars, .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="eyebrow">Trafigura · Physical Oil &amp; Petroleum Products desk · synthetic illustrative book</div>
  <h1>North Sea Storm Desk</h1>
  <div class="sub">When the weather moves the market, the desk knows its exposure in seconds and has a hedge ready to approve.</div>

  <div class="hero">
    <div class="eyebrow">Business outcome</div>
    <div class="headline">Get Crude back inside its risk limit in seconds, not hours.</div>
    <div class="valueprop">
      A North Sea storm has pushed the Crude book <b id="hero-util">2.11×</b> over its VaR limit.
      Today the desk rebuilds cover, VaR and P&amp;L by hand. That takes about 45 minutes per weather event, and the desk is trading blind while it happens.
      This desk reprices the whole chain the moment the storm data lands. It recommends the hedge that brings Crude back to <b id="hero-post">1.00×</b>,
      and every number traces back to governed data. <b>The desk decides. ETRM executes.</b>
    </div>
    <div class="kpis">
      <div class="kpi">
        <div class="label">Crude limit utilisation</div>
        <div class="value"><span class="from" id="k-util">2.11×</span> → <span class="to" id="k-post">1.00×</span></div>
        <div class="note">Breach today → compliant after the recommended hedge</div>
      </div>
      <div class="kpi">
        <div class="label">VaR over limit</div>
        <div class="value"><span class="from" id="k-excess">$4.45M</span> → <span class="to">$0</span></div>
        <div class="note" id="k-excess-note">Crude VaR $8.45M vs $4.0M limit</div>
      </div>
      <div class="kpi">
        <div class="label">Time to reprice after a storm</div>
        <div class="value"><span class="from">~45 min</span> → <span class="to" id="k-time">&lt;1 s</span></div>
        <div class="note" id="k-time-note">Manual rebuild today (desk estimate) vs live chain</div>
      </div>
      <div class="kpi">
        <div class="label">MTD P&amp;L explained</div>
        <div class="value" id="k-pnl">$1.25M</div>
        <div class="note" id="k-pnl-note">Split by flat price, crack and freight</div>
      </div>
    </div>
  </div>

  <div class="pillars">
    <div class="pillar"><b>Protect the limit</b><p>Breaches are caught and sized the moment the weather changes. The desk no longer waits for the next risk run.</p></div>
    <div class="pillar"><b>Decide faster</b><p>Weather, cover, VaR and P&amp;L run as one chain. The hedge and the reroute economics are ready before the trader asks.</p></div>
    <div class="pillar"><b>Trust every number</b><p>Numbers come only from governed metric views and deterministic functions. AI explains them; it never invents them. Every decision is audited.</p></div>
  </div>

  <div class="flow-wrap">
    <div class="eyebrow">The operating change</div>
    <h2>Same North Sea storm. Two ways the desk works.</h2>
    <div class="flow-lede">
      The business value is not a faster chart. It is that after weather moves the market, the desk
      <b>stops trading blind</b>. Today a storm means ~45 minutes of spreadsheets while Crude sits 2.11× over its limit.
      On this desk the same event is ingested, repriced, explained and sized into a hedge the trader can approve — inside a 5-second budget (last live run updates the green lane).
    </div>
    <div class="flow-compare">
      <div class="lane today">
        <div class="lane-head">TODAY — ~45 minutes · desk is blind</div>
        <div class="steps">
          <div class="hop"><span class="n">1</span><span class="t">Storm alert on phone / email</span></div>
          <div class="hop"><span class="n">2</span><span class="t">Pull weather, AIS, inventory into Excel</span></div>
          <div class="hop"><span class="n">3</span><span class="t">Rebuild days of cover by hand</span></div>
          <div class="hop"><span class="n">4</span><span class="t">Re-run VaR in a batch / local model</span></div>
          <div class="hop"><span class="n">5</span><span class="t">Check limits in a second system</span></div>
          <div class="hop"><span class="n">6</span><span class="t">Trader guesses a hedge size</span></div>
          <div class="hop"><span class="n">7</span><span class="t">Risk signs off later</span></div>
          <div class="hop"><span class="n">8</span><span class="t">Ops books the trade in ETRM</span></div>
        </div>
        <div class="lane-end bad">Outcome: hedge lands after the move. Exposure sits unpriced for ~45 min. No audit of why the size was chosen.</div>
      </div>
      <div class="lane now">
        <div class="lane-head">THIS DESK — seconds · desk is current</div>
        <div class="steps" id="live-hops">
          <div class="hop" data-hop="ingest"><span class="n">1</span><span class="t">Storm reading lands</span><span class="d">Lakeflow + live trigger</span></div>
          <div class="hop" data-hop="m1"><span class="n">2</span><span class="t">Weather → days of cover</span><span class="d">M1, warm model</span></div>
          <div class="hop" data-hop="m2"><span class="n">3</span><span class="t">Cover → VaR change</span><span class="d">M2 · this hop is the increment, not book VaR</span></div>
          <div class="hop" data-hop="m3"><span class="n">4</span><span class="t">VaR → limit utilisation</span><span class="d">M3 · is Crude still in breach?</span></div>
          <div class="hop" data-hop="views"><span class="n">5</span><span class="t">Breach + P&amp;L by leg</span><span class="d">Governed metric views</span></div>
          <div class="hop" data-hop="hedge"><span class="n">6</span><span class="t">Hedge + reroute sized</span><span class="d">UC functions, not the LLM</span></div>
          <div class="hop" data-hop="ask"><span class="n">7</span><span class="t">Ask why, in English</span><span class="d">Genie, same numbers</span></div>
          <div class="hop" data-hop="approve"><span class="n">8</span><span class="t">Trader approves</span><span class="d">Audit written · ETRM still executes</span></div>
        </div>
        <div class="lane-end good" id="live-end">Outcome: Crude can be put back inside the limit while the storm is still in the tape. Every number is governed. Every decision is audited.</div>
      </div>
    </div>
    <div class="flow-caption">
      Press <b>Run storm reprice</b> below to fire steps 1–4 live. Then <b>Get recommendation</b> for step 6 and <b>Ask the desk</b> for step 7.
      The −$3 (or similar) on the reprice card is the model increment from this weather reading — not the $8.45M book VaR in Step 1.
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <div class="eyebrow">Step 1 · The situation</div>
      <h2>Crude is in breach and P&amp;L needs explaining</h2>
      <div class="why">Where the desk stands right now, from governed metric views.</div>
      <div id="situation-takeaway" class="takeaway bad">Loading the book…</div>
      <div id="risk-table"></div>
      <div id="pnl-table"></div>
    </div>

    <div class="card">
      <div class="eyebrow">Step 2 · The storm hits</div>
      <h2>Reprice the book on fresh weather</h2>
      <div class="why">One click sends a new North Sea weather reading through the chain: weather → days of cover → VaR → limit. It has a 5-second budget.</div>
      <button class="btn" id="chain-btn" onclick="triggerChain()">Run storm reprice</button>
      <div id="chain-result">
        <div class="takeaway"><span class="state state-idle">IDLE</span>Not started. Press the button. You will see RUNNING, then COMPLETE.</div>
      </div>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <div class="eyebrow">Step 3 · The decision</div>
      <h2>Hedge recommendation to approve</h2>
      <div class="why">Sized by deterministic Unity Catalog functions. AI writes the summary from those numbers only.</div>
      <button class="btn" id="decision-btn" onclick="loadDecision()">Get recommendation</button>
      <div id="decision-result"></div>
    </div>

    <div class="card">
      <div class="eyebrow">Step 4 · Ask the desk</div>
      <h2>Ask anything about the book, in plain English</h2>
      <div class="why">Genie answers from the same governed views, so it gives the same numbers as the tables.</div>
      <input id="genie-input" placeholder="e.g. Why is Crude in breach and how much do we need to hedge?"
             onkeypress="if(event.key==='Enter')askGenie()">
      <button class="btn" onclick="askGenie()">Ask</button>
      <div id="genie-answer" class="muted">Try: "Which leg drives MTD P&amp;L?" or "Which books are in breach?"</div>
    </div>
  </div>

  <div class="footer">
    <div class="chips"><b style="color:#cfd6e4">How it works:</b>
      <span>Lakeflow ingests weather, prices, AIS, inventory</span>
      <span>Unity Catalog governs</span>
      <span>Lakebase serves in milliseconds</span>
      <span>M1→M2→M3 models stay warm in the app</span>
      <span>Genie answers questions</span>
      <span>This app is where the desk decides</span>
    </div>
    <div style="margin-top:8px">Recommends only. The ETRM system of record executes trades. All data is synthetic and illustrative.</div>
  </div>

  <script>
    const fmtUSD = (n) => {
      const a = Math.abs(n);
      const s = a >= 1e6 ? (a / 1e6).toFixed(2) + 'M' : a >= 1e3 ? (a / 1e3).toFixed(0) + 'K' : a.toFixed(0);
      return (n < 0 ? '-$' : '$') + s;
    };
    const fmtX = (n) => Number(n).toFixed(2) + '×';

    async function loadOutcome() {
      try {
        const r = await fetch('/api/outcome');
        const o = await r.json();
        if (o.crude_util) {
          document.getElementById('k-util').textContent = fmtX(o.crude_util);
          document.getElementById('hero-util').textContent = fmtX(o.crude_util);
        }
        if (o.post_util) {
          document.getElementById('k-post').textContent = fmtX(o.post_util);
          document.getElementById('hero-post').textContent = fmtX(o.post_util);
        }
        if (o.crude_var_usd && o.crude_limit_usd) {
          const excess = Math.max(0, o.crude_var_usd - o.crude_limit_usd);
          document.getElementById('k-excess').textContent = fmtUSD(excess);
          document.getElementById('k-excess-note').textContent =
            `Crude VaR ${fmtUSD(o.crude_var_usd)} vs ${fmtUSD(o.crude_limit_usd)} limit. Hedge ${Number(o.hedge_bbl).toLocaleString()} bbl closes it.`;
        }
        if (o.pnl && o.pnl.length) {
          const total = o.pnl.reduce((s, p) => s + p.mtd_usd, 0);
          const top = o.pnl.slice().sort((a, b) => b.mtd_usd - a.mtd_usd)[0];
          document.getElementById('k-pnl').textContent = fmtUSD(total);
          document.getElementById('k-pnl-note').textContent =
            `${top.leg.replace('_', ' ')} drives ${Math.round(100 * top.mtd_usd / total)}% of MTD P&L`;
        }
      } catch (e) { /* keep defaults */ }
    }

    async function loadRisk() {
      const [riskR, pnlR] = await Promise.all([fetch('/api/risk'), fetch('/api/pnl')]);
      const risk = await riskR.json();
      const pnl = await pnlR.json();
      let rhtml = '<table><tr><th>Book</th><th>VaR 95</th><th>Limit</th><th>Utilisation</th><th>Status</th></tr>';
      let breach = null;
      for (const r of risk.risk) {
        const u = parseFloat(r.limit_utilisation);
        const cls = u > 1 ? 'bad-text' : 'ok-text';
        if (u > 1) breach = r;
        rhtml += `<tr><td>${r.sub_book}</td><td>${fmtUSD(Number(r.var_95_usd))}</td>`;
        rhtml += `<td>${fmtUSD(Number(r.limit_usd))}</td>`;
        rhtml += `<td class="${cls}">${fmtX(u)}</td><td class="${cls}">${r.limit_status}</td></tr>`;
      }
      rhtml += '</table>';
      document.getElementById('risk-table').innerHTML = rhtml;

      const total = pnl.pnl.reduce((s, p) => s + Number(p.mtd_pnl_usd), 0);
      let phtml = '<table><tr><th>P&amp;L leg</th><th>MTD</th><th>Share</th></tr>';
      let top = null;
      for (const p of pnl.pnl) {
        const v = Number(p.mtd_pnl_usd);
        if (!top || v > Number(top.mtd_pnl_usd)) top = p;
        phtml += `<tr><td>${p.leg_type.replace('_', ' ')}</td><td>${fmtUSD(v)}</td><td>${Math.round(100 * v / total)}%</td></tr>`;
      }
      phtml += '</table>';
      document.getElementById('pnl-table').innerHTML = phtml;

      const viewsHop = document.querySelector('#live-hops .hop[data-hop="views"]');
      if (viewsHop) viewsHop.classList.add('live');
      const t = document.getElementById('situation-takeaway');
      if (breach) {
        t.innerHTML = `<b>${breach.sub_book} is ${fmtX(breach.limit_utilisation)} its VaR limit</b>, which is ${fmtUSD(Number(breach.var_95_usd) - Number(breach.limit_usd))} over. ` +
          `MTD P&amp;L is ${fmtUSD(total)}, and <b>${top.leg_type.replace('_', ' ')}</b> drives ${Math.round(100 * Number(top.mtd_pnl_usd) / total)}% of it.`;
      } else {
        t.className = 'takeaway good';
        t.innerHTML = `All books are within limit. MTD P&amp;L is ${fmtUSD(total)}.`;
      }
    }

    async function triggerChain() {
      const btn = document.getElementById('chain-btn');
      btn.disabled = true;
      document.querySelectorAll('#live-hops .hop').forEach(h => h.classList.remove('live'));
      ['ingest','m1','m2','m3'].forEach(id => {
        const el = document.querySelector('#live-hops .hop[data-hop="'+id+'"]');
        if (el) el.classList.add('live');
      });
      document.getElementById('live-end').textContent = 'RUNNING — weather is moving through M1 → M2 → M3. Wait for COMPLETE on the card to the right.';
      document.getElementById('chain-result').innerHTML =
        '<div class="takeaway"><span class="state state-run">RUNNING</span>Repricing on the new weather reading. It is not finished until you see COMPLETE. This is steps 1–4 of the green lane.</div>';
      try {
        const r = await fetch('/api/trigger');
        const d = await r.json();
        const ok = d.status === 200 && d.body && d.body.run_id && !d.body.error;
        if (!ok) {
          document.getElementById('chain-result').innerHTML =
            `<div class="takeaway bad"><span class="state state-fail">FAILED</span>The reprice did not complete (HTTP ${d.status}).</div>` +
            `<p class="muted">${(d.body && (d.body.error || JSON.stringify(d.body))) || ''}</p>`;
          return;
        }
        const b = d.body, m1 = b.m1 || {}, m2 = b.m2 || {}, m3 = b.m3 || {};
        const ms = b.total_ms, budget = d.budget_ms || 5000;
        const secs = (ms / 1000).toFixed(2);
        const pct = Math.min(100, (ms / budget) * 100);
        document.getElementById('live-end').innerHTML =
          `COMPLETE — steps 1–4 just ran in <b>${secs} s</b>. Today that spreadsheet rebuild is ~45 minutes, and the desk is blind for all of it. Next: Get recommendation (step 6).`;
        let html = `<div class="takeaway good"><span class="state state-ok">COMPLETE</span>` +
          `<b>Book repriced in ${secs} s</b>. That replaced today's ~45 min Excel rebuild (red lane, steps 2–5). The desk is no longer blind.</div>`;
        html += '<table>';
        html += `<tr><td>Supply cover after the storm</td><td><b>${Number(m1.days_of_cover).toFixed(1)} days</b></td></tr>`;
        html += `<tr><td>Change in VaR from this reading</td><td><b>${fmtUSD(Number(m2.var_delta_usd))}</b></td></tr>`;
        if (m3.limit_util !== undefined) html += `<tr><td>Crude limit utilisation</td><td><b>${fmtX(m3.limit_util)}</b></td></tr>`;
        html += '</table>';
        html += `<div class="bar"><div class="bar-fill" style="width:${Math.max(pct, 1.5)}%;background:#4caf50"></div></div>`;
        html += `<div class="muted">${ms} ms used of the 5,000 ms budget (${pct.toFixed(0)}%)</div>`;
        html += `<details><summary>Technical detail</summary><div class="tech">` +
          `M1 weather→cover ${m1.latency_ms} ms · M2 cover→VaR ${m2.latency_ms} ms` +
          (m3.latency_ms !== undefined ? ` · M3 VaR→limit ${m3.latency_ms} ms` : '') +
          `<br>Chain compute incl. Lakebase writes ${ms} ms · door-to-door HTTP incl. auth ${d.wall_ms} ms<br>Run ${b.run_id}</div></details>`;
        document.getElementById('chain-result').innerHTML = html;
        document.getElementById('k-time').textContent = secs + ' s';
        document.getElementById('k-time-note').textContent = 'Manual rebuild today (desk estimate) vs the last live run';
      } catch (e) {
        document.getElementById('chain-result').innerHTML =
          `<div class="takeaway bad"><span class="state state-fail">FAILED</span>${e}</div>`;
      } finally {
        btn.disabled = false;
      }
    }

    async function askGenie() {
      const q = document.getElementById('genie-input').value;
      if (!q) return;
      const el = document.getElementById('genie-answer');
      el.className = '';
      const askHop = document.querySelector('#live-hops .hop[data-hop="ask"]');
      if (askHop) askHop.classList.add('live');
      el.innerHTML = '<span class="state state-run">THINKING</span>Genie is querying the governed views… (step 7 of the green lane)';
      const r = await fetch('/api/ask?q=' + encodeURIComponent(q));
      const d = await r.json();
      if (d.error && String(d.error).includes('403')) {
        el.innerHTML = '<span class="state state-fail">NO ACCESS</span>The app is not yet allowed to use this Genie space (needs CAN_RUN).';
      } else {
        el.textContent = d.answer || d.error || 'No answer';
      }
    }

    async function loadDecision() {
      const btn = document.getElementById('decision-btn');
      btn.disabled = true;
      const hedgeHop = document.querySelector('#live-hops .hop[data-hop="hedge"]');
      if (hedgeHop) hedgeHop.classList.add('live');
      document.getElementById('decision-result').innerHTML =
        '<div class="takeaway"><span class="state state-run">LOADING</span>Sizing the hedge and writing the summary. Wait for COMPLETE. This is step 6 of the green lane.</div>';
      try {
        const r = await fetch('/api/decision');
        const d = await r.json();
        if (d.error) {
          document.getElementById('decision-result').innerHTML =
            `<div class="takeaway bad"><span class="state state-fail">FAILED</span>${d.error}</div>`;
          return;
        }
        const excess = Math.max(0, d.var_95_usd - d.var_95_usd / d.current_util);
        let html = `<div class="takeaway good"><span class="state state-ok">COMPLETE</span>` +
          `<b>Sell ${d.hedge_bbl.toLocaleString()} bbl of Crude</b> to take utilisation from ` +
          `<span class="bad-text">${fmtX(d.current_util)}</span> to <span class="ok-text">${fmtX(d.post_action_util)}</span>, ` +
          `bringing ${fmtUSD(excess)} of VaR back inside the limit.</div>`;
        if (d.reroute && d.reroute.cargo_id) {
          html += `<div class="takeaway">Cargo ${d.reroute.cargo_id} → ${d.reroute.alt_port}: ` +
            `ETA ${d.reroute.delta_eta_days > 0 ? '+' : ''}${d.reroute.delta_eta_days} days, cost ${fmtUSD(Number(d.reroute.delta_cost_usd))}. ` +
            `<b>${d.reroute.recommendation}</b></div>`;
        }
        if (d.narrative) html += `<div id="narrative">${d.narrative}</div>`;
        html += `<div class="banner">${d.banner} Approving records the decision; it does not place a trade.</div>`;
        html += `<button class="btn btn-approve" onclick="decide('APPROVE')">Approve hedge</button>`;
        html += `<button class="btn btn-decline" onclick="decide('DECLINE')">Decline</button>`;
        html += `<div id="decision-ack"></div>`;
        document.getElementById('decision-result').innerHTML = html;
      } finally {
        btn.disabled = false;
      }
    }

    async function decide(action) {
      const r = await fetch('/api/decision/approve?action=' + action, {method: 'POST'});
      const d = await r.json();
      const approveHop = document.querySelector('#live-hops .hop[data-hop="approve"]');
      if (approveHop) approveHop.classList.add('live');
      document.getElementById('decision-ack').innerHTML =
        `<div class="takeaway ${action === 'APPROVE' ? 'good' : 'bad'}"><span class="state ${action === 'APPROVE' ? 'state-ok' : 'state-fail'}">${d.action}</span>` +
        `Recorded in the audit trail by ${d.who} (decision ${String(d.decision_id).slice(0, 8)}). Next step: book the trade in the ETRM.</div>`;
    }

    loadOutcome();
    loadRisk();
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML
