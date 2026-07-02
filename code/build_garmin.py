#!/usr/bin/env python3
"""Parse the Garmin Connect data export into the Health 360 view.

Garmin's headline contribution is a **measured VO2max** computed from years of real
runs/rides (Firstbeat) — far better than our triangulated estimate. Also a long
resting-HR history, but the user does NOT sleep in the watch, so Garmin RHR is
daytime-derived and runs high (~63-70) vs their true overnight ~46-52 from Oura —
kept only as a long-term trend, NOT as the resting-HR source of truth (Oura wins).

Reads Health Records/Garmin Export/<uuid>/DI_CONNECT/... and writes
data/processed/garmin.json.
"""
import json, glob, statistics, datetime
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "processed" / "garmin.json"

def find_connect_dir():
    hits = glob.glob(str(ROOT / "Health Records" / "Garmin Export" / "**" / "DI_CONNECT"), recursive=True)
    return Path(hits[0]) if hits else None

def monthly(series):
    """series: dict date->value -> list of {month, value(mean)} sorted."""
    buckets = defaultdict(list)
    for d, v in series.items():
        buckets[d[:7]].append(v)
    return [{"month": m, "value": round(statistics.mean(vs), 1)} for m, vs in sorted(buckets.items())]

def main():
    cdir = find_connect_dir()
    if not cdir:
        print("No Garmin export found under Health Records/Garmin Export/"); raise SystemExit(1)

    # ---- VO2max (MaxMetData), prefer RUNNING (the standard headline metric) ----
    vo2 = defaultdict(dict)  # sport -> date -> value
    for f in glob.glob(str(cdir / "DI-Connect-Metrics" / "MetricsMaxMetData_*.json")):
        for e in json.load(open(f)):
            v, s, d = e.get("vo2MaxValue"), e.get("sport"), e.get("calendarDate")
            if v and s and d:
                vo2[s][d] = float(v)
    run = vo2.get("RUNNING", {})
    primary = run or (vo2.get("CYCLING") or {})
    sport = "RUNNING" if run else ("CYCLING" if vo2.get("CYCLING") else "—")
    vo2_latest = primary[max(primary)] if primary else None
    vo2_vals = list(primary.values())

    # ---- Resting HR (UDS), daytime-derived — trend only ----
    rhr = {}
    for f in glob.glob(str(cdir / "DI-Connect-Aggregator" / "UDSFile_*.json")):
        try:
            data = json.load(open(f))
        except (ValueError, OSError):
            continue
        for e in (data if isinstance(data, list) else [data]):
            d = e.get("calendarDate"); h = e.get("restingHeartRate")
            if d and h:
                rhr[d] = h

    result = {
        "generated": datetime.date.today().isoformat(),
        "vo2max": ({
            "measured": vo2_latest,
            "sport": sport,
            "latest_date": max(primary),
            "n": len(primary),
            "range": [min(vo2_vals), max(vo2_vals)],
            "date_range": [min(primary), max(primary)],
            "monthly": monthly(primary),
            "note": "Garmin Firstbeat VO2max from runs/rides — the measured value for the dashboard.",
        } if primary else None),
        "resting_hr": ({
            "latest": rhr[max(rhr)],
            "date_range": [min(rhr), max(rhr)],
            "n": len(rhr),
            "monthly": monthly(rhr),
            "note": "Daytime-derived (watch not worn overnight) so reads high; trend only. Oura is the resting-HR source of truth.",
        } if rhr else None),
    }
    OUT.write_text(json.dumps(result, indent=2))
    print(f"Wrote {OUT}")
    if primary:
        v = result["vo2max"]
        print(f"VO2max ({sport}): measured {vo2_latest} (latest {v['latest_date']}), "
              f"{v['n']} readings {v['date_range'][0]}→{v['date_range'][1]}, range {v['range'][0]}–{v['range'][1]}")
    if rhr:
        print(f"Resting HR (Garmin, daytime): {len(rhr)} days {min(rhr)}→{max(rhr)}, latest {rhr[max(rhr)]} (trend only)")

if __name__ == "__main__":
    main()
