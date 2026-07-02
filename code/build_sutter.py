#!/usr/bin/env python3
"""Parse the Sutter (Epic/Lucy) C-CDA export into vitals + labs for the Health 360 view.

Reads every DOC*.XML under Health Records/Sutter Export/ and extracts:
  * Blood pressure (LOINC 8480-6 systolic / 8462-4 diastolic) -> office BP history
  * Pulse (8867-4), Body weight (29463-7 / 3141-9), BMI (39156-5)
The same reading appears across many visit summaries, so everything is deduped by
timestamp. Writes data/processed/sutter_vitals.json.

Office BP is single readings and can be white-coat elevated; a 7-day home series is
still preferred for the risk model, but this gives a real measured baseline.
"""
import re, json, glob, datetime, statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "Health Records" / "Sutter Export"
OUT = ROOT / "data" / "processed" / "sutter_vitals.json"

# observation: code ... effectiveTime ... value(PQ).  Non-greedy to stay inside one obs.
OBS = re.compile(
    r'code="(?P<loinc>8480-6|8462-4|8867-4|29463-7|3141-9|39156-5)"'
    r'.*?effectiveTime value="(?P<dt>\d{8,14})'
    r'.*?value xsi:type="PQ" value="(?P<val>-?\d+\.?\d*)"(?:\s+unit="(?P<unit>[^"]*)")?',
    re.DOTALL)

LABEL = {"8480-6": "sys", "8462-4": "dia", "8867-4": "pulse",
         "29463-7": "weight", "3141-9": "weight", "39156-5": "bmi"}

# narrative-table lab rows: <td ...Name">NAME</td><td>[<content>]VALUE[</content>]</td><td>RANGE</td>
CAPTION = re.compile(r'<caption[^>]*>(?P<name>[^<]*?)\((?P<date>\d{2}/\d{2}/\d{4})[^)]*\)</caption>')
LABROW = re.compile(r'Name"?>(?P<lab>[^<]{2,45})</td><td>(?:<content>)?\s*(?P<val>-?\d+\.?\d*)\s*(?:</content>)?</td><td>(?P<ref>[^<]*)</td>')

# map a narrative lab name (lowercased, substring) -> our key
LAB_KEYS = [
    ("alt", "alt"), ("sgpt", "alt"), ("ast", "ast"), ("sgot", "ast"),
    ("ggt", "ggt"), ("gamma gluta", "ggt"),
    ("alkaline phos", "alp"), ("bilirubin", "bilirubin_total"),
    ("cholesterol to hdl", "tc_hdl_ratio"), ("non hdl", "non_hdl_c"),
    ("ldl", "ldl_c"), ("hdl", "hdl_c"), ("triglyceride", "triglycerides"),
    ("cholesterol", "total_chol"), ("hemoglobin a1c", "a1c"), ("a1c", "a1c"),
    ("glucose", "glucose"), ("creatinine", "creatinine"), ("c reactive", "hs_crp"),
]
def classify(name):
    n = name.lower().strip()
    for sub, key in LAB_KEYS:
        if sub in n:
            return key
    return None

def parse_dt(s):
    s = s[:14].ljust(14, "0")
    try:
        return datetime.datetime.strptime(s, "%Y%m%d%H%M%S")
    except ValueError:
        return datetime.datetime.strptime(s[:8], "%Y%m%d")

def main():
    files = glob.glob(str(SRC / "**" / "DOC*.XML"), recursive=True)
    if not files:
        print(f"No C-CDA docs found under {SRC}"); raise SystemExit(1)

    # (timestamp) -> {sys, dia, pulse, weight, bmi}
    readings = {}
    labs = {}   # (date, key) -> value   (deduped across docs)
    for f in files:
        txt = Path(f).read_text(errors="ignore")
        for m in OBS.finditer(txt):
            kind = LABEL[m.group("loinc")]
            dt = parse_dt(m.group("dt"))
            val = float(m.group("val"))
            unit = (m.group("unit") or "").strip()
            if kind == "weight" and unit in ("[lb_av]", "lb"):
                val = round(val * 0.453592, 1)   # lb -> kg
            readings.setdefault(dt, {})[kind] = val
        # narrative labs: assign each lab row the date of its nearest preceding caption
        caps = [(mm.start(), mm.group("date")) for mm in CAPTION.finditer(txt)]
        for mm in LABROW.finditer(txt):
            key = classify(mm.group("lab"))
            if not key:
                continue
            prior = [d for pos, d in caps if pos < mm.start()]
            if not prior:
                continue
            mo, dy, yr = prior[-1].split("/")
            iso = f"{yr}-{mo}-{dy}"
            labs[(iso, key)] = float(mm.group("val"))

    # blood-pressure series = timestamps with both sys & dia
    bp = [{"datetime": dt.isoformat(), "date": dt.date().isoformat(),
           "systolic": int(v["sys"]), "diastolic": int(v["dia"]),
           "pulse": int(v["pulse"]) if "pulse" in v else None}
          for dt, v in sorted(readings.items()) if "sys" in v and "dia" in v]

    sys_vals = [r["systolic"] for r in bp]
    dia_vals = [r["diastolic"] for r in bp]
    weights = sorted((dt, v["weight"]) for dt, v in readings.items() if "weight" in v)
    # representative recent BP for the risk model: mean of last 6 years of readings
    cutoff = (datetime.date.today() - datetime.timedelta(days=6*365)).isoformat()
    recent = [r for r in bp if r["date"] >= cutoff]
    bp_recent = ({"systolic": round(statistics.mean(r["systolic"] for r in recent)),
                  "diastolic": round(statistics.mean(r["diastolic"] for r in recent)),
                  "n": len(recent), "since": recent[0]["date"]} if recent else None)

    def cat(s, d):
        if s < 120 and d < 80: return "normal"
        if s < 130 and d < 80: return "elevated"
        if s < 140 or d < 90:  return "stage 1 hypertension"
        return "stage 2 hypertension"

    # organize narrative labs into per-marker time series
    by_marker = {}
    for (iso, key), val in sorted(labs.items()):
        by_marker.setdefault(key, []).append({"date": iso, "value": val})
    liver = {k: by_marker.get(k, []) for k in ("alt", "ast", "ggt", "alp", "bilirubin_total")}
    alt_high = [r for r in liver["alt"] if r["value"] > 44]

    result = {
        "generated": datetime.date.today().isoformat(),
        "source": "Sutter My Health Online C-CDA export",
        "n_docs": len(files),
        "labs_by_marker": by_marker,
        "liver_enzymes": liver,
        "alt_elevations": alt_high,
        "bp_readings": len(bp),
        "bp_date_range": [bp[0]["date"], bp[-1]["date"]] if bp else [None, None],
        "bp_latest": bp[-1] if bp else None,
        "bp_mean": ({"systolic": round(statistics.mean(sys_vals)),
                     "diastolic": round(statistics.mean(dia_vals)),
                     "category": cat(statistics.mean(sys_vals), statistics.mean(dia_vals))}
                    if bp else None),
        "bp_max": ({"systolic": max(sys_vals), "diastolic": max(dia_vals)} if bp else None),
        "bp_recent": bp_recent,
        "weight_kg_range": ([round(weights[0][1], 1), round(weights[-1][1], 1)] if weights else None),
        "bp_series": bp,
    }
    OUT.write_text(json.dumps(result, indent=2))
    print(f"Wrote {OUT}")
    if bp:
        m = result["bp_mean"]
        print(f"BP: {len(bp)} office readings {result['bp_date_range'][0]}→{result['bp_date_range'][1]}")
        print(f"  mean {m['systolic']}/{m['diastolic']} ({m['category']})  |  "
              f"latest {bp[-1]['systolic']}/{bp[-1]['diastolic']} ({bp[-1]['date']})  |  "
              f"max {result['bp_max']['systolic']}/{result['bp_max']['diastolic']}")
        print("\n  recent readings:")
        for r in bp[-8:]:
            print(f"    {r['date']}  {r['systolic']}/{r['diastolic']}" + (f"  HR {r['pulse']}" if r['pulse'] else ""))
    print(f"\nLabs extracted: {len(labs)} values across {len(by_marker)} markers ({', '.join(sorted(by_marker))})")
    if liver["alt"]:
        alt_str = ", ".join(f"{r['date'][:7]}={r['value']:.0f}" for r in liver["alt"])
        print(f"  ALT history (ref <44): {alt_str}")
        if alt_high:
            print(f"  ⚠ ALT elevations: {[(r['date'], r['value']) for r in alt_high]}")

if __name__ == "__main__":
    main()
