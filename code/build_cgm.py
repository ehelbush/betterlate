#!/usr/bin/env python3
"""Stelo / Dexcom CGM pipeline for the Health 360 view.

Oura's API does not expose the integrated Stelo glucose (verified: 404), so this
reads a CSV exported from the Stelo app (or Dexcom Clarity) and computes the
cardiovascular-relevant glucose metrics: mean, GMI (estimated A1c), glycemic
variability (SD, CV%), time-in-range, spike frequency, and overnight glucose.

Why a CGM matters here even with a normal A1c: post-meal spikes and high glycemic
variability drive triglycerides, small-dense LDL, and inflammation independent of
fasting glucose / A1c — the exact lipid pattern in the user's 2022-23 panels.

USAGE:
  1. Export from the Stelo app (Account/Profile -> Export, or share to Dexcom Clarity
     -> Export CSV). Save the .csv into  data/cgm/.
  2. python3 code/build_cgm.py
Output: data/processed/cgm.json  (+ dashboard CGM section on next build_dashboard.py)
"""
import csv, json, datetime, statistics, glob, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CGM_DIR = ROOT / "data" / "cgm"
OUT = ROOT / "data" / "processed" / "cgm.json"

# non-diabetic optimization thresholds (mg/dL)
TIR_LO, TIR_HI = 70, 140      # standard healthy range
TIGHT_HI = 110                # tight optimization ceiling
SPIKE = 140                   # post-meal excursion threshold

def find_csv():
    files = sorted(glob.glob(str(CGM_DIR / "*.csv")))
    return files[-1] if files else None

def parse_rows(path):
    """Auto-detect timestamp and glucose columns across Stelo/Clarity formats."""
    text = Path(path).read_text(errors="ignore").splitlines()
    reader = csv.reader(text)
    rows = list(reader)
    # find header row containing a glucose-like column
    header_idx, gcol, tcol = None, None, None
    for i, r in enumerate(rows[:15]):
        low = [c.strip().lower() for c in r]
        for j, c in enumerate(low):
            if "glucose" in c and ("mg/dl" in c or "value" in c or c == "glucose"):
                gcol = j
            if "timestamp" in c or c in ("device timestamp", "time", "datetime"):
                tcol = j
        if gcol is not None:
            header_idx = i
            break
    if header_idx is None or gcol is None:
        raise SystemExit("Could not find a glucose column in the CSV header.")
    out = []
    for r in rows[header_idx + 1:]:
        if len(r) <= gcol:
            continue
        gv = r[gcol].strip()
        m = re.search(r"\d+\.?\d*", gv)
        if not m:
            continue
        val = float(m.group())
        if val < 20 or val > 600:
            continue
        ts = None
        if tcol is not None and len(r) > tcol:
            ts = parse_ts(r[tcol].strip())
        out.append((ts, val))
    return out

def parse_ts(s):
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M",
                "%m/%d/%Y %I:%M %p", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.datetime.strptime(s[:19], fmt[:len(s[:19])] if "%z" not in fmt else fmt)
        except ValueError:
            continue
    return None

def main():
    path = find_csv()
    if not path:
        print("No CGM CSV found. Export from the Stelo app and drop a .csv in data/cgm/.\n"
              "  Stelo app -> Profile/Account -> Export Data, or share to Dexcom Clarity -> Export.")
        raise SystemExit(1)

    data = parse_rows(path)
    vals = [v for _, v in data]
    if not vals:
        raise SystemExit("CSV parsed but no glucose values found.")

    mean = statistics.mean(vals)
    sd = statistics.pstdev(vals)
    cv = sd / mean * 100
    gmi = 3.31 + 0.02392 * mean  # estimated A1c-equivalent (%)
    n = len(vals)
    pct = lambda f: round(100 * sum(1 for v in vals if f(v)) / n, 1)

    # overnight (00:00-06:00) where timestamps exist
    night = [v for t, v in data if t and 0 <= t.hour < 6]
    day = [v for t, v in data if t and 6 <= t.hour < 24]

    dated = [t for t, _ in data if t]
    span = (max(dated).date().isoformat(), min(dated).date().isoformat()) if dated else (None, None)

    result = {
        "generated": datetime.date.today().isoformat(),
        "source_file": Path(path).name,
        "n_readings": n,
        "date_range": [span[1], span[0]],
        "mean_glucose": round(mean, 1),
        "gmi_est_a1c": round(gmi, 2),
        "sd": round(sd, 1),
        "cv_pct": round(cv, 1),
        "peak": round(max(vals)),
        "min": round(min(vals)),
        "time_in_range_70_140_pct": pct(lambda v: TIR_LO <= v <= TIR_HI),
        "time_tight_70_110_pct": pct(lambda v: TIR_LO <= v <= TIGHT_HI),
        "time_above_140_pct": pct(lambda v: v > SPIKE),
        "time_below_70_pct": pct(lambda v: v < TIR_LO),
        "overnight_mean": round(statistics.mean(night), 1) if night else None,
        "daytime_mean": round(statistics.mean(day), 1) if day else None,
        "targets": {
            "mean_glucose": "<105", "gmi_est_a1c": "<5.7", "cv_pct": "<20 (excellent), <36 (ok)",
            "time_in_range_70_140_pct": ">95", "time_above_140_pct": "<5",
        },
    }
    OUT.write_text(json.dumps(result, indent=2))
    print(f"Wrote {OUT}")
    print(f"{n} readings | mean {result['mean_glucose']} (GMI {result['gmi_est_a1c']}%) | "
          f"CV {result['cv_pct']}% | TIR70-140 {result['time_in_range_70_140_pct']}% | "
          f">140 {result['time_above_140_pct']}%")

if __name__ == "__main__":
    main()
