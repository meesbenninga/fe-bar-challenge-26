# AI Usage — FE Bar Build

## Tools Used

* **Cursor**: Problem framing, industry story, FEVM vs Azure decision, feasibility PRD iteration, and the one-shot implementation prompt.
* **Genie Code (Databricks Assistant)**: Primary build agent on the FEVM workspace. Executed the 9-step build from that prompt.
* **databricks-claude-opus-4-8**: LLM endpoint used in the oil desk decision card for 3-sentence hedge narrative. The LLM receives only pre-computed numbers and writes prose — it never computes VaR, hedge sizes, or P&L.

## Key Prompts

1. **One-shot build prompt**: A single structured prompt (STEP 1–9) drove the entire build. The prompt specified:
   * Operating rules (max 2 attempts per blocker, no secrets, do-not-touch list)
   * A single CHECKPOINT (STEP 2) for grants
   * Explicit "done when" criteria per step
   * Architecture constraints (warm Apps, Trigger.AvailableNow, local ray.init())

2. **Phase 0/1 iteration** (prior session): Iterative debugging of App-to-App OAuth (PAT vs JWT discovery, mlflow[databricks] dependency, Lakebase SP roles).

## Patterns

* **Evidence-driven**: Every step writes proof to Delta (http_evidence table) or Lakebase (control_metrics). The agent reads evidence back to verify success before proceeding.
* **Fail-forward with BLOCKERS**: When a grant is blocked by guardrails (Genie CAN_RUN, permissions API), the agent records it in BLOCKERS and continues rather than halting.
* **App-to-App as test harness**: fe-bar-producer exists solely to prove the OAuth M2M pattern. It mints its own JWT and calls other apps, proving the auth chain that a browser user cannot test from executeCode.
* **Calibrated synthetic data**: Numbers are planted (CRUDE util=2.11, hedge brings to 1.00) to tell the business story. UC functions are deterministic SQL that produce exact results.

## What the LLM Does NOT Do

* Does not compute VaR, P&L, hedge sizes, or utilisation — all from SQL metric views or UC functions.
* Does not access production data — all data is synthetic.
* Does not create OAuth secrets or credentials — platform-injected only.
