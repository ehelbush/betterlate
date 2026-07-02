#!/usr/bin/env python3
"""Wharf to Wharf training tracker — tissue-led, from the Claud Chat brief.

Combines the static brief (Claud Chat/wharf-to-wharf-data.json: zones, injuries, rehab,
KPIs) with live training data:
  * jog-pace discipline   <- data/processed/w2w_runs.json (computed from Strava HR streams)
  * run volume / longest  <- the same runs + Strava export
  * manual rehab/readiness <- data/manual/w2w_log.csv (Achilles status, PT streak, ankle symmetry)
Writes data/processed/w2w.json, rendered as the dashboard's "Wharf to Wharf" tab.

The signature metric is jog-pace discipline: jogs must stay <=139 bpm (Zone 2). Average
session pace hides this because walk breaks drag it down, so we use per-run HR-stream data.
"""
import json, csv, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRIEF = json.loads((ROOT / "Claud Chat" / "wharf-to-wharf-data.json").read_text())
RUNS = json.loads((ROOT / "data" / "processed" / "w2w_runs.json").read_text())
LOG = ROOT / "data" / "manual" / "w2w_log.csv"
OUT = ROOT / "data" / "processed" / "w2w.json"

TODAY = datetime.date.today()
RACE = datetime.date.fromisoformat(BRIEF["meta"]["race_date"])
CHECKPOINT = 6.0

runs = RUNS["runs"]
longest = max((r["miles"] for r in runs), default=0)
wk_start = TODAY - datetime.timedelta(days=TODAY.weekday())
wk_runs = [r for r in runs if r["date"] >= wk_start.isoformat()]
week_miles = round(sum(r["miles"] for r in wk_runs), 1)

# jog-pace discipline rollup
n_ok = sum(1 for r in runs if r["in_control"])
latest_run = runs[-1] if runs else None

# ---- manual log (Achilles status, PT streak, ankle symmetry) ----
log = []
if LOG.exists():
    for row in csv.DictReader(l for l in LOG.read_text().splitlines() if l and not l.startswith("#")):
        if row.get("date"):
            log.append(row)
log.sort(key=lambda r: r["date"])

def latest(field):
    for r in reversed(log):
        if r.get(field):
            return r[field]
    return None

# PT streak = consecutive logged days (ending today/yesterday) with pt_done y
pt_streak = 0
d = TODAY
seen = {r["date"]: r for r in log}
if d.isoformat() not in seen:
    d -= datetime.timedelta(days=1)
while d.isoformat() in seen and (seen[d.isoformat()].get("pt_done","").lower() in ("y","yes")):
    pt_streak += 1; d -= datetime.timedelta(days=1)

ankle_r = latest("ankle_sls_right_s"); ankle_l = latest("ankle_sls_left_s")
symmetry = None
if ankle_r and ankle_l:
    try:
        symmetry = round(100 * float(ankle_r) / float(ankle_l))
    except (ValueError, ZeroDivisionError):
        pass

result = {
    "generated": TODAY.isoformat(),
    "race_date": BRIEF["meta"]["race_date"],
    "days_to_race": (RACE - TODAY).days,
    "goal": BRIEF["meta"]["goal_note"],
    "goal_pace": BRIEF["meta"]["goal_pace_per_mile"],
    "limiter": BRIEF["meta"]["limiter"],
    "start_line": "30th Ave & Portola (moved from the wharf — Murray St Bridge construction)",
    "longest_run": longest,
    "checkpoint": CHECKPOINT,
    "longest_pct": round(100 * longest / CHECKPOINT),
    "week_miles": week_miles,
    "week_run_count": len(wk_runs),
    "jog_discipline": {
        "runs_in_control": n_ok, "runs_total": len(runs),
        "z2_ceiling": RUNS["z2_ceiling"], "rows": runs,
        "latest": latest_run,
    },
    "manual": {
        "achilles_status": latest("achilles_status"),
        "pt_streak": pt_streak,
        "n_logged_days": len(log),
        "ankle_sls_right_s": ankle_r, "ankle_sls_left_s": ankle_l,
        "ankle_symmetry_pct": symmetry,
        "hop_test": latest("hop_test"),
        "has_log": len(log) > 0,
    },
    "hr_zones": BRIEF["hr_zones_bpm"],
    "pace_targets": BRIEF["pace_targets_per_mile"],
    "injuries": BRIEF["injuries"],
    "rehab_protocol": BRIEF["rehab_protocol"],
}
OUT.write_text(json.dumps(result, indent=2))
print(f"Wrote {OUT}")
print(f"W2W {result['race_date']} — {result['days_to_race']} days out | longest {longest}/{CHECKPOINT} mi ({result['longest_pct']}%)")
print(f"Jog discipline: {n_ok}/{len(runs)} runs in control (<=139 bpm jogs)")
if latest_run:
    print(f"  latest {latest_run['date']}: {latest_run['avg_hr_moving']} avg HR, {latest_run['pct_zone2']}% Z2, drift {latest_run['drift']:+d}")
print(f"Manual log: {len(log)} days · PT streak {pt_streak} · Achilles {result['manual']['achilles_status'] or '(unlogged)'}")
