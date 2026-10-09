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
  <meta charset="utf-8"><title>FE Bar — Oil Desk</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: #0f1117; color: #e0e0e0; padding: 20px; }
    h1 { color: #fff; margin-bottom: 20px; }
    h2 { color: #8ab4f8; margin: 16px 0 8px; font-size: 1.1em; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }
    .card { background: #1a1d27; border-radius: 8px; padding: 16px; border: 1px solid #2a2d37; }
    .breach { border-color: #f44336; background: #1a1015; }
    .ok { border-color: #4caf50; }
    .btn { background: #1a73e8; color: #fff; border: none; padding: 10px 20px;
           border-radius: 4px; cursor: pointer; font-size: 14px; margin: 4px; }
    .btn:hover { background: #1557b0; }
    .btn-approve { background: #4caf50; }
    .btn-decline { background: #f44336; }
    .bar { height: 24px; border-radius: 4px; margin: 4px 0; }
    .bar-fill { height: 100%; border-radius: 4px; }
    table { width: 100%; border-collapse: collapse; margin: 8px 0; }
    th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #2a2d37; }
    th { color: #8ab4f8; }
    .highlight { color: #f44336; font-weight: bold; }
    .ok-text { color: #4caf50; }
    #narrative { font-style: italic; color: #ccc; margin: 8px 0; }
    .banner { background: #333; color: #ffa726; padding: 8px 16px; border-radius: 4px;
              text-align: center; margin: 12px 0; font-weight: bold; }
    #genie-input { width: 70%; padding: 8px; background: #1a1d27; border: 1px solid #2a2d37;
                   color: #e0e0e0; border-radius: 4px; }
    #genie-answer { margin-top: 8px; padding: 12px; background: #1a1d27; border-radius: 4px;
                    min-height: 40px; white-space: pre-wrap; }
    .loading { color: #8ab4f8; }
    .state { display: inline-block; padding: 4px 10px; border-radius: 4px; font-weight: 700; letter-spacing: 0.04em; font-size: 12px; }
    .state-idle { background: #2a2d37; color: #aaa; }
    .state-run { background: #1a3a5c; color: #8ab4f8; }
    .state-ok { background: #14351c; color: #69f0ae; }
    .state-fail { background: #3a1212; color: #ff8a80; }
    .metric { margin: 8px 0; line-height: 1.45; }
    .metric b { color: #fff; }
    .muted { color: #888; font-size: 12px; }
  </style>
</head>
<body>
  <h1>FE Bar — Trafigura Physical Oil Desk</h1>
  <div class="grid">
    <div class="card" id="chain-card">
      <h2>1. Live Chain</h2>
      <p class="muted">Reprices North Sea Brent after a metocean tick. Clock starts when you press the button.</p>
      <button class="btn" id="chain-btn" onclick="triggerChain()">Run reprice (M1 → M2 → M3)</button>
      <div id="chain-result">
        <p><span class="state state-idle">IDLE</span> Not started. Press the button — you will see RUNNING, then COMPLETE or FAILED.</p>
      </div>
    </div>
    <div class="card" id="risk-card">
      <h2>2. Risk &amp; P&amp;L</h2>
      <div id="risk-table"></div>
      <div id="pnl-table"></div>
    </div>
    <div class="card">
      <h2>3. Ask the Desk</h2>
      <input id="genie-input" placeholder="e.g. What is the CRUDE limit utilisation?"
             onkeypress="if(event.key==='Enter')askGenie()">
      <button class="btn" onclick="askGenie()">Ask</button>
      <div id="genie-answer"></div>
    </div>
    <div class="card" id="decision-card">
      <h2>4. Decision Card</h2>
      <button class="btn" onclick="loadDecision()">Load Recommendation</button>
      <div id="decision-result"></div>
    </div>
  </div>

  <script>
    async function triggerChain() {
      const btn = document.getElementById('chain-btn');
      btn.disabled = true;
      document.getElementById('chain-result').innerHTML =
        '<p><span class="state state-run">RUNNING</span> Calling the model chain. Not finished until you see COMPLETE.</p>';
      try {
        const r = await fetch('/api/trigger');
        const d = await r.json();
        const ok = d.status === 200 && d.body && d.body.run_id && !d.body.error;
        if (!ok) {
          document.getElementById('chain-result').innerHTML =
            `<p><span class="state state-fail">FAILED</span> Chain did not complete (HTTP ${d.status}).</p>` +
            `<p class="muted">${(d.body && (d.body.error || JSON.stringify(d.body))) || 'No body'}</p>`;
          return;
        }
        const b = d.body;
        const chainMs = b.total_ms;
        const budget = d.budget_ms || 5000;
        const under = chainMs < budget;
        const m1 = b.m1 || {};
        const m2 = b.m2 || {};
        const m3 = b.m3 || {};
        const pct = Math.min(100, (chainMs / budget) * 100);
        const color = under ? '#4caf50' : '#f44336';
        let html = `<p><span class="state state-ok">COMPLETE</span> Chain finished. North Sea Brent reprice is done.</p>`;
        html += `<div class="metric"><b>M1 Metocean → days of cover:</b> ${Number(m1.days_of_cover).toFixed(2)} days <span class="muted">(${m1.latency_ms}ms)</span></div>`;
        html += `<div class="metric"><b>M2 VaR delta:</b> $${Number(m2.var_delta_usd).toFixed(2)} <span class="muted">(${m2.latency_ms}ms) — model increment, not the $8.45M book VaR in panel 2</span></div>`;
        if (m3.limit_util !== undefined) {
          html += `<div class="metric"><b>M3 limit utilisation:</b> ${m3.limit_util}x <span class="muted">(${m3.latency_ms}ms)</span></div>`;
        }
        html += `<div class="metric"><b>Budget:</b> ${chainMs}ms used of ${budget}ms — ${under ? 'UNDER BUDGET' : 'OVER BUDGET'} (${pct.toFixed(0)}%)</div>`;
        html += `<div class="bar" style="background:#2a2d37"><div class="bar-fill" style="width:${pct}%;background:${color}"></div></div>`;
        html += `<p class="muted">Door-to-door HTTP ${d.wall_ms}ms (includes auth). Chain compute ${chainMs}ms. Run ${b.run_id}</p>`;
        document.getElementById('chain-result').innerHTML = html;
      } catch (e) {
        document.getElementById('chain-result').innerHTML =
          `<p><span class="state state-fail">FAILED</span> ${e}</p>`;
      } finally {
        btn.disabled = false;
      }
    }

    async function loadRisk() {
      const [riskR, pnlR] = await Promise.all([fetch('/api/risk'), fetch('/api/pnl')]);
      const risk = await riskR.json();
      const pnl = await pnlR.json();
      let rhtml = '<table><tr><th>Book</th><th>VaR 95</th><th>Limit</th><th>Util</th><th>Status</th></tr>';
      for (const r of risk.risk) {
        const cls = parseFloat(r.limit_utilisation) > 1 ? 'highlight' : 'ok-text';
        rhtml += `<tr><td>${r.sub_book}</td><td>$${Number(r.var_95_usd).toLocaleString()}</td>`;
        rhtml += `<td>$${Number(r.limit_usd).toLocaleString()}</td>`;
        rhtml += `<td class="${cls}">${r.limit_utilisation}x</td>`;
        rhtml += `<td class="${cls}">${r.limit_status}</td></tr>`;
      }
      rhtml += '</table>';
      document.getElementById('risk-table').innerHTML = rhtml;

      let phtml = '<table><tr><th>Leg</th><th>MTD P&L</th><th>Days</th></tr>';
      for (const p of pnl.pnl) {
        phtml += `<tr><td>${p.leg_type}</td><td>$${Number(p.mtd_pnl_usd).toLocaleString()}</td>`;
        phtml += `<td>${p.trading_days}</td></tr>`;
      }
      phtml += '</table>';
      document.getElementById('pnl-table').innerHTML = phtml;
    }

    async function askGenie() {
      const q = document.getElementById('genie-input').value;
      if (!q) return;
      document.getElementById('genie-answer').innerHTML = '<span class="loading">Thinking...</span>';
      const r = await fetch('/api/ask?q=' + encodeURIComponent(q));
      const d = await r.json();
      document.getElementById('genie-answer').textContent = d.answer || d.error || 'No answer';
    }

    async function loadDecision() {
      document.getElementById('decision-result').innerHTML =
        '<p><span class="state state-run">LOADING</span> Computing hedge from UC functions, then a 3-sentence narrative. Wait for COMPLETE.</p>';
      const r = await fetch('/api/decision');
      const d = await r.json();
      if (d.error) {
        document.getElementById('decision-result').innerHTML =
          `<p><span class="state state-fail">FAILED</span> ${d.error}</p>`;
        return;
      }
      let html = `<p><span class="state state-ok">COMPLETE</span> Recommendation ready. Approve or decline — ETRM still executes.</p>`;
      html += `<div class="banner">${d.banner}</div>`;
      html += `<p>Current CRUDE util: <span class="highlight">${d.current_util}x (BREACH)</span></p>`;
      html += `<p>Hedge: <b>${d.hedge_bbl.toLocaleString()} bbl</b></p>`;
      html += `<p>Post-hedge util: <span class="ok-text">${d.post_action_util}x</span></p>`;
      html += `<p>VaR 95: $${d.var_95_usd.toLocaleString()}</p>`;
      if (d.reroute && d.reroute.cargo_id) {
        html += `<p>Reroute ${d.reroute.cargo_id} to ${d.reroute.alt_port}: `;
        html += `\u0394ETA=${d.reroute.delta_eta_days}d, \u0394cost=$${Number(d.reroute.delta_cost_usd).toLocaleString()}, `;
        html += `${d.reroute.recommendation}</p>`;
      }
      html += `<div id="narrative">${d.narrative}</div>`;
      html += `<button class="btn btn-approve" onclick="decide('APPROVE')">Approve</button>`;
      html += `<button class="btn btn-decline" onclick="decide('DECLINE')">Decline</button>`;
      document.getElementById('decision-result').innerHTML = html;
    }

    async function decide(action) {
      const r = await fetch('/api/decision/approve?action=' + action, {method: 'POST'});
      const d = await r.json();
      alert('Decision recorded: ' + d.decision_id + ' (' + d.action + ')');
    }

    // Auto-load risk on page load
    loadRisk();
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML
