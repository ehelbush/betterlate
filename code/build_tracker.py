#!/usr/bin/env python3
"""Momentum tracker — daily consistency + weekly compliance vs the regimen plan.

Merges the Strava export (history) with data/strava-live/recent.json (recent activities
pulled live via MCP) into a daily activity series, scores this week against
data/processed/plan.json targets, and computes streaks. Writes data/processed/tracker.json,
which the dashboard renders as a "This Week" momentum tab (heatmap + compliance + streaks).

Pass a reference date as argv[1] (YYYY-MM-DD) for deterministic builds; defaults to today.
"""
import csv, json, sys, datetime
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPORT = ROOT / "data" / "strava-export" / "activities.csv"
RECENT = ROOT / "data" / "strava-live" / "recent.json"
PLAN = json.loads((ROOT / "data" / "processed" / "plan.json").read_text())
OUT = ROOT / "data" / "processed" / "tracker.json"

TODAY = datetime.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.date.today()
RUN = {"Run"}; STRENGTH = {"Workout", "Weight Training", "Yoga"}
RIDE = {"Ride", "E-Bike Ride", "EBikeRide"}; SWIMSURF = {"Swim", "Surfing", "Stand Up Paddling", "Kayaking"}

def f(x):
    try: return float(x)
    except (TypeError, ValueError): return 0.0

def parse_export_date(s):
    for fmt in ("%b %d, %Y, %I:%M:%S %p", "%b %d, %Y, %H:%M:%S"):
        try: return datetime.datetime.strptime(s.strip(), fmt).date()
        except ValueError: continue
    return None

# date -> list of {type, min, load}
days = defaultdict(list)
cutoff = TODAY - datetime.timedelta(days=200)

if EXPORT.exists():
    for r in csv.DictReader(open(EXPORT)):
        d = parse_export_date(r.get("Activity Date", ""))
        if not d or d < cutoff or d > TODAY:
            continue
        days[d.isoformat()].append({"type": r.get("Activity Type", "").strip(),
                                    "min": (f(r.get("Moving Time")) or 0)/60,
                                    "load": f(r.get("Relative Effort"))})
if RECENT.exists():
    for a in json.loads(RECENT.read_text())["activities"]:
        days[a["date"]].append({"type": a["type"], "min": a["moving_s"]/60, "load": a["rel_effort"]})

def has(types, acts): return any(a["type"] in types for a in acts)

# ---- daily heatmap: last 16 weeks (start on a Monday) ----
end = TODAY
start = end - datetime.timedelta(days=end.weekday() + 15*7)  # Monday, 16 weeks back
heat = []
d = start
while d <= end:
    acts = days.get(d.isoformat(), [])
    load = round(sum(a["load"] for a in acts))
    mins = round(sum(a["min"] for a in acts))
    heat.append({"date": d.isoformat(), "load": load, "min": mins,
                 "active": 1 if acts else 0,
                 "kinds": sorted({("run" if a["type"] in RUN else "strength" if a["type"] in STRENGTH
                                   else "swim" if a["type"] in SWIMSURF else "ride" if a["type"] in RIDE
                                   else "other") for a in acts})})
    d += datetime.timedelta(days=1)

# ---- this week (Mon–Sun containing TODAY) compliance ----
wk_start = TODAY - datetime.timedelta(days=TODAY.weekday())
wk = [days.get((wk_start + datetime.timedelta(days=i)).isoformat(), []) for i in range(7)]
flat = [a for day in wk for a in day]
t = PLAN["weekly_targets"]; lsm = PLAN["long_session_min_minutes"]
done = {
    "active_days": sum(1 for day in wk if day),
    "runs": sum(1 for day in wk if has(RUN, day)),
    "strength": sum(1 for day in wk if has(STRENGTH, day)),
    "rides": sum(1 for day in wk if has(RIDE, day)),
    "long_session": sum(1 for a in flat if a["min"] >= lsm),
    "swim_or_surf": sum(1 for day in wk if has(SWIMSURF, day)),
}
compliance = [{"key": k, "label": k.replace("_", " "), "done": done[k], "target": t[k],
               "pct": min(100, round(100*done[k]/t[k])) if t[k] else 100} for k in t]
overall = round(sum(c["pct"] for c in compliance)/len(compliance))

# ---- streaks ----
active_dates = {k for k, v in days.items() if v}
# current active streak (consecutive days up to today/yesterday)
streak = 0; d = TODAY
if d.isoformat() not in active_dates: d -= datetime.timedelta(days=1)  # today may be unfinished
while d.isoformat() in active_dates:
    streak += 1; d -= datetime.timedelta(days=1)
# weeks meeting the runs target, counting back
weeks_on_target = 0; ws = wk_start
while True:
    days_in = [days.get((ws + datetime.timedelta(days=i)).isoformat(), []) for i in range(7)]
    if sum(1 for dd in days_in if has(RUN, dd)) >= t["runs"] and any(days_in):
        weeks_on_target += 1; ws -= datetime.timedelta(days=7)
    else:
        break

result = {
    "generated": TODAY.isoformat(),
    "phase": PLAN["phase"],
    "week_of": wk_start.isoformat(),
    "overall_compliance": overall,
    "compliance": compliance,
    "this_week": {"hours": round(sum(a["min"] for a in flat)/60, 1),
                  "load": round(sum(a["load"] for a in flat)),
                  "sessions": len(flat)},
    "streak_active_days": streak,
    "weeks_run_target": weeks_on_target,
    "heatmap": heat,
}
OUT.write_text(json.dumps(result, indent=2))
print(f"Wrote {OUT}")
print(f"Week of {wk_start}: {overall}% compliance | streak {streak}d active | {weeks_on_target} wks on run-target")
for c in compliance:
    bar = "█"*round(c["pct"]/10) + "·"*(10-round(c["pct"]/10))
    print(f"  {c['label']:14} {c['done']}/{c['target']}  {bar} {c['pct']}%")
