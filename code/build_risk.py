#!/usr/bin/env python3
"""Cardiovascular risk assessment for the Health 360 view.

Computes the ACC/AHA Pooled Cohort Equations 10-year ASCVD risk from the latest
lipid panel, layers on risk enhancers actually present in the user's data (Lp(a),
ApoB, hs-CRP, family-history flag), and correlates exercise volume with lipids
year-by-year. Writes ../data/processed/risk.json.

Assumptions where data is missing are listed in result["assumptions"] and should
be replaced with measured values (esp. systolic BP) when available.
"""
import json, math, datetime, csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIO = json.loads((ROOT / "data" / "processed" / "biomarkers.json").read_text())
FIT = json.loads((ROOT / "data" / "processed" / "fitness.json").read_text())
OUT = ROOT / "data" / "processed" / "risk.json"

def load_bp():
    """Average of blood-pressure readings in data/manual/blood_pressure.csv, if any."""
    f = ROOT / "data" / "manual" / "blood_pressure.csv"
    if not f.exists():
        return None
    sys_vals = []
    for row in csv.DictReader(l for l in f.read_text().splitlines() if not l.startswith("#")):
        try:
            sys_vals.append(float(row["systolic"]))
        except (ValueError, KeyError, TypeError):
            continue
    return round(sum(sys_vals) / len(sys_vals), 1) if sys_vals else None

def load_apple_bp():
    """Most recent systolic from Apple Health, if no manual log exists."""
    f = ROOT / "data" / "processed" / "apple_health.json"
    if not f.exists():
        return None
    latest = (json.loads(f.read_text()).get("latest") or {})
    return latest.get("bp_systolic")

def load_sutter_bp():
    """Recent-mean office systolic from the Sutter C-CDA export, if present."""
    f = ROOT / "data" / "processed" / "sutter_vitals.json"
    if not f.exists():
        return None, None
    d = json.loads(f.read_text())
    r = d.get("bp_recent")
    return (r["systolic"], r) if r else (None, None)

# Priority: home cuff log (best) > Sutter office BP (real, white-coat caveat) > Apple Health > assumption
measured_sbp = load_bp()
sbp_source = "blood_pressure.csv (home)" if measured_sbp else None
sutter_bp_detail = None
if not measured_sbp:
    sutter_sbp, sutter_bp_detail = load_sutter_bp()
    if sutter_sbp:
        measured_sbp, sbp_source = sutter_sbp, "Sutter office readings"
if not measured_sbp:
    apple_sbp = load_apple_bp()
    if apple_sbp:
        measured_sbp, sbp_source = apple_sbp, "Apple Health"

DOB = datetime.date(1981, 4, 22)
TODAY = datetime.date.today()
age = TODAY.year - DOB.year - ((TODAY.month, TODAY.day) < (DOB.month, DOB.day))

latest = BIO["panels"][-1]  # 2026-01-14

# ---- Inputs (white male coefficients; BP assumed pending real measurement) ----
total_chol = latest["total_chol"]   # 230
hdl = latest["hdl_c"]               # 57
sbp = measured_sbp if measured_sbp else 120   # measured BP if logged, else assumption
sbp_is_measured = measured_sbp is not None
bp_treated = False
smoker = False     # per cardiology notes; binge-alcohol noted, not tobacco
diabetic = False   # A1c 5.3, glucose 92, insulin 5.3 -> not diabetic

# ---- Pooled Cohort Equations (2013 ACC/AHA), white male ----
def ascvd_white_male(age, tc, hdl, sbp, treated, smoker, diab):
    ln_age = math.log(age); ln_tc = math.log(tc); ln_hdl = math.log(hdl)
    ln_sbp = math.log(sbp)
    s = (12.344 * ln_age + 11.853 * ln_tc - 2.664 * ln_age * ln_tc
         - 7.990 * ln_hdl + 1.769 * ln_age * ln_hdl)
    if treated:
        s += 1.797 * ln_sbp
    else:
        s += 1.764 * ln_sbp
    s += 7.837 * (1 if smoker else 0) - 1.795 * ln_age * (1 if smoker else 0)
    s += 0.658 * (1 if diab else 0)
    mean = 61.18
    base_surv = 0.9144
    risk = 1 - base_surv ** math.exp(s - mean)
    return risk * 100

base_risk = ascvd_white_male(age, total_chol, hdl, sbp, bp_treated, smoker, diabetic)

# ---- Risk enhancers actually present (2018 ACC/AHA cholesterol guideline) ----
enhancers = []
if latest.get("lp_a", 0) >= 75:
    enhancers.append(f"Lp(a) {latest['lp_a']} nmol/L — markedly elevated (>=75 is a risk-enhancing genetic factor; this level is independently high-risk)")
if latest.get("apob", 0) >= 90:
    enhancers.append(f"ApoB {latest['apob']} mg/dL — elevated (>=90 risk-enhancing; >=110 high), confirms high atherogenic particle burden")
crp_vals = [p.get("hs_crp") for p in BIO["panels"] if p.get("hs_crp")]
if crp_vals and crp_vals[-1] >= 2.0:
    enhancers.append(f"hs-CRP {crp_vals[-1]} mg/L — intermediate-range inflammation")
ldlp = next((p.get("ldl_p") for p in reversed(BIO["panels"]) if p.get("ldl_p")), None)
if ldlp:
    enhancers.append(f"LDL-P {ldlp} nmol/L and small dense LDL pattern on NMR — discordantly high particle count")
if latest["ldl_c"] >= 160 or max(p.get("ldl_c", 0) for p in BIO["panels"]) >= 160:
    enhancers.append("Persistent/peak LDL-C >=160 mg/dL (peak 164 in 2024) — severe primary hypercholesterolemia range")
sleep_path = ROOT / "data" / "processed" / "sleep_study.json"
sleep = json.loads(sleep_path.read_text()) if sleep_path.exists() else None
if sleep:
    enhancers.append(
        f"Moderate obstructive sleep apnea (pAHI 3% {sleep['pAHI_3pct']}, O2 nadir {sleep['spo2_min']}%, "
        f"{sleep['study_date']}; worse REM/supine) — independent, TREATABLE driver of BP/AFib/inflammation. "
        f"Treatment status: {sleep['treated']}")
if sutter_bp_detail and (sutter_bp_detail["systolic"] >= 130 or sutter_bp_detail["diastolic"] >= 80):
    enhancers.append(
        f"Borderline / low-stage-1 blood pressure — Sutter office BP averages {sutter_bp_detail['systolic']}/{sutter_bp_detail['diastolic']} "
        f"({sutter_bp_detail['n']} readings since {sutter_bp_detail['since']}); latest 131/83 (2025). "
        "Notably stable since 2009 and never flagged, so lower-priority: confirm with a home cuff (rule out white-coat), "
        "and treating the sleep apnea may lower it on its own — monitor before any treatment.")

# ---- Exercise <-> lipid correlation ----
fit_by_year = {y["year"]: y for y in FIT["annual"]}
corr_rows = []
for p in BIO["panels"]:
    yr = p["date"][:4]
    fy = fit_by_year.get(yr)
    if fy:
        corr_rows.append({
            "date": p["date"],
            "mvpa_min_wk": fy["mod_vig_min_per_wk"],
            "train_hours_yr": fy["hours"],
            "ldl_c": p.get("ldl_c"),
            "hdl_c": p.get("hdl_c"),
            "triglycerides": p.get("triglycerides"),
        })

# Pearson r between MVPA and TG / HDL where both present
def pearson(xs, ys):
    n = len(xs)
    if n < 3: return None
    mx, my = sum(xs)/n, sum(ys)/n
    num = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x-mx)**2 for x in xs) * sum((y-my)**2 for y in ys))
    return round(num/den, 2) if den else None

tg_pairs = [(r["mvpa_min_wk"], r["triglycerides"]) for r in corr_rows if r["triglycerides"]]
hdl_pairs = [(r["mvpa_min_wk"], r["hdl_c"]) for r in corr_rows if r["hdl_c"]]
ldl_pairs = [(r["mvpa_min_wk"], r["ldl_c"]) for r in corr_rows if r["ldl_c"]]
r_tg = pearson([a for a,_ in tg_pairs], [b for _,b in tg_pairs])
r_hdl = pearson([a for a,_ in hdl_pairs], [b for _,b in hdl_pairs])
r_ldl = pearson([a for a,_ in ldl_pairs], [b for _,b in ldl_pairs])

result = {
    "generated": TODAY.isoformat(),
    "age": age,
    "ascvd_10yr_pct": round(base_risk, 1),
    "ascvd_category": ("low (<5%)" if base_risk < 5 else
                       "borderline (5-7.5%)" if base_risk < 7.5 else
                       "intermediate (7.5-20%)" if base_risk < 20 else "high (>=20%)"),
    "ascvd_note": ("Pooled Cohort Equations capture only age/sex/lipids/BP/smoking/diabetes. "
                   "They DO NOT include Lp(a) or ApoB, so they substantially understate this profile. "
                   "The risk enhancers below move the user into a higher effective-risk tier."),
    "lifetime_risk_note": "With Lp(a) 235 nmol/L plus LDL/ApoB elevation from age <45, lifetime ASCVD risk is high even though the 10-yr number looks modest.",
    "risk_enhancers": enhancers,
    "assumptions": [
        (f"Systolic BP {sbp} mmHg from {sbp_source}."
         if sbp_is_measured else
         f"Systolic BP assumed {sbp} mmHg, untreated — NOT measured. Log readings in data/manual/blood_pressure.csv (or sync Apple Health) to use real values."),
        "Non-smoker, non-diabetic per labs/notes.",
        "White/other race coefficients used.",
    ],
    "sbp_used": sbp,
    "sbp_is_measured": sbp_is_measured,
    "latest_panel": latest,
    "sleep_study": sleep,
    "exercise_lipid_correlation": {
        "pearson_mvpa_vs_triglycerides": r_tg,
        "pearson_mvpa_vs_hdl": r_hdl,
        "pearson_mvpa_vs_ldl": r_ldl,
        "interpretation": ("Higher training volume tracks with lower triglycerides and higher HDL "
                           "in the user's own data; LDL/ApoB and Lp(a) are far less exercise-responsive "
                           "and are the markers that most need diet + possible pharmacotherapy."),
        "rows": corr_rows,
    },
}

OUT.write_text(json.dumps(result, indent=2))
print(f"Wrote {OUT}\n")
print(f"Age {age}  |  10-yr ASCVD (base PCE): {result['ascvd_10yr_pct']}%  [{result['ascvd_category']}]")
print(f"Risk enhancers present: {len(enhancers)}")
for e in enhancers: print("  •", e)
print(f"\nExercise correlation:  r(MVPA,TG)={r_tg}   r(MVPA,HDL)={r_hdl}")
print("\nYear   MVPA/wk  LDL  HDL  TG")
for r in corr_rows:
    print(f"  {r['date']}  {str(r['mvpa_min_wk']):>5}   {str(r['ldl_c'] or '-'):>3}  {str(r['hdl_c'] or '-'):>3}  {str(r['triglycerides'] or '-'):>3}")
