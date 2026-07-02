#!/usr/bin/env python3
"""Ingest the Google Health (Fitbit) Takeout export -> data/processed/google_health.json.

The standout is body weight: the Fitbit Aria scale recorded ~1,400 readings from
2013 through May 2026, which fills the gap left when the home scale broke in Dec 2025
and the Apple Health series went stale. Apple Health never received the Google-side
weight (Google can only READ HealthKit, not write to it), so we pull it straight from
the Takeout CSV here and merge it into the dashboard's weight trend.

Source layout (Takeout):
  Google Health/Physical Activity_GoogleData/weight.csv   timestamp, weight grams, data source
"""
import csv, json, datetime, statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "Health Records" / "Google-health" / "Takeout" / "Google Health"
OUT = ROOT / "data" / "processed" / "google_health.json"

def parse_weight():
    f = SRC / "Physical Activity_GoogleData" / "weight.csv"
    if not f.exists():
        return None
    rows = []
    with f.open() as fh:
        for r in csv.DictReader(fh):
            ts = (r.get("timestamp") or "").strip()
            grams = (r.get("weight grams") or "").strip()
            if not ts or not grams:
                continue
            try:
                date = ts[:10]
                kg = round(int(float(grams)) / 1000.0, 2)
            except ValueError:
                continue
            if kg <= 0:
                continue
            rows.append({"date": date, "ts": ts, "kg": kg, "src": (r.get("data source") or "").strip()})
    if not rows:
        return None
    rows.sort(key=lambda x: x["ts"])

    # one value per day (last reading of the day), then month-average to match Apple's series
    by_day = {}
    for r in rows:
        by_day[r["date"]] = r["kg"]
    by_month = defaultdict(list)
    for d, kg in by_day.items():
        by_month[d[:7]].append(kg)
    monthly = [{"month": m, "weight_kg": round(statistics.mean(v), 1)} for m, v in sorted(by_month.items())]

    kgs = [r["kg"] for r in rows]
    src_counts = defaultdict(int)
    for r in rows:
        src_counts[r["src"] or "unknown"] += 1
    return {
        "latest_kg": rows[-1]["kg"], "latest_date": rows[-1]["date"], "latest_src": rows[-1]["src"],
        "first_kg": rows[0]["kg"], "first_date": rows[0]["date"],
        "min_kg": min(kgs), "max_kg": max(kgs), "n": len(rows),
        "date_range": [rows[0]["date"], rows[-1]["date"]],
        "monthly": monthly,
        "daily": [{"date": d, "kg": k} for d, k in sorted(by_day.items())],
        "sources": dict(src_counts),
    }

def main():
    weight = parse_weight()
    result = {
        "generated": datetime.date.today().isoformat(),
        "source": "Google Health (Fitbit) Takeout",
        "weight": weight,
    }
    OUT.write_text(json.dumps(result, indent=2))
    print(f"Wrote {OUT}")
    if weight:
        w = weight
        print(f"Weight: {w['n']} readings {w['date_range'][0]}→{w['date_range'][1]} "
              f"({w['min_kg']}–{w['max_kg']} kg); latest {w['latest_kg']} kg on {w['latest_date']} ({w['latest_src']})")
        # show the months that extend past Apple's Dec-2025 end
        recent = [m for m in w["monthly"] if m["month"] >= "2026-01"]
        if recent:
            print("  new months (fills the gap):", ", ".join(f"{m['month']}={m['weight_kg']}" for m in recent))
    else:
        print("No weight.csv found / parsed.")

if __name__ == "__main__":
    main()
