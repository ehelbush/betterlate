#!/usr/bin/env python3
"""Apple Health pipeline — ingests Health Auto Export JSON into the Health 360 view.

Apple keeps HealthKit on-device (no cloud API), so this reads the JSON that the
Health Auto Export iOS app writes to its iCloud container. Two file shapes:
  * HealthAutoExport-YYYY.json          -> weekly-grouped backfill (one pt per week)
  * HealthAutoExport-YYYY-MM-DD.json    -> daily auto-sync (intraday points)
We detect grouping from the filename and normalize SUM metrics (steps, energy,
nutrition, distance) to a per-day value (weekly total / 7); MEAN metrics
(weight, resting HR, walking speed) are used as-is.

The user's sources: MyFitnessPal (nutrition + early weight), iPhones, Garmin Connect
(cycling). No Apple Watch, so VO2max / BP / SpO2 are absent. The genuinely useful
layer here: a long weight trajectory, resting-HR history, and activity/gait trends.

Output: data/processed/apple_health.json
"""
import json, os, glob, re, datetime, statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = Path(os.environ.get("APPLE_HEALTH_DIR", ROOT / "data" / "apple-health"))
ICLOUD = Path.home() / "Library/Mobile Documents/iCloud~com~ifunography~HealthExport/Documents"
OUT = ROOT / "data" / "processed" / "apple_health.json"
LB_TO_KG = 0.453592

# exact metric name -> (our key, aggregation)
QTY_MAP = {
    "step_count":              ("steps", "sum"),
    "flights_climbed":         ("flights", "sum"),
    "active_energy":           ("active_energy", "sum"),
    "basal_energy_burned":     ("basal_energy", "sum"),
    "walking_running_distance":("walk_run_mi", "sum"),
    "cycling_distance":        ("cycling_mi", "sum"),
    "walking_speed":           ("walking_speed", "mean"),
    "resting_heart_rate":      ("resting_hr", "mean"),
    "respiratory_rate":        ("respiratory", "mean"),
    "weight_body_mass":        ("weight_kg", "mean"),   # lb -> kg below
    "heart_rate_variability":  ("hrv", "mean"),
    "vo2_max":                 ("vo2max", "mean"),
    "blood_oxygen_saturation": ("spo2", "mean"),
}
NUTRI = {  # MyFitnessPal nutrition (per-day after /7); units in comment
    "dietary_energy": "kcal", "saturated_fat": "g", "fiber": "g",
    "cholesterol": "mg", "carbohydrates": "g", "protein": "g",
    "sodium": "mg", "dietary_sugar": "g",
}
SUM = {k for k, (_, a) in QTY_MAP.items() if a == "sum"} | set(NUTRI)

WEEKLY_RE = re.compile(r"-\d{4}\.json$")  # year-only filename = weekly backfill

def day_of(s): return str(s)[:10]
def month_of(s): return str(s)[:7]

def load_files():
    seen, files = set(), []
    for base in (SRC_DIR, ICLOUD):
        for f in glob.glob(str(base / "**" / "*.json"), recursive=True):
            rp = os.path.realpath(f)
            if rp not in seen:
                seen.add(rp); files.append(f)
    return sorted(files)

def main():
    files = load_files()
    if not files:
        print(f"No Apple Health JSON found in {SRC_DIR} or the iCloud container.\n"
              "  Set up Health Auto Export (JSON, iCloud Drive) — see report/DATA_ACQUISITION.md")
        raise SystemExit(1)

    qty = defaultdict(lambda: defaultdict(list))   # key -> date -> [per-day values]
    nutri = defaultdict(lambda: defaultdict(list))
    hr_min, hr_avg = defaultdict(list), defaultdict(list)

    for f in files:
        weekly = bool(WEEKLY_RE.search(os.path.basename(f)))
        try:
            doc = json.loads(Path(f).read_text())
        except (ValueError, OSError):
            continue
        for m in (doc.get("data") or {}).get("metrics") or []:
            name = (m.get("name") or "").lower()
            pts = m.get("data") or []
            if name == "heart_rate":
                for p in pts:
                    d = day_of(p.get("date"))
                    if p.get("Min") is not None: hr_min[d].append(float(p["Min"]))
                    if p.get("Avg") is not None: hr_avg[d].append(float(p["Avg"]))
                continue
            target = NUTRI if name in NUTRI else (QTY_MAP[name][0] if name in QTY_MAP else None)
            if target is None:
                continue
            for p in pts:
                v = p.get("qty")
                if v is None:
                    continue
                v = float(v)
                if name in SUM and weekly:
                    v /= 7.0                       # weekly total -> per-day
                if name == "weight_body_mass":
                    v *= LB_TO_KG                   # lb -> kg
                d = day_of(p.get("date"))
                if name in NUTRI:
                    nutri[name][d].append(v)
                else:
                    qty[QTY_MAP[name][0]][d].append(v)

    # collapse to one value per day per key
    daily = defaultdict(dict)
    agg_of = {k: a for _, (k, a) in QTY_MAP.items()}
    for key, byd in qty.items():
        for d, vals in byd.items():
            daily[d][key] = round(sum(vals) if agg_of.get(key) == "sum" else statistics.mean(vals), 2)
    for d, vals in hr_min.items(): daily[d].setdefault("resting_hr", round(min(vals)))
    for d, vals in hr_avg.items(): daily[d]["hr_avg"] = round(statistics.mean(vals))

    days = [dict(date=d, **daily[d]) for d in sorted(daily)]

    # monthly rollups for trend charts (mean of the per-day values within the month)
    monthly = defaultdict(lambda: defaultdict(list))
    for r in days:
        for k, v in r.items():
            if k != "date":
                monthly[r["date"][:7]][k].append(v)
    monthly_out = []
    for mth in sorted(monthly):
        row = {"month": mth}
        for k, vals in monthly[mth].items():
            row[k] = round(statistics.mean(vals), 1)
        monthly_out.append(row)

    def latest(key, src=days):
        for r in reversed(src):
            if key in r: return r[key]
        return None
    def avg30(key):
        vals = [r[key] for r in days[-30:] if key in r]
        return round(sum(vals)/len(vals), 1) if vals else None

    # nutrition: intermittent MyFitnessPal data — summarize, don't over-trust
    nutri_weeks = len(set().union(*[set(nutri[n]) for n in nutri]) ) if nutri else 0
    nutri_span = None
    if nutri:
        alld = sorted(set().union(*[set(nutri[n]) for n in nutri]))
        nutri_span = [alld[0], alld[-1]] if alld else None

    keys = ["weight_kg","resting_hr","hr_avg","steps","walking_speed","flights",
            "walk_run_mi","cycling_mi","total_energy","hrv","vo2max","spo2"]
    wk = [r["weight_kg"] for r in days if "weight_kg" in r]
    result = {
        "generated": datetime.date.today().isoformat(),
        "n_files": len(files),
        "n_days": len(days),
        "date_range": [days[0]["date"], days[-1]["date"]] if days else [None, None],
        "latest": {k: latest(k) for k in keys},
        "avg_30d": {k: avg30(k) for k in ["resting_hr","hr_avg","steps","walking_speed"]},
        "weight": ({"latest_kg": round(wk[-1], 1), "first_kg": round(wk[0], 1),
                    "min_kg": round(min(wk), 1), "max_kg": round(max(wk), 1),
                    "n": len(wk)} if wk else None),
        "nutrition": ({"source": "MyFitnessPal (Apple Health)", "weeks_logged": nutri_weeks,
                       "span": nutri_span,
                       "note": "Intermittent/incomplete logging — indicative only, not reliable for precise diet targets."}
                      if nutri else None),
        "monthly": monthly_out,
        "daily": days,
    }
    OUT.write_text(json.dumps(result, indent=2))
    print(f"Wrote {OUT}  ({len(days)} day-points from {len(files)} files, {result['date_range'][0]}→{result['date_range'][1]})")
    w = result["weight"]
    if w: print(f"Weight: {w['n']} readings, {w['first_kg']}→{w['latest_kg']} kg (min {w['min_kg']}, max {w['max_kg']})")
    print(f"Resting HR latest {latest('resting_hr')}  |  steps/day 30d avg {avg30('steps')}  |  walking {avg30('walking_speed')} mph")
    if result["nutrition"]:
        print(f"Nutrition (MyFitnessPal): {nutri_weeks} weeks logged, {nutri_span} — intermittent")

if __name__ == "__main__":
    main()
