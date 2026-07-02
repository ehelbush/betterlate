#!/usr/bin/env python3
"""Aggregate Strava activities into a cardio-fitness timeline for the Health 360 view.

Reads ../data/strava-export/activities.csv and writes ../data/processed/fitness.json
with monthly/annual aggregates plus heart-rate-zone estimates. CV-relevant metrics:
moving hours, distance, training load (Relative Effort), and minutes in moderate-to-
vigorous (Zone 2+) intensity, which is what drives cardiovascular adaptation.
"""
import csv, json, datetime
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "strava-export" / "activities.csv"
OUT = ROOT / "data" / "processed" / "fitness.json"

DOB = datetime.date(1981, 4, 22)

def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

def parse_date(s):
    for fmt in ("%b %d, %Y, %I:%M:%S %p", "%b %d, %Y, %H:%M:%S"):
        try:
            return datetime.datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None

rows = list(csv.DictReader(open(SRC)))

acts = []
for r in rows:
    dt = parse_date(r.get("Activity Date", ""))
    if not dt:
        continue
    acts.append({
        "dt": dt,
        "type": r.get("Activity Type", "").strip(),
        "dist_km": (f(r.get("Distance")) or 0) / 1000.0,
        "hours": (f(r.get("Moving Time")) or 0) / 3600.0,
        "avg_hr": f(r.get("Average Heart Rate")),
        "max_hr": f(r.get("Max Heart Rate")),
        "rel_effort": f(r.get("Relative Effort")) or 0,
        "calories": f(r.get("Calories")) or 0,
        "elev": f(r.get("Elevation Gain")) or 0,
    })

acts.sort(key=lambda a: a["dt"])

# Estimate HRmax from observed maxima (robust: 99th pct of recorded max HR)
maxhrs = sorted(a["max_hr"] for a in acts if a["max_hr"])
hrmax = maxhrs[int(len(maxhrs) * 0.99)] if maxhrs else 175
age_pred_hrmax = 220 - (datetime.date.today().year - DOB.year)

# Prefer real Strava-set HR zones if synced (data/processed/strava_live.json)
zone_source = "estimated (% of observed HRmax)"
z2_lo = 0.60 * hrmax   # aerobic base / fat-ox
z4_lo = 0.80 * hrmax   # vigorous
live_path = ROOT / "data" / "processed" / "strava_live.json"
if live_path.exists():
    try:
        z = json.loads(live_path.read_text())["hr_zones_bpm"]
        z2_lo, z4_lo = z["z2"][0], z["z4"][0]
        zone_source = "Strava athlete zones (real)"
    except (KeyError, ValueError):
        pass

CARDIO_TYPES = {"Ride", "E-Bike Ride", "Run", "Hike", "Walk", "Swim",
                "Workout", "Stand Up Paddling", "Kayaking"}

monthly = defaultdict(lambda: {"hours": 0.0, "dist_km": 0.0, "count": 0,
                               "load": 0.0, "mod_vig_min": 0.0, "hr_sum": 0.0,
                               "hr_n": 0, "calories": 0.0})
annual = defaultdict(lambda: {"hours": 0.0, "dist_km": 0.0, "count": 0,
                              "load": 0.0, "mod_vig_min": 0.0, "by_type_hours": defaultdict(float),
                              "first": None, "last": None})

for a in acts:
    mk = a["dt"].strftime("%Y-%m")
    yk = a["dt"].strftime("%Y")
    m, y = monthly[mk], annual[yk]
    m["hours"] += a["hours"]; m["dist_km"] += a["dist_km"]; m["count"] += 1
    m["load"] += a["rel_effort"]; m["calories"] += a["calories"]
    y["hours"] += a["hours"]; y["dist_km"] += a["dist_km"]; y["count"] += 1
    y["load"] += a["rel_effort"]; y["by_type_hours"][a["type"]] += a["hours"]
    if y["first"] is None: y["first"] = a["dt"]
    y["last"] = a["dt"]
    if a["avg_hr"]:
        m["hr_sum"] += a["avg_hr"]; m["hr_n"] += 1
    # moderate-to-vigorous minutes: count session minutes if avg HR >= Z2 lower
    if a["avg_hr"] and a["avg_hr"] >= z2_lo and a["type"] in CARDIO_TYPES:
        mins = a["hours"] * 60
        m["mod_vig_min"] += mins; y["mod_vig_min"] += mins

monthly_out = []
for mk in sorted(monthly):
    d = monthly[mk]
    monthly_out.append({
        "month": mk,
        "hours": round(d["hours"], 1),
        "dist_km": round(d["dist_km"], 1),
        "count": d["count"],
        "load": round(d["load"]),
        "mod_vig_min_per_wk": round(d["mod_vig_min"] / 4.345),
        "avg_hr": round(d["hr_sum"] / d["hr_n"]) if d["hr_n"] else None,
        "calories": round(d["calories"]),
    })

annual_out = []
for yk in sorted(annual):
    d = annual[yk]
    top = sorted(d["by_type_hours"].items(), key=lambda x: -x[1])[:5]
    span_days = (d["last"] - d["first"]).days if d["first"] and d["last"] else 0
    weeks = max(span_days / 7.0, 1.0)
    partial = span_days < 350
    annual_out.append({
        "year": yk,
        "hours": round(d["hours"]),
        "dist_km": round(d["dist_km"]),
        "count": d["count"],
        "load": round(d["load"]),
        "mod_vig_min_per_wk": round(d["mod_vig_min"] / weeks),
        "partial": partial,
        "top_types": [{"type": t, "hours": round(h)} for t, h in top],
    })

result = {
    "generated": datetime.date.today().isoformat(),
    "n_activities": len(acts),
    "date_range": [acts[0]["dt"].date().isoformat(), acts[-1]["dt"].date().isoformat()],
    "hrmax_observed": round(hrmax),
    "hrmax_age_predicted": age_pred_hrmax,
    "zones": {"z2_lower_bpm": round(z2_lo), "vigorous_lower_bpm": round(z4_lo), "source": zone_source},
    "annual": annual_out,
    "monthly": monthly_out,
}

OUT.write_text(json.dumps(result, indent=2))
print(f"Wrote {OUT}")
print(f"Activities: {len(acts)}  HRmax(obs)={round(hrmax)}  Z2>= {round(z2_lo)} bpm")
print("\nRecent annual cardio (mod-vig min/week target = 150):")
for y in annual_out[-8:]:
    print(f"  {y['year']}: {y['hours']:>4}h  {y['dist_km']:>6}km  load {y['load']:>5}  MVPA {y['mod_vig_min_per_wk']:>3} min/wk  ({y['count']} acts)")
