#!/usr/bin/env python3
"""Estimate VO2max from data already on hand, until a measured test exists.

VO2max can't be read directly from Strava, but it can be triangulated from
heart-rate ratio, cycling FTP, and running race pace. Each method is noisy and
sport-specific, so we report all three plus a weighted central estimate and a
range — never a single false-precision number.

Precedence: if Oura has a *measured* VO2max (from its guided test), that wins and
this estimate is shown only as a cross-check. Writes data/processed/vo2max.json.
"""
import json, math, datetime, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
P = ROOT / "data" / "processed"
OUT = P / "vo2max.json"

def load(name):
    f = P / name
    return json.loads(f.read_text()) if f.exists() else {}

LIVE = load("strava_live.json")
FIT = load("fitness.json")
OURA = load("oura.json")
APPLE = load("apple_health.json")
GARMIN = load("garmin.json")

weight = LIVE.get("profile", {}).get("weight_kg", 80)
ftp = LIVE.get("ftp_watts", 200)
hrmax = FIT.get("hrmax_observed", 190)
# Use the 30-day-average resting HR (stable) rather than a single nightly nadir.
hr_rest = (OURA.get("avg_30d", {}) or {}).get("resting_hr") or 55

methods = []

# 1) Uth-Sorensen HR-ratio (trained men): VO2max ~ 15.3 * HRmax/HRrest
hr_est = 15.3 * hrmax / hr_rest
methods.append({"method": "HR ratio (Uth-Sorensen)", "value": round(hr_est),
                "inputs": f"HRmax {hrmax} / resting {hr_rest}", "weight": 0.4})

# 2) Cycling, from FTP: VO2max power ~ FTP/0.75; ACSM cycling VO2
vo2_pwr = ftp / 0.75
acsm = (10.8 * vo2_pwr / weight) + 7
methods.append({"method": "Cycling FTP (ACSM)", "value": round(acsm),
                "inputs": f"FTP {ftp}W @ {weight:.0f}kg", "weight": 0.4})

# 3) Running VDOT from fastest 10k (Daniels), if available
m = re.match(r"(\d+)m(\d+)s", LIVE.get("fastest_10k", ""))
if m:
    t = int(m.group(1)) + int(m.group(2)) / 60.0  # minutes
    v = 10000.0 / t
    pct = 0.8 + 0.1894393*math.exp(-0.012778*t) + 0.2989558*math.exp(-0.1932605*t)
    vo2 = -4.60 + 0.182258*v + 0.000104*v*v
    methods.append({"method": "Running VDOT (Daniels)", "value": round(vo2/pct),
                    "inputs": f"10k {LIVE['fastest_10k']}", "weight": 0.2,
                    "note": "low because cycling-dominant athlete runs slowly"})

# weighted central estimate
wsum = sum(x["weight"] for x in methods)
central = round(sum(x["value"] * x["weight"] for x in methods) / wsum)
vals = [x["value"] for x in methods]

# rating bands, men 40-49 (Cooper/ACSM, approx ml/kg/min)
def rating(v):
    return ("Superior" if v >= 53 else "Excellent" if v >= 48 else "Good" if v >= 43
            else "Fair" if v >= 36 else "Poor")

# Measured value precedence: Garmin (years of run/ride data) > Apple Watch > Oura.
garmin_vo2 = (GARMIN.get("vo2max") or {}).get("measured")
apple_vo2 = (APPLE.get("latest", {}) or {}).get("vo2max")
oura_vo2 = (OURA.get("latest", {}) or {}).get("vo2max")
measured = garmin_vo2 or apple_vo2 or oura_vo2
measured_src = ("Garmin" if garmin_vo2 else "Apple Watch" if apple_vo2 else "Oura" if oura_vo2 else None)

result = {
    "generated": datetime.date.today().isoformat(),
    "measured_oura": measured,
    "estimate_central": central,
    "estimate_range": [min(vals), max(vals)],
    "rating": rating(measured or central),
    "is_measured": measured is not None,
    "measured_source": measured_src,
    "methods": methods,
    "note": (f"Measured VO2max in use ({measured_src})." if measured else
             "Estimate only — triangulated from HR, FTP, and race pace. "
             "Take the Oura guided VO2max test or a lab CPET for a true value."),
}
OUT.write_text(json.dumps(result, indent=2))
print(f"Wrote {OUT}")
src = f"MEASURED ({measured_src}) {measured}" if measured else f"estimate {central} (range {min(vals)}-{max(vals)})"
print(f"VO2max: {src} ml/kg/min  [{result['rating']}]")
for x in methods:
    print(f"  {x['method']:<26} {x['value']:>3}  ({x['inputs']})")
