#!/usr/bin/env python3
"""Oura Ring pipeline — pulls daily ring metrics into the Health 360 view.

Uses the Oura Cloud API v2 (no third-party deps, stdlib urllib only).

SETUP (one time):
  1. Go to https://cloud.ouraring.com/personal-access-tokens and create a token.
  2. Save it to  data/oura/token.txt   (single line; this folder is not committed)
     or export OURA_TOKEN=...
  3. Run:  python3 code/build_oura.py            # last 365 days
           python3 code/build_oura.py 2024-01-01 # from a start date

Output:
  data/oura/raw/<endpoint>.json    cached raw API responses
  data/processed/oura.json         tidy daily series the dashboard reads

CV-relevant series extracted: resting HR, HRV, sleep duration/efficiency,
readiness, SpO2, VO2max, and Oura "cardiovascular age" (vascular_age).
"""
import json, os, sys, urllib.request, urllib.error, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OURA_DIR = ROOT / "data" / "oura"
RAW = OURA_DIR / "raw"
OUT = ROOT / "data" / "processed" / "oura.json"
BASE = "https://api.ouraring.com/v2/usercollection"

# endpoint -> whether it's date-ranged via start_date/end_date
ENDPOINTS = [
    "daily_sleep", "sleep", "daily_readiness", "daily_activity",
    "daily_spo2", "daily_cardiovascular_age", "vO2_max",
]

def get_token():
    tok = os.environ.get("OURA_TOKEN")
    f = OURA_DIR / "token.txt"
    if not tok and f.exists():
        tok = f.read_text().strip()
    return tok

def fetch(endpoint, token, start, end):
    """Page through an Oura v2 collection endpoint."""
    rows, nxt = [], None
    while True:
        q = f"start_date={start}&end_date={end}"
        if nxt:
            q += f"&next_token={nxt}"
        req = urllib.request.Request(f"{BASE}/{endpoint}?{q}",
                                     headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.load(r)
        rows.extend(payload.get("data", []))
        nxt = payload.get("next_token")
        if not nxt:
            return rows

def main():
    token = get_token()
    if not token:
        print("No Oura token found.\n"
              "  Create one at https://cloud.ouraring.com/personal-access-tokens\n"
              "  then save it to data/oura/token.txt (or export OURA_TOKEN=...).")
        sys.exit(1)

    end = datetime.date.today().isoformat()
    start = sys.argv[1] if len(sys.argv) > 1 else (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    RAW.mkdir(parents=True, exist_ok=True)

    raw = {}
    for ep in ENDPOINTS:
        try:
            data = fetch(ep, token, start, end)
            (RAW / f"{ep}.json").write_text(json.dumps(data, indent=2))
            raw[ep] = data
            print(f"  {ep}: {len(data)} records")
        except urllib.error.HTTPError as e:
            print(f"  {ep}: HTTP {e.code} ({e.reason}) — skipped")
            raw[ep] = []
        except Exception as e:
            print(f"  {ep}: {e} — skipped")
            raw[ep] = []

    # ---- normalize into a daily timeline ----
    daily = {}
    def day(d):
        return daily.setdefault(d, {"date": d})

    for s in raw.get("sleep", []):
        d = s.get("day")
        if not d:
            continue
        row = day(d)
        if s.get("lowest_heart_rate"):
            row["resting_hr"] = s["lowest_heart_rate"]
        if s.get("average_hrv"):
            row["hrv"] = s["average_hrv"]
        if s.get("total_sleep_duration"):
            row["sleep_hours"] = round(s["total_sleep_duration"] / 3600, 2)
        if s.get("efficiency"):
            row["sleep_efficiency"] = s["efficiency"]
    for s in raw.get("daily_sleep", []):
        if s.get("day") and s.get("score") is not None:
            day(s["day"])["sleep_score"] = s["score"]
    for s in raw.get("daily_readiness", []):
        if s.get("day") and s.get("score") is not None:
            day(s["day"])["readiness"] = s["score"]
    for s in raw.get("daily_activity", []):
        if s.get("day"):
            r = day(s["day"])
            if s.get("steps") is not None: r["steps"] = s["steps"]
    for s in raw.get("daily_spo2", []):
        d = s.get("day"); spo2 = (s.get("spo2_percentage") or {}).get("average")
        if d and spo2 is not None:
            day(d)["spo2"] = round(spo2, 1)
    for s in raw.get("daily_cardiovascular_age", []):
        if s.get("day") and s.get("vascular_age") is not None:
            day(s["day"])["vascular_age"] = s["vascular_age"]
    for s in raw.get("vO2_max", []):
        d = s.get("day") or (s.get("timestamp") or "")[:10]
        if d and s.get("vo2_max") is not None:
            day(d)["vo2max"] = s["vo2_max"]

    series = [daily[d] for d in sorted(daily)]

    def latest_of(key):
        for r in reversed(series):
            if key in r:
                return r[key]
        return None
    def avg_recent(key, n=30):
        vals = [r[key] for r in series[-n:] if key in r]
        return round(sum(vals)/len(vals), 1) if vals else None

    result = {
        "generated": datetime.date.today().isoformat(),
        "range": [start, end],
        "n_days": len(series),
        "latest": {k: latest_of(k) for k in
                   ["resting_hr","hrv","sleep_hours","sleep_efficiency","sleep_score",
                    "readiness","spo2","vascular_age","vo2max"]},
        "avg_30d": {k: avg_recent(k) for k in
                    ["resting_hr","hrv","sleep_hours","readiness","spo2"]},
        "daily": series,
    }
    OUT.write_text(json.dumps(result, indent=2))
    print(f"\nWrote {OUT}  ({len(series)} days)")
    L = result["latest"]
    print(f"Latest: RHR {L['resting_hr']}  HRV {L['hrv']}  sleep {L['sleep_hours']}h  "
          f"VO2max {L['vo2max']}  vascular age {L['vascular_age']}")

if __name__ == "__main__":
    main()
