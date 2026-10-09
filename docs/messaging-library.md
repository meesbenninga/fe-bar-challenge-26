# FE Bar — Messaging library (talk track)

Locked lines for Slack, manager, and roleplay. Do not reopen unless Mees says rewrite.
The 45 min is the **manual rebuild**, not model inference. Do not say we made MLflow faster.

---

## Problem

After a market move, traders rebuild their risk numbers by hand. That takes ~45 min. While they do it they don't know if they're over their limit or what to do. They're flying blind.

## What

Not one giant job, and not a single model endpoint. Three small apps that pass work to each other.

1. Something happens in the world (weather, price, whatever) and an app sends that event in.
2. A second app already has the models loaded. Model 1 finishes, that result kicks model 2, then 3 (some run one after another, some in parallel). Results land in a fast database, governed in the catalog.
3. A third app is the desk: you're over the limit, here's the hedge, approve it. Trader decides. Their trade system still books it.

## Why

Not just Model Serving / MLflow? The models were never the slow bit — they already answer in milliseconds. Serving scores one model. This problem is a chain (2 can't start until 1 is done) plus a live decision after. Serving doesn't do that. The Lucid's pipeline-per-model version is the right chain but too slow (each hop starts a job). Always-on apps keep the chain warm so the whole thing, not one score, comes back in ~0.2s.

## Outcome

A ~45 min flying-blind window becomes under a second. Same control, just in time to act.

And it's reusable: weather, wave height, prices, any real-time stream that feeds predictive models can run on this. That's the operating pattern — chain + live decision after — not "we made models faster."

---

## Slack (short)

Hey — FE Bar prototype: took the Lucid chained-app idea and applied it to energy trading.

Traders currently rebuild risk by hand after a market move (~45 min, flying blind). We split it across three always-on apps: event in → models kick each other in the right order → desk sees the limit breach and a hedge to approve.

Not Model Serving — that scores one model. This is a chain plus a live decision. Whole thing ~0.2s.

Reusable for weather, waves, prices, any live stream. Same control, just in time to act.
