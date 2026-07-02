#!/usr/bin/env python3
"""Render the Health 360 dashboard as a single self-contained HTML file.

Reads the three processed JSON files and emits ../report/index.html with all data
inlined and charts pre-rendered as SVG, so it opens correctly on double-click with
no web server or network access.
"""
import json, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Use your real data in data/processed/ once the build scripts have run; otherwise fall
# back to the bundled synthetic demo fixtures so the dashboard renders out of the box.
P = ROOT / "data" / "processed"
if not P.exists() or not any(P.glob("*.json")):
    P = ROOT / "sample" / "processed"
BIO = json.loads((P / "biomarkers.json").read_text())
FIT = json.loads((P / "fitness.json").read_text())
RISK = json.loads((P / "risk.json").read_text())
LIVE = json.loads((P / "strava_live.json").read_text()) if (P / "strava_live.json").exists() else {}
OURA = json.loads((P / "oura.json").read_text()) if (P / "oura.json").exists() else None
VO2 = json.loads((P / "vo2max.json").read_text()) if (P / "vo2max.json").exists() else None
CGM = json.loads((P / "cgm.json").read_text()) if (P / "cgm.json").exists() else None
APPLE = json.loads((P / "apple_health.json").read_text()) if (P / "apple_health.json").exists() else None
GOOGLE = json.loads((P / "google_health.json").read_text()) if (P / "google_health.json").exists() else None
SUTTER = json.loads((P / "sutter_vitals.json").read_text()) if (P / "sutter_vitals.json").exists() else None
GARMIN = json.loads((P / "garmin.json").read_text()) if (P / "garmin.json").exists() else None
TRACKER = json.loads((P / "tracker.json").read_text()) if (P / "tracker.json").exists() else None
W2W = json.loads((P / "w2w.json").read_text()) if (P / "w2w.json").exists() else None

# actual run dates (from Strava-derived w2w data) — drives run-aware scheduling
RUN_DATES = set()
if W2W:
    RUN_DATES = {r["date"] for r in W2W.get("jog_discipline", {}).get("rows", [])}

# Manual schedule overrides for specific dates (swaps around travel / events).
# ISO date -> (session text, is_run_day). Consulted before the weekday skeleton,
# so a one-off swap doesn't fight the run-aware rules.
PLAN_OVERRIDE = {
    # Week of 6/29: "get back on track" after the wedding weekend. Recovery markers rebounded
    # (readiness 85), so re-establish EASY aerobic + protect sleep. Every run strictly Z2, never
    # two run-days in a row. Cycling can be by feel (non-impact). ~25 days to Wharf to Wharf.
    "2026-07-01": ("Easy Z2 recovery ride / spin · today's priority is 8h sleep + hydration", False),
    "2026-07-02": ("Easy run 25–30 min · STRICTLY ≤139 bpm · walk breaks + warm-up/cool-down (discipline reset)", True),
    "2026-07-03": ("Recovery · Z2 spin or mobility, no run (day after a run)", False),
    "2026-07-04": ("Long run 5 mi · EASY Z2 pace only · warm-up + cool-down (sub a long ride if legs feel off)", True),
    "2026-07-05": ("Recovery ride / walk / surf, no run", False),
}

def aerobic_for(d):
    """Run-aware session for a day: never schedule a run the day after a run; mark days already run."""
    iso = d.isoformat(); wd = d.weekday()
    prev = (d - datetime.timedelta(days=1)).isoformat()
    if iso in RUN_DATES:
        return "✓ Ran today — easy spin / mobility to finish", False
    if iso in PLAN_OVERRIDE:
        return PLAN_OVERRIDE[iso]
    if prev in RUN_DATES:
        return "Recovery — Z2 ride or easy spin (no run: never two run-days in a row)", False
    base = {0:"Easy run 2–3 mi · jogs ≤139 bpm", 1:"Z2 endurance ride 60–90 min",
            2:"Easy run 2–3 mi · jogs ≤139 bpm", 3:"Surf AM + easy spin",
            4:"Strength (legs light) + easy spin", 5:"Long run (week's progression) · ≤139 bpm",
            6:"Easy ride / road-gravel"}[wd]
    return base, wd in (0, 2, 5)
OUT = ROOT / "report" / "index.html"
OUT.parent.mkdir(exist_ok=True)

latest = BIO["panels"][-1]
# Current weight: prefer the most recent *measured* scale reading (Google/Fitbit Aria has
# data through May 2026) over the stale Strava profile value. Falls back gracefully.
gw = (GOOGLE or {}).get("weight") or {}
cur_weight = gw.get("latest_kg") or LIVE.get("profile", {}).get("weight_kg", latest.get("weight_kg"))
cur_weight_date = gw.get("latest_date")
weight_status = "good" if cur_weight and cur_weight <= 93 else "warn"
# Display weight in pounds (data stays in kg internally). 93 kg target = 205 lb.
KG_TO_LB = 2.20462
TARGET_LB = round(93 * KG_TO_LB)  # 205
def lb(kg): return kg * KG_TO_LB

# ---------- tiny SVG chart helpers ----------
def _x(i, n, w, pad): return pad + (w - 2*pad) * (i/(max(n-1,1)))
def _y(v, lo, hi, h, pad):
    if hi == lo: hi = lo + 1
    return h - pad - (h - 2*pad) * ((v - lo)/(hi - lo))

def mon_yy(s):
    """Format a 'YYYY-MM' or 'YYYY-MM-DD' date as 'Jan-25'. Pass through anything else."""
    p = str(s).split("-")
    if len(p) >= 2 and len(p[0]) == 4 and p[1].isdigit():
        try:
            return datetime.date(int(p[0]), int(p[1]), 1).strftime("%b-%y")
        except ValueError:
            pass
    return str(s)

def line_chart(series, w=900, h=270, pad=44, bands=None, ylabel=""):
    """series: list of (label, color, [(xlabel, value)...]). Full-width; points show date+value on hover."""
    all_v = [v for _,_,pts in series for _,v in pts if v is not None]
    if not all_v: return ""
    lo, hi = min(all_v), max(all_v)
    rng = hi - lo or 1; lo -= rng*0.12; hi += rng*0.12
    n = len(series[0][2])
    svg = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">']
    if bands:
        for b_lo, b_hi, col in bands:
            y1, y2 = _y(min(b_hi,hi), lo, hi, h, pad), _y(max(b_lo,lo), lo, hi, h, pad)
            svg.append(f'<rect x="{pad}" y="{y1:.1f}" width="{w-2*pad}" height="{abs(y2-y1):.1f}" fill="{col}" opacity="0.10"/>')
    for k in range(4):
        val = lo + (hi-lo)*k/3
        y = _y(val, lo, hi, h, pad)
        svg.append(f'<line x1="{pad}" y1="{y:.1f}" x2="{w-pad}" y2="{y:.1f}" stroke="var(--grid)" stroke-width="1"/>')
        svg.append(f'<text x="{pad-6}" y="{y+4:.1f}" class="tick" text-anchor="end">{val:.0f}</text>')
    pts0 = series[0][2]
    for i,(xl,_) in enumerate(pts0):
        if i % max(1, n//8) == 0 or i == n-1:
            x = _x(i, n, w, pad)
            svg.append(f'<text x="{x:.1f}" y="{h-pad+18}" class="tick" text-anchor="middle">{xl}</text>')
    for label, color, pts in series:
        d = []
        for i,(_,v) in enumerate(pts):
            if v is None: continue
            x, y = _x(i, n, w, pad), _y(v, lo, hi, h, pad)
            d.append(f'{"M" if not d else "L"}{x:.1f} {y:.1f}')
        svg.append(f'<path d="{" ".join(d)}" fill="none" stroke="{color}" stroke-width="2.5"/>')
        for i,(xl,v) in enumerate(pts):
            if v is None: continue
            x, y = _x(i, n, w, pad), _y(v, lo, hi, h, pad)
            svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{color}"/>')
            svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="13" fill="transparent" pointer-events="all" data-tip="{label} · {xl}: {v:g}"/>')
    svg.append('</svg>')
    return "".join(svg)

def bars_with_line(cats, bar_vals, line_vals, bar_color, line_color, w=900, h=270, pad=46,
                   bar_label="", line_label=""):
    bl, bh = 0, max(bar_vals)*1.15 or 1
    ll, lh = min(v for v in line_vals if v is not None), max(v for v in line_vals if v is not None)
    lr = lh-ll or 1; ll -= lr*0.2; lh += lr*0.2
    n = len(cats); bw = (w-2*pad)/n*0.6
    svg = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">']
    for k in range(4):
        y = pad + (h-2*pad)*k/3
        svg.append(f'<line x1="{pad}" y1="{y:.1f}" x2="{w-pad}" y2="{y:.1f}" stroke="var(--grid)" stroke-width="1"/>')
    for i,c in enumerate(cats):
        cx = _x(i, n, w, pad)
        bh_px = (h-2*pad)*(bar_vals[i]/bh)
        svg.append(f'<rect x="{cx-bw/2:.1f}" y="{h-pad-bh_px:.1f}" width="{bw:.1f}" height="{bh_px:.1f}" fill="{bar_color}" opacity="0.55" rx="2" pointer-events="all" data-tip="{c} · {bar_label}: {bar_vals[i]:g}"/>')
        svg.append(f'<text x="{cx:.1f}" y="{h-pad+18}" class="tick" text-anchor="middle">{c}</text>')
    d=[]
    for i,v in enumerate(line_vals):
        if v is None: continue
        x = _x(i,n,w,pad); y = h-pad-(h-2*pad)*((v-ll)/(lh-ll))
        d.append(f'{"M" if not d else "L"}{x:.1f} {y:.1f}')
    svg.append(f'<path d="{" ".join(d)}" fill="none" stroke="{line_color}" stroke-width="2.5"/>')
    for i,v in enumerate(line_vals):
        if v is None: continue
        x = _x(i,n,w,pad); y = h-pad-(h-2*pad)*((v-ll)/(lh-ll))
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{line_color}"/>')
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="13" fill="transparent" pointer-events="all" data-tip="{cats[i]} · {line_label}: {v:g}"/>')
    svg.append('</svg>')
    return "".join(svg)

# ---------- KPI cards ----------
def kpi(label, value, unit, status, target):
    cls = {"good":"k-good","warn":"k-warn","bad":"k-bad"}[status]
    return f'''<div class="kpi {cls}"><div class="k-label">{label}</div>
      <div class="k-val">{value}<span class="k-unit">{unit}</span></div>
      <div class="k-target">{target}</div></div>'''

kpis = [
    kpi("10-yr ASCVD (base)", RISK["ascvd_10yr_pct"], "%", "good", "PCE only — understates risk"),
    kpi("Lp(a)", latest["lp_a"], "nmol/L", "bad", "goal &lt;75 · genetic"),
    kpi("ApoB", latest["apob"], "mg/dL", "bad", "goal &lt;80"),
    kpi("LDL-C", latest["ldl_c"], "mg/dL", "bad", "goal &lt;100 (&lt;70)"),
    kpi("HDL-C", latest["hdl_c"], "mg/dL", "warn", "goal &ge;60"),
    kpi("Triglycerides", latest["triglycerides"], "mg/dL", "good", "goal &lt;100"),
    kpi("HbA1c", latest["a1c"], "%", "good", "goal &lt;5.7"),
    kpi("Weight", f'{lb(cur_weight):.0f}', "lb", weight_status,
        ('at target' if weight_status == "good" else f'{lb(cur_weight)-TARGET_LB:.0f} lb over {TARGET_LB} target')
        + (f' · scale {mon_yy(cur_weight_date[:7])}' if cur_weight_date else '')),
    kpi("Cardio (MVPA)", FIT["annual"][-1]["mod_vig_min_per_wk"], "min/wk", "warn", "goal ≥150–300"),
]
if VO2:
    v = VO2["measured_oura"] or VO2["estimate_central"]
    tag = "measured" if VO2["is_measured"] else f'est · range {VO2["estimate_range"][0]}–{VO2["estimate_range"][1]}'
    vstatus = "good" if VO2["rating"] in ("Good","Excellent","Superior") else "warn"
    kpis.append(kpi("VO2max", v, "ml/kg/min", vstatus, f'{VO2["rating"]} · {tag}'))
if SUTTER and SUTTER.get("bp_latest"):
    bl = SUTTER["bp_latest"]; bm = SUTTER["bp_mean"]
    kpis.append(kpi("Blood pressure", f'{bl["systolic"]}/{bl["diastolic"]}', "mmHg", "warn",
                    'borderline · stable since 2009'))

# ---------- lipid trend chart ----------
def panel_series(key):
    return [(mon_yy(p["date"]), p.get(key)) for p in BIO["panels"]]
ldl_pts = panel_series("ldl_c"); apob_pts = panel_series("apob")
lipid_chart = line_chart([
    ("LDL-C", "var(--c-ldl)", ldl_pts),
    ("ApoB", "var(--c-apob)", [(d, v) for d, v in apob_pts]),
], bands=[(0,100,"var(--c-good)"),(160,400,"var(--c-bad)")])

hdl_chart = line_chart([("HDL-C", "var(--c-hdl)", panel_series("hdl_c")),
                        ("Triglycerides","var(--c-tg)", panel_series("triglycerides"))],
                       bands=[(60,200,"var(--c-good)")])

# ---------- exercise vs triglycerides (note: show TG, the diet/exercise-responsive marker) ----------
yrs = [a["year"] for a in FIT["annual"] if a["year"] >= "2018"]
fa = {a["year"]: a for a in FIT["annual"]}
tg_by_year = {p["date"][:4]: p.get("triglycerides") for p in BIO["panels"] if p.get("triglycerides")}
ex_cats = yrs
ex_bars = [fa[y]["mod_vig_min_per_wk"] for y in yrs]
ex_line = [tg_by_year.get(y) for y in yrs]
ex_chart = bars_with_line(ex_cats, ex_bars, ex_line, "var(--c-train)", "var(--c-tg)",
                          bar_label="MVPA min/wk", line_label="triglycerides")

# ---------- tables ----------
def bio_table():
    cols = [("date","Date"),("total_chol","TC"),("ldl_c","LDL"),("hdl_c","HDL"),
            ("triglycerides","TG"),("apob","ApoB"),("lp_a","Lp(a)"),("a1c","A1c"),("hs_crp","hsCRP")]
    head = "".join(f"<th>{h}</th>" for _,h in cols)
    rows = ""
    for p in BIO["panels"]:
        tds = ""
        for k,_ in cols:
            v = p.get(k, "")
            tds += f"<td>{v if v not in (None,'') else '·'}</td>"
        rows += f"<tr>{tds}</tr>"
    return f"<table class='tbl'><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"

def fit_table():
    head = "<th>Year</th><th>Hours</th><th>Dist (km)</th><th>Activities</th><th>Load</th><th>MVPA/wk</th><th>Top sports</th>"
    rows = ""
    for a in FIT["annual"]:
        if a["year"] < "2017": continue
        top = ", ".join(f"{t['type']} {t['hours']}h" for t in a["top_types"][:3])
        flag = " <span class='ytd'>YTD</span>" if a.get("partial") else ""
        rows += (f"<tr><td>{a['year']}{flag}</td><td>{a['hours']}</td><td>{a['dist_km']}</td>"
                 f"<td>{a['count']}</td><td>{a['load']}</td><td>{a['mod_vig_min_per_wk']}</td><td class='sm'>{top}</td></tr>")
    return f"<table class='tbl'><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"

# ---------- optional Oura section ----------
oura_section = ""
if OURA and OURA.get("daily"):
    L, A = OURA["latest"], OURA["avg_30d"]
    vasc = L.get("vascular_age")
    vasc_txt = (f"{vasc} vs {RISK['age']} chrono" if vasc else "—")
    def rhr_series(key):
        return [(mon_yy(r["date"]), r.get(key)) for r in OURA["daily"] if r.get(key) is not None]
    rhr_pts = rhr_series("resting_hr")[-120:]
    hrv_pts = rhr_series("hrv")[-120:]
    rhr_chart = line_chart([("Resting HR","var(--c-ldl)", rhr_pts)]) if len(rhr_pts) > 2 else ""
    hrv_chart = line_chart([("HRV","var(--c-hdl)", hrv_pts)]) if len(hrv_pts) > 2 else ""
    ocards = "".join([
        kpi("Resting HR", L.get("resting_hr","—"), "bpm", "good", f'30d avg {A.get("resting_hr","—")}'),
        kpi("HRV", L.get("hrv","—"), "ms", "good", f'30d avg {A.get("hrv","—")}'),
        kpi("Sleep", L.get("sleep_hours","—"), "h", "warn", f'efficiency {L.get("sleep_efficiency","—")}%'),
        kpi("Readiness", L.get("readiness","—"), "", "good", f'30d avg {A.get("readiness","—")}'),
        kpi("Vascular age", vasc or "—", "", "warn", vasc_txt),
        kpi("SpO2", L.get("spo2","—"), "%", "good", "apnea screen"),
    ])
    oura_section = f"""<div class="section">
  <h2>Oura ring — autonomic, sleep & recovery</h2>
  <p class="lead">{OURA['n_days']} days synced ({OURA['range'][0]} → {OURA['range'][1]}). Resting HR, HRV, and SpO2 are cardiac/autonomic markers; sleep + SpO2 also screen the apnea flagged by your cardiologist.</p>
  <div class="kpis">{ocards}</div>
  <div style="margin-top:16px">{rhr_chart}<div class="legend"><span><i style="background:var(--c-ldl)"></i>Resting HR (bpm)</span></div></div>
  <div style="margin-top:18px">{hrv_chart}<div class="legend"><span><i style="background:var(--c-hdl)"></i>HRV (ms)</span></div></div>
</div>"""

# ---------- optional CGM (Stelo) section ----------
cgm_section = ""
if CGM:
    tir = CGM["time_in_range_70_140_pct"]
    cv = CGM["cv_pct"]
    ccards = "".join([
        kpi("Mean glucose", CGM["mean_glucose"], "mg/dL", "good" if CGM["mean_glucose"] < 105 else "warn", "goal &lt;105"),
        kpi("GMI (est. A1c)", CGM["gmi_est_a1c"], "%", "good" if CGM["gmi_est_a1c"] < 5.7 else "warn", "goal &lt;5.7"),
        kpi("Variability (CV)", cv, "%", "good" if cv < 20 else "warn", "goal &lt;20"),
        kpi("Time 70–140", tir, "%", "good" if tir >= 95 else "warn", "goal &ge;95"),
        kpi("Time &gt;140", CGM["time_above_140_pct"], "%", "good" if CGM["time_above_140_pct"] < 5 else "warn", "spikes · goal &lt;5"),
        kpi("Overnight", CGM.get("overnight_mean") or "—", "mg/dL", "good", "dawn / sleep glucose"),
    ])
    cgm_section = f"""<div class="section">
  <h2>Stelo CGM — glucose & metabolic variability</h2>
  <p class="lead">{CGM['n_readings']} readings ({CGM['date_range'][0]} → {CGM['date_range'][1]}, from {CGM['source_file']}). Even with a normal A1c, post-meal spikes and high variability drive triglycerides, small-dense LDL, and inflammation — so these are tracked as cardiovascular markers, not just diabetes ones.</p>
  <div class="kpis">{ccards}</div>
</div>"""

# ---------- optional Apple Health section ----------
apple_section = ""
if APPLE and APPLE.get("daily"):
    L, A = APPLE["latest"], APPLE["avg_30d"]
    mo = APPLE.get("monthly", [])
    # Weight: merge Apple's monthly series with the Google/Fitbit Aria series. Google is the
    # fuller, more current source — it extends through May 2026 and fills the gap left when the
    # home scale broke in Dec 2025 (Apple never received the Google-side readings).
    wt_by_month = {m["month"]: m["weight_kg"] for m in mo if "weight_kg" in m}
    GW = (GOOGLE or {}).get("weight")
    if GW:
        for m in GW.get("monthly", []):
            wt_by_month[m["month"]] = m["weight_kg"]   # Google wins on overlap + extends past Dec 2025
    wt_pts = [(mon_yy(k), round(lb(v), 1)) for k, v in sorted(wt_by_month.items())]
    W = GW or APPLE.get("weight")  # summary KPI from the longer record
    rhr_pts = [(mon_yy(m["month"]), m["resting_hr"]) for m in mo if "resting_hr" in m]
    wt_chart = line_chart([("Weight lb","var(--c-train)", wt_pts)],
                          bands=[(0,TARGET_LB,"var(--c-good)")]) if len(wt_pts) > 2 else ""
    rhr_chart = line_chart([("Resting HR","var(--c-hdl)", rhr_pts)]) if len(rhr_pts) > 2 else ""
    _since = (W.get("date_range") or APPLE.get("date_range") or ["?"])[0][:4] if W else "?"
    wchg = (f'{lb(W["latest_kg"])-lb(W["first_kg"]):+.0f} lb since {_since}' if W else "")
    cards = [
        kpi("Weight (history)", f'{lb(W["latest_kg"]):.0f}' if W else "—", "lb", "warn", wchg),
        kpi("Resting HR", L.get("resting_hr","—"), "bpm", "good", f'30d avg {A.get("resting_hr","—")}'),
        kpi("Steps", f'{(A.get("steps") or 0):,.0f}', "/day", "good", "30d avg"),
        kpi("Walking speed", A.get("walking_speed","—"), "mph", "good", "gait / healthspan"),
    ]
    nut = APPLE.get("nutrition")
    nut_note = (f'<div class="callout"><b>Diet data found:</b> MyFitnessPal logged ~{nut["weeks_logged"]} weeks ({nut["span"][0]}→{nut["span"][1]}) synced via Apple Health — but it\'s intermittent and incomplete, so it confirms the earlier call: historical MFP data isn\'t reliable enough to analyze. Fresh consistent logging during the diet block is the way.</div>' if nut else "")
    apple_section = f"""<div class="section">
  <h2>Apple Health + Google — 13-year weight & activity history</h2>
  <p class="lead">{APPLE['n_days']} day-points, {APPLE['date_range'][0]}→{APPLE['date_range'][1]}, via Health Auto Export (Oura + iPhone + Garmin; no Apple Watch). The standout is a {W['n'] if W else 0}-reading weight trajectory{f" through {W['date_range'][1]}" if (W and W.get('date_range')) else ""}, now backfilled from the Fitbit Aria scale (Google Health Takeout) so the broken-home-scale gap since Dec 2025 is filled. HRV/SpO2/sleep come from the Oura section; VO2max/BP still need a watch, the Oura test, or a cuff.</p>
  <div class="kpis">{"".join(cards)}</div>
  <div style="margin-top:16px">{wt_chart}<div class="legend"><span><i style="background:var(--c-train)"></i>Body weight (lb) · green = ≤205 target</span></div></div>
  <div style="margin-top:18px">{rhr_chart}<div class="legend"><span><i style="background:var(--c-hdl)"></i>Resting HR (bpm)</span></div></div>
  {nut_note}
</div>"""

# ---------- optional Garmin VO2max block ----------
garmin_block = ""
if GARMIN and GARMIN.get("vo2max"):
    g = GARMIN["vo2max"]
    v_pts = [(mon_yy(m["month"]), m["value"]) for m in g["monthly"]]
    v_chart = line_chart([("VO2max","var(--c-train)", v_pts)],
                         bands=[(48,60,"var(--c-good)"),(0,40,"var(--c-bad)")]) if len(v_pts) > 2 else ""
    garmin_block = f"""<div class="section">
  <h2>VO2max — {g['n']}-reading Garmin history (measured)</h2>
  <p class="lead">Garmin Firstbeat VO2max from your {g['sport'].lower()} since {g['date_range'][0][:4]}: currently <b>{g['measured']:.0f}</b> (latest {g['latest_date']}), historical range {g['range'][0]:.0f}–{g['range'][1]:.0f}. For a 45-yr-old man, ~43 is "Good," but you've been as high as {g['range'][1]:.0f} — the recent dip tracks your lower run volume. The race block should pull it back up. Green band = excellent (≥48), red = below average.</p>
  {v_chart}
  <div class="legend"><span><i style="background:var(--c-train)"></i>VO2max (ml/kg/min)</span></div>
</div>"""

# ---------- optional Sutter BP block ----------
sutter_bp_block = ""
if SUTTER and SUTTER.get("bp_series"):
    s = SUTTER
    bp_pts = [(mon_yy(r["date"]), r["systolic"]) for r in s["bp_series"]]
    dia_pts = [(mon_yy(r["date"]), r["diastolic"]) for r in s["bp_series"]]
    bp_chart = line_chart([("Systolic","var(--c-ldl)", bp_pts),("Diastolic","var(--c-apob)", dia_pts)],
                          bands=[(0,120,"var(--c-good)"),(130,200,"var(--c-bad)")])
    m, rec = s["bp_mean"], s.get("bp_recent")
    sutter_bp_block = f"""<div class="section">
  <h2>Blood pressure — Sutter office history</h2>
  <p class="lead">{s['bp_readings']} office readings {mon_yy(s['bp_date_range'][0])}→{mon_yy(s['bp_date_range'][1])} from the Sutter record. Mean {m['systolic']}/{m['diastolic']}; recent 6-yr mean {rec['systolic']}/{rec['diastolic']}; latest {s['bp_latest']['systolic']}/{s['bp_latest']['diastolic']} ({mon_yy(s['bp_latest']['date'])}). <b>Notably stable since 2009</b> — these readings sit at the upper edge of normal / borderline (technically stage-1 by the ≥130/80 cutoff), but the long-term stability and that it's never been flagged make this lower-priority. Fills the input that every risk model was assuming.</p>
  {bp_chart}
  <div class="legend"><span><i style="background:var(--c-ldl)"></i>Systolic</span><span><i style="background:var(--c-apob)"></i>Diastolic</span></div>
  <div class="callout">Office readings can be <b>white-coat elevated</b> (anxiety in-clinic). The plan: confirm with a 7-day home cuff, and treating the sleep apnea may bring it down on its own — so monitor before any treatment.</div>
</div>"""

# ---------- optional liver-enzyme block ----------
liver_block = ""
le = BIO.get("liver_enzymes")
if le and le.get("series"):
    s = le["series"]
    alt_pts = [(mon_yy(r["date"]), r["alt"]) for r in s if "alt" in r]
    ggt_pts = [(mon_yy(r["date"]), r["ggt"]) for r in s if "ggt" in r]
    le_chart = line_chart([("ALT","var(--c-ldl)", alt_pts),("GGT","var(--c-apob)", ggt_pts)],
                          bands=[(0,44,"var(--c-good)"),(44,80,"var(--c-bad)")]) if len(alt_pts) > 2 else ""
    latest_alt = s[-1].get("alt")
    liver_block = f"""<div class="section">
  <h2>Liver enzymes — watch item</h2>
  <p class="lead">ALT history (ref &lt;44, green band): peaked <b>51 (high) in 2011</b>, settled to high-normal (28–33) through 2014, normal since (latest ALT {latest_alt} in 2025). AST/GGT always normal. This intermittent ALT pattern fits mild fatty liver (NAFLD) tied to your insulin-resistance markers and weight — <b>not currently diagnosed</b>, worth watching as weight comes down. Improving lipids/weight should keep it normal.</p>
  {le_chart}
  <div class="legend"><span><i style="background:var(--c-ldl)"></i>ALT (IU/L)</span><span><i style="background:var(--c-apob)"></i>GGT (IU/L)</span></div>
</div>"""

enh = "".join(f"<li>{e}</li>" for e in RISK["risk_enhancers"])
assum = "".join(f"<li>{a}</li>" for a in RISK["assumptions"])

corr = RISK["exercise_lipid_correlation"]
gen = RISK["generated"]

# ---------- momentum ("This Week") tab ----------
def checklist_groups(today):
    """The detailed daily accountability checklist. Aerobic varies by weekday; PT/supplements/
    health are daily; strength is generic and only on lift days."""
    wd = today.weekday()  # 0=Mon
    aerobic, is_run_day = aerobic_for(today)
    g = [
      {"name":"Aerobic","items":[{"id":"aerobic","label":aerobic}]},
      {"name":"PT — daily (right ankle is the focus, bilateral)","items":[
        {"id":"pt_sls","label":"Single-leg stand 3×30s each · eyes open then closed"},
        {"id":"pt_star","label":"Star/reach balance 2×5 each direction each foot"},
        {"id":"pt_evert","label":"Band ankle eversion 2×12 each (peroneals — highest value)"},
        {"id":"pt_calf","label":"Calf raises 3×8 each · flat floor, NO heel drop, 3s lower"},
        {"id":"pt_bridge","label":"Single-leg glute bridges 2×10 each"},
        {"id":"pt_mob","label":"Mobility: calf stretch + foot roll + McKenzie press-ups"},
      ]},
      {"name":"Supplements","items":[
        {"id":"sup_multi","label":"Multivitamin (AM, with food)"},
        {"id":"sup_omega","label":"Omega-3 (bedtime)"},
        {"id":"sup_k2","label":"Vitamin K2 / MK-7 (PM)"},
      ]},
      {"name":"Health & accountability","items":[
        {"id":"food","label":"🍽️ Food diary logged (Cronometer)"},
        {"id":"mouthtape","label":"😮‍💨 Mouth tape at night + check Oura SpO2"},
        {"id":"limits","label":"Alcohol / cannabis within limits"},
      ]},
      {"name":"Strength (generic — per plan)","items":[
        {"id":"strength","label":"Strength session (neutral-grip, wrist-safe)"}]},
    ]
    if is_run_day:  # only when today is actually a run (run-aware)
        g[3]["items"].insert(0, {"id":"pre_run_gate","label":"✅ Pre-run gate: ankle stable + Achilles OK"})
    if wd == 1:  # a BP-log reminder mid-week (light touch)
        g[3]["items"].append({"id":"bp","label":"🩺 BP reading (home cuff)"})
    return g

def build_checklist_section(today):
    groups = checklist_groups(today)
    all_ids = [it["id"] for grp in groups for it in grp["items"]]
    blocks = ""
    for grp in groups:
        rows = "".join(
            f'<label class="chk"><input type="checkbox" data-item="{it["id"]}"><span>{it["label"]}</span></label>'
            for it in grp["items"])
        blocks += f'<div class="chk-grp"><div class="chk-grp-h">{grp["name"]}</div>{rows}</div>'
    import json as _j
    return f"""<div class="section">
  <h2>Today's checklist <span id="chk-pct" class="chk-pct"></span></h2>
  <p class="lead">{today.strftime('%A, %b %-d')}. Tick these off as you go — they sync across your devices. <span id="chk-streak" style="color:var(--good)"></span></p>
  <div class="checklist">{blocks}</div>
  <div id="chk-status" class="chk-status"></div>
</div>
<script>window.CHK_DATE="{today.isoformat()}";window.CHK_IDS={_j.dumps(all_ids)};</script>"""

def build_calendar_pane(today):
    D = datetime.date
    race_w2w, race_tri = D(2026, 7, 26), D(2026, 9, 27)
    end = race_tri
    events = {
        "2026-07-26": ("🏁 Wharf to Wharf", "6 mi · start moved to 30th Ave & Portola"),
        "2026-09-27": ("🏁 Santa Cruz Triathlon", "Olympic 1.5k/40k/10k · confirm exact date"),
    }
    long_runs = {"2026-06-27":"4 mi","2026-07-04":"5 mi","2026-07-11":"6 mi — peak (the checkpoint)",
                 "2026-07-18":"4–5 mi (ease)","2026-07-25":"2–3 mi shakeout (taper)"}
    def phase(d):
        if d <= D(2026,7,26): return "Wharf to Wharf build"
        if d <= D(2026,8,9):  return "Reset + diet / CGM block"
        if d <= D(2026,9,20): return "Santa Cruz Tri build"
        return "Tri taper + race"
    def session(d):
        wd = d.weekday(); ph = phase(d); iso = d.isoformat()
        prev = (d - datetime.timedelta(days=1)).isoformat()
        # run-aware: show completed runs and never a run the day after one
        if iso in RUN_DATES:
            return "✓ Ran — easy spin / mobility"
        if iso in PLAN_OVERRIDE:
            return PLAN_OVERRIDE[iso][0]
        if prev in RUN_DATES:
            return "Recovery — Z2 ride / easy spin (no back-to-back runs)"
        base = {0:"Easy run 2–3 mi (≤139 bpm) + strength", 1:"Z2 endurance ride 60–90 min",
                2:"Easy run 2–3 mi (≤139 bpm) + core", 3:"Surf AM + easy spin",
                4:"Strength (legs light) + easy spin", 5:"Long session", 6:"Easy ride / road-gravel"}[wd]
        if wd == 5:
            base = (f"Long run {long_runs[iso]}" if iso in long_runs
                    else "Long brick (bike→run) / long ride 40–60k" if ph.startswith("Santa Cruz")
                    else "Long easy run/ride")
        if ph.startswith("Santa Cruz") and wd in (1, 3):
            base += " + open-water swim"
        return base
    # build week groups (Mon-anchored)
    start = today - datetime.timedelta(days=today.weekday())
    weeks, d = [], start
    while d <= end:
        wk_start = d; days = []
        for _ in range(7):
            if d > end: break
            ev = events.get(d.isoformat())
            days.append({"d": d, "session": session(d), "phase": phase(d), "event": ev,
                         "today": d == today, "past": d < today})
            d += datetime.timedelta(days=1)
        weeks.append({"start": wk_start, "phase": phase(days[0]["d"]), "days": days})
    # render
    blocks = ""
    for wk in weeks:
        rows = ""
        for x in wk["days"]:
            cls = "cal-row" + (" cal-today" if x["today"] else "") + (" cal-past" if x["past"] else "")
            evbadge = (f'<span class="cal-ev">{x["event"][0]}</span>' if x["event"] else "")
            evsub = (f' · <span style="color:var(--accent)">{x["event"][1]}</span>' if x["event"] else "")
            rows += (f'<div class="{cls}"><div class="cal-d"><b>{x["d"].strftime("%a")}</b> {x["d"].strftime("%b %-d")}</div>'
                     f'<div class="cal-s">{x["session"]}{evsub}<span class="cal-pt">PT</span></div>'
                     f'<div>{evbadge}</div></div>')
        wkly = wk["start"].strftime("%b %-d")
        blocks += f'<div class="section" style="padding:14px 18px"><div class="cal-wh">Week of {wkly} · <span style="color:var(--muted)">{wk["phase"]}</span></div>{rows}</div>'
    return f"""<div class="section">
  <h2>Calendar — through the Santa Cruz Tri</h2>
  <p class="lead">Your day-by-day plan: workout + daily PT, with race/event days flagged. Scroll ahead. Sessions follow the weekly skeleton; the long-run Saturdays ramp to the 6-mi W2W checkpoint, then bricks for the tri.</p>
</div>{blocks}""", True

def build_week_pane():
    if not TRACKER:
        return "", "", False
    T = TRACKER
    # consistency heatmap: weeks as columns, days as rows (GitHub-style)
    heat = T["heatmap"]; n = len(heat)
    weeks = (n + 6) // 7
    cell, gap = 13, 3
    w = 40 + weeks*(cell+gap); h = 30 + 7*(cell+gap)
    loads = [d["load"] for d in heat if d["load"] > 0]
    hi = max(loads) if loads else 1
    def shade(d):
        if not d["active"]: return "var(--grid)"
        if d["load"] <= 0: return "#2c4a3a"   # active but no load (walk/yoga)
        q = d["load"]/hi
        return "#1d5e3f" if q < .25 else "#2e8b57" if q < .5 else "#3ecf8e" if q < .8 else "#7fffd4"
    rects = []
    days_lbl = ["Mon","","Wed","","Fri","","Sun"]
    for i,d in enumerate(heat):
        col, row = i//7, i%7
        x, y = 40+col*(cell+gap), 24+row*(cell+gap)
        title = f'{d["date"]}: ' + (", ".join(d["kinds"]) if d["kinds"] else "rest") + (f' · load {d["load"]}' if d["load"] else "")
        rects.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2.5" fill="{shade(d)}" pointer-events="all" data-tip="{title}"/>')
    for r,lbl in enumerate(days_lbl):
        if lbl: rects.append(f'<text x="34" y="{24+r*(cell+gap)+10}" class="tick" text-anchor="end">{lbl}</text>')
    heatmap = f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" style="max-width:{w}px">{"".join(rects)}</svg>'

    bars = ""
    for c in T["compliance"]:
        col = "var(--good)" if c["pct"] >= 100 else "var(--accent)" if c["pct"] >= 50 else "var(--warn)"
        bars += f'''<div class="cbar"><div class="cbar-top"><span>{c["label"]}</span><b>{c["done"]}/{c["target"]}</b></div>
          <div class="cbar-track"><div class="cbar-fill" style="width:{c["pct"]}%;background:{col}"></div></div></div>'''

    scards = "".join([
        kpi("🔥 Active streak", T["streak_active_days"], "days", "good", "don't break the chain"),
        kpi("On plan this week", f'{T["overall_compliance"]}', "%", "good" if T["overall_compliance"]>=70 else "warn", f'week of {T["week_of"][5:]}'),
        kpi("Run-target weeks", T["weeks_run_target"], "", "good", "consecutive, 3 runs/wk"),
        kpi("This week", T["this_week"]["sessions"], "sessions", "good", f'{T["this_week"]["hours"]} h · load {T["this_week"]["load"]}'),
    ])
    pane = f"""
<div class="section">
  <h2>This week — {T['phase']}</h2>
  <p class="lead">Your daily check-in. Targets from the regimen; this updates as activities sync from Strava. Generated {T['generated']}.</p>
  <div class="kpis">{scards}</div>
  <div style="margin-top:18px" class="compliance">{bars}</div>
</div>
<div class="section">
  <h2>Consistency — last 16 weeks</h2>
  <p class="lead">One square per day, greener = more training load. The streak is the point: stack active days, keep the chain alive. Hover a square for detail.</p>
  {heatmap}
  <div class="legend"><span>Less</span><i style="background:var(--grid)"></i><i style="background:#1d5e3f"></i><i style="background:#2e8b57"></i><i style="background:#3ecf8e"></i><i style="background:#7fffd4"></i><span>More</span></div>
</div>"""
    return pane, scards, True

week_pane, _, has_week = build_week_pane()
week_pane = build_checklist_section(datetime.date.today()) + (week_pane or "")
has_week = True

# ---------- "Wharf to Wharf" tab ----------
def build_w2w_pane():
    if not W2W:
        return "", False
    W = W2W; jd = W["jog_discipline"]; man = W["manual"]
    # top KPIs
    cards = [
        kpi("Countdown", W["days_to_race"], "days", "good", "race day · Sun Jul 26"),
        kpi("Longest run", f'{W["longest_run"]:g}', "mi", "warn" if W["longest_pct"]<100 else "good", f'of 6.0 goal · {W["longest_pct"]}%'),
        kpi("This week", f'{W["week_miles"]:g}', "run mi", "good", f'{W["week_run_count"]} run(s)'),
        kpi("Jog discipline", f'{jd["runs_in_control"]}/{jd["runs_total"]}', "in Z2", "good" if jd["runs_in_control"]>=jd["runs_total"]/2 else "warn", "jogs ≤139 bpm"),
        kpi("PT streak", man["pt_streak"], "days", "good" if man["pt_streak"]>0 else "warn", "log it daily"),
        kpi("Achilles AM", (man["achilles_status"] or "—").replace("_"," "), "", "warn" if man["achilles_status"]=="sore_lingering" else "good", "morning status"),
    ]
    # longest-run progress bar
    prog = f'''<div class="cbar" style="margin-top:6px"><div class="cbar-top"><span>Longest run → 6.0 mi checkpoint</span><b>{W["longest_run"]:g}/6.0 mi</b></div>
      <div class="cbar-track"><div class="cbar-fill" style="width:{W["longest_pct"]}%;background:var(--accent)"></div></div></div>'''
    # jog-pace table
    rows = ""
    for r in jd["rows"]:
        ok = "var(--good)" if r["in_control"] else "var(--bad)"
        flag = "in control" if r["in_control"] else "too hot"
        rows += (f"<tr><td>{mon_yy(r['date'])[:3]} {r['date'][8:]}</td><td>{r['miles']:g}</td><td>{r['pace']}/mi</td>"
                 f"<td>{r['avg_hr_moving']}</td><td>{r['pct_zone2']}%</td><td>{r['max_hr']}</td>"
                 f"<td>{r['drift']:+d}</td><td style='color:{ok}'>{flag}</td></tr>")
    jog_table = (f"<table class='tbl'><thead><tr><th>Run</th><th>mi</th><th>pace</th><th>avg HR</th>"
                 f"<th>%Z2</th><th>max HR</th><th>drift</th><th>verdict</th></tr></thead><tbody>{rows}</tbody></table>")
    # injuries
    icards = ""
    for inj in sorted(W["injuries"], key=lambda x: x["priority"]):
        st = inj["status"]; col = {"recovering":"k-warn","managed":"k-good"}.get(st,"k-warn")
        rules = "".join(f"<li>{r}</li>" for r in inj["rules"])
        icards += f'''<div class="kpi {col}" style="min-width:240px"><div class="k-label">Priority {inj["priority"]} · {st}</div>
          <div style="font-weight:650;margin:3px 0 5px">{inj["label"]}</div>
          <ul class="enh" style="font-size:12px;margin:0;padding-left:16px">{rules}</ul></div>'''
    rehab = "".join(f'<li><b>{r["exercise"].replace("_"," ")}</b> — {r["dose"]}'
                    + (f' <span style="color:var(--muted)">({r["note"]})</span>' if r.get("note") else "") + '</li>'
                    for r in W["rehab_protocol"])
    log_note = ("" if man["has_log"] else
        '<div class="callout">The manual KPIs (Achilles status, PT streak, ankle L/R symmetry) populate once you log them — fill in <b>data/manual/w2w_log.csv</b> (30 sec/day).</div>')
    pane = f"""
<div class="section">
  <h2>Wharf to Wharf — {W["days_to_race"]} days out</h2>
  <p class="lead">Goal: {W["goal"]} <b>Tissue-led, not fitness-led</b> — the limiter is {W["limiter"]}. Start line: {W["start_line"]}.</p>
  <div class="kpis">{''.join(cards)}</div>
  {prog}
  {log_note}
</div>
<div class="section">
  <h2>Jog-pace discipline — the signature metric</h2>
  <p class="lead">Average pace lies (walk breaks drag it down). This is the avg HR of the <b>moving</b> portion and % of jog time in Zone 2 (≤{jd['z2_ceiling']} bpm), from Strava HR streams. <b>Drift</b> = 2nd-half minus 1st-half HR; positive = started too fast. The 6/19 run is the model; 6/8–6/10 ran into Zone 3–4.</p>
  {jog_table}
</div>
<div class="section">
  <h2>Injury constraints (these gate everything)</h2>
  <div class="kpis">{icards}</div>
</div>
<div class="section">
  <h2>Rehab protocol — do daily (bilateral, right is the focus)</h2>
  <ul class="enh">{rehab}</ul>
  <div class="callout">Ankle single-leg-stand symmetry (eyes closed): R {man['ankle_sls_right_s'] or '—'}s / L {man['ankle_sls_left_s'] or '—'}s{f" ({man['ankle_symmetry_pct']}% of left)" if man['ankle_symmetry_pct'] else ''} · hop test: {man['hop_test'] or 'not tested'}. Right catching up to left = stability returning.</div>
</div>"""
    return pane, True

w2w_pane, has_w2w = build_w2w_pane()
w2w_tab_btn = '<button class="tab" onclick="showTab(\'w2w\',this)">Wharf to Wharf</button>' if has_w2w else ''
w2w_tab_div = f'<div id="tab-w2w" class="pane">{w2w_pane}</div>' if has_w2w else ''
cal_pane, has_cal = build_calendar_pane(datetime.date.today())
cal_tab_btn = '<button class="tab" onclick="showTab(\'cal\',this)">Calendar</button>' if has_cal else ''
cal_tab_div = f'<div id="tab-cal" class="pane">{cal_pane}</div>' if has_cal else ''

HTML = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Betterlate · Demo User</title>
<style>
:root{{
  --bg:#0f1115; --panel:#171a21; --panel2:#1d212b; --ink:#e7ebf2; --muted:#9aa4b4;
  --line:#2a2f3a; --grid:#252a35; --accent:#5aa9ff;
  --good:#3ecf8e; --warn:#f5b94a; --bad:#ff6b6b;
  --c-good:#3ecf8e; --c-bad:#ff6b6b;
  --c-ldl:#ff6b6b; --c-apob:#ff9f43; --c-hdl:#3ecf8e; --c-tg:#f5b94a; --c-train:#5aa9ff;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}}
.wrap{{max-width:1040px;margin:0 auto;padding:32px 22px 80px}}
header h1{{margin:0 0 4px;font-size:26px;letter-spacing:-.4px}}
header .tagline{{color:var(--accent);font-size:13.5px;font-weight:600;margin:0 0 4px;letter-spacing:.2px}}
header .sub{{color:var(--muted);font-size:13.5px}}
.section{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:22px;margin:20px 0}}
.section h2{{margin:0 0 4px;font-size:18px}}
.section .lead{{color:var(--muted);font-size:13.5px;margin:0 0 16px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}}
.kpi{{background:var(--panel2);border:1px solid var(--line);border-left-width:4px;border-radius:11px;padding:13px 14px}}
.k-good{{border-left-color:var(--good)}} .k-warn{{border-left-color:var(--warn)}} .k-bad{{border-left-color:var(--bad)}}
.k-label{{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px}}
.k-val{{font-size:27px;font-weight:650;margin:3px 0}}
.k-unit{{font-size:13px;color:var(--muted);font-weight:400;margin-left:4px}}
.k-target{{font-size:11.5px;color:var(--muted)}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
@media(max-width:760px){{.grid2{{grid-template-columns:1fr}}}}
.chart{{width:100%;height:auto}}
.tick{{fill:var(--muted);font-size:10px}}
.legend{{display:flex;gap:16px;flex-wrap:wrap;font-size:12.5px;color:var(--muted);margin-top:6px}}
.legend i{{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;vertical-align:-1px}}
.tabs{{display:flex;gap:8px;margin:18px 0 4px;border-bottom:1px solid var(--line)}}
.tab{{background:none;border:none;color:var(--muted);font:600 14.5px inherit;padding:9px 16px;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px}}
.tab:hover{{color:var(--ink)}}
.tab.active{{color:var(--accent);border-bottom-color:var(--accent)}}
.pane{{display:none}} .pane.active{{display:block}}
@media print{{ .pane{{display:block!important}} .tabs,.foot{{display:none}} .section{{break-inside:avoid}} }}
.compliance{{display:grid;grid-template-columns:1fr 1fr;gap:12px 22px}}
@media(max-width:640px){{.compliance{{grid-template-columns:1fr}}}}
.cbar-top{{display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px}}
.cbar-top span{{text-transform:capitalize;color:var(--muted)}}
.cbar-track{{height:8px;background:var(--panel2);border-radius:5px;overflow:hidden}}
.cbar-fill{{height:100%;border-radius:5px;transition:width .3s}}
.chart rect[data-tip],.chart circle[data-tip]{{cursor:crosshair}}
.tip{{position:fixed;pointer-events:none;background:#11141a;border:1px solid var(--accent);color:var(--ink);padding:5px 10px;border-radius:8px;font-size:12.5px;font-weight:600;white-space:nowrap;opacity:0;transition:opacity .08s;z-index:9999;box-shadow:0 4px 14px rgba(0,0,0,.5)}}
.tip.on{{opacity:1}}
.checklist{{display:grid;grid-template-columns:1fr 1fr;gap:14px 26px}}
@media(max-width:720px){{.checklist{{grid-template-columns:1fr}}}}
.chk-grp-h{{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px;margin:4px 0 7px;font-weight:600}}
.chk{{display:flex;align-items:flex-start;gap:9px;padding:5px 0;cursor:pointer;font-size:13.5px;line-height:1.4}}
.chk input{{margin-top:2px;width:17px;height:17px;accent-color:var(--good);cursor:pointer;flex:none}}
.chk input:checked+span{{color:var(--muted);text-decoration:line-through}}
.chk-pct{{font-size:15px;font-weight:650;color:var(--good);margin-left:6px}}
.chk-status{{font-size:12px;color:var(--muted);margin-top:12px}}
.cal-wh{{font-size:12.5px;font-weight:600;margin:0 0 8px;padding-bottom:6px;border-bottom:1px solid var(--line)}}
.cal-row{{display:grid;grid-template-columns:96px 1fr auto;gap:12px;align-items:center;padding:7px 0;border-bottom:1px solid var(--line);font-size:13.5px}}
.cal-row:last-child{{border-bottom:none}}
.cal-d{{color:var(--muted);font-size:12.5px}} .cal-d b{{color:var(--ink)}}
.cal-today{{background:rgba(90,169,255,.08);margin:0 -10px;padding:7px 10px;border-radius:8px;border-bottom:none}}
.cal-past{{opacity:.45}}
.cal-pt{{display:inline-block;background:var(--panel2);border:1px solid var(--line);color:var(--muted);font-size:10.5px;padding:1px 7px;border-radius:10px;margin-left:8px;vertical-align:1px}}
.cal-ev{{display:inline-block;background:var(--accent);color:#001;font-weight:700;font-size:11.5px;padding:2px 9px;border-radius:20px;white-space:nowrap}}
.tbl{{width:100%;border-collapse:collapse;font-size:13px}}
.tbl th,.tbl td{{padding:7px 9px;border-bottom:1px solid var(--line);text-align:right}}
.tbl th:first-child,.tbl td:first-child{{text-align:left}}
.tbl th{{color:var(--muted);font-weight:600;font-size:11.5px;text-transform:uppercase;letter-spacing:.3px}}
.tbl td.sm,.tbl td.sm{{font-size:11.5px;color:var(--muted);text-align:left}}
.ytd{{font-size:9px;background:var(--accent);color:#001;padding:1px 5px;border-radius:6px;vertical-align:middle}}
.bignum{{font-size:40px;font-weight:700;line-height:1}}
.flag{{color:var(--bad);font-weight:600}}
ul.enh{{margin:6px 0 0;padding-left:18px}} ul.enh li{{margin:6px 0}}
.callout{{background:var(--panel2);border:1px solid var(--line);border-radius:11px;padding:14px 16px;margin-top:14px;font-size:13.5px}}
.callout b{{color:var(--accent)}}
.pill{{display:inline-block;background:var(--panel2);border:1px solid var(--line);border-radius:20px;padding:3px 11px;font-size:12px;color:var(--muted);margin:2px 4px 2px 0}}
a{{color:var(--accent)}}
.foot{{color:var(--muted);font-size:12px;margin-top:30px;text-align:center}}
</style></head><body><div class="wrap">
<header>
  <h1>Betterlate</h1>
  <div class="tagline">Better late than never · a cardiovascular health 360</div>
  <div class="sub">Demo User · age {RISK['age']} · generated {gen} · sources: {len(BIO['panels'])} lab panels (2020–2026), {FIT['n_activities']} Strava activities ({FIT['date_range'][0]}→{FIT['date_range'][1]})</div>
</header>

<div class="tabs">
  <button class="tab active" onclick="showTab('week',this)">This Week</button>
  {cal_tab_btn}
  {w2w_tab_btn}
  <button class="tab" onclick="showTab('overview',this)">360 Overview</button>
</div>

<div id="tab-week" class="pane active">{week_pane if has_week else '<div class="section"><p class="lead">Run build_tracker.py to populate this tab.</p></div>'}</div>

{cal_tab_div}

{w2w_tab_div}

<div id="tab-overview" class="pane">

<div class="section">
  <h2>Where things stand now</h2>
  <p class="lead">Latest values — most recent panel {latest['date']} ({latest['source']}).</p>
  <div class="kpis">{''.join(kpis)}</div>
</div>

<div class="section">
  <h2>Cardiovascular risk</h2>
  <div class="grid2">
    <div>
      <div class="bignum" style="color:var(--good)">{RISK['ascvd_10yr_pct']}%</div>
      <div style="color:var(--muted);font-size:13px">10-yr ASCVD by Pooled Cohort Equations — <b>{RISK['ascvd_category']}</b></div>
      <div class="callout">{RISK['ascvd_note']}</div>
      <div class="callout"><b>Bottom line:</b> {RISK['lifetime_risk_note']}</div>
    </div>
    <div>
      <div style="font-size:13px;color:var(--muted);margin-bottom:4px">Risk enhancers present in the user's data:</div>
      <ul class="enh">{enh}</ul>
    </div>
  </div>
</div>

<div class="section">
  <h2>Lipid trajectory</h2>
  <p class="lead">The two markers that matter most here — LDL-C and ApoB (atherogenic particle burden). Green band = goal zone, red band = high.</p>
  <div>{lipid_chart}
    <div class="legend"><span><i style="background:var(--c-ldl)"></i>LDL-C</span><span><i style="background:var(--c-apob)"></i>ApoB</span></div>
  </div>
  <div style="margin-top:18px">{hdl_chart}
    <div class="legend"><span><i style="background:var(--c-hdl)"></i>HDL-C</span><span><i style="background:var(--c-tg)"></i>Triglycerides</span></div>
  </div>
</div>

<div class="section">
  <h2>Exercise ↔ lipids: your own correlation</h2>
  <p class="lead">Annual moderate-to-vigorous training (bars) vs <b>triglycerides</b> (line) — the lipid most responsive to exercise + diet. In your data the correlations are: training vs triglycerides <b>r = {corr['pearson_mvpa_vs_triglycerides']}</b>, vs LDL <b>r = {corr.get('pearson_mvpa_vs_ldl','—')}</b>, vs HDL <b>r = {corr['pearson_mvpa_vs_hdl']}</b>. (HDL showed the strongest link, but triglycerides is the more clinically important marker, so it's charted here — honest about the weaker fit.)</p>
  {ex_chart}
  <div class="legend"><span><i style="background:var(--c-train)"></i>MVPA min/week</span><span><i style="background:var(--c-tg)"></i>Triglycerides</span></div>
  <div class="callout">{corr['interpretation']}</div>
</div>

{garmin_block}

{sutter_bp_block}

{apple_section}

{oura_section}

{cgm_section}

{liver_block}

<div class="section">
  <h2>Biomarker timeline</h2>
  {bio_table()}
</div>

<div class="section">
  <h2>Training history</h2>
  <p class="lead">Zones: {FIT['zones'].get('source','')} · Zone-2 floor {FIT['zones']['z2_lower_bpm']} bpm · vigorous {FIT['zones']['vigorous_lower_bpm']} bpm · observed HRmax {FIT['hrmax_observed']}. {LIVE.get('recent_6wk_note','')}</p>
  {fit_table()}
</div>

<div class="section">
  <h2>Data gaps to close for a true 360</h2>
  <ul class="enh">{assum}</ul>
  <div style="margin-top:10px">
    <span class="pill">Blood pressure (home cuff, 7-day avg)</span>
    <span class="pill">Coronary artery calcium (CAC) score</span>
    <span class="pill">Repeat ApoB + NMR LDL-P</span>
    <span class="pill">Sutter Health records (ECG, echo, visit notes)</span>
    <span class="pill">VO2max / resting HR (Oura/Strava)</span>
    <span class="pill">Body composition (DEXA)</span>
    <span class="pill">Apple Health daily steps & sleep</span>
  </div>
  <div class="callout">Plans &amp; docs: <b>regimen.md</b> (week-by-week race + reboot, W2W Jul 26, SC Tri ~Sep); <b>cardiovascular_program.md</b> (intervention plan); <b>visit_agenda.md</b> (next doctor visit); <b>supplements_routine.md</b> (daily supplement checklist); <b>DATA_ACQUISITION.md</b> (pull remaining data); <b>REPLICATE.md</b> (how someone else can build their own).</div>
</div>

</div><!-- /tab-overview -->

<div class="foot">Personal health analytics · not medical advice · discuss changes with your physician.</div>
<script>
function showTab(id, btn){{
  document.querySelectorAll('.pane').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.getElementById('tab-'+id).classList.add('active');
  btn.classList.add('active');
  if(history.replaceState) history.replaceState(null,'','#'+id);
}}
if(location.hash){{
  var id=location.hash.slice(1);
  var b=[].slice.call(document.querySelectorAll('.tab')).find(function(t){{return (t.getAttribute('onclick')||'').indexOf("'"+id+"'")>-1;}});
  if(b) b.click();
}}
// daily checklist — last-write-wins across devices (each toggle carries a timestamp; tombstones sync unchecks)
(function(){{
  if(!document.querySelector('.checklist')) return;
  var DATE=window.CHK_DATE;
  function TOK(){{return localStorage.getItem('bl_tok');}}
  function lsGet(){{ var o; try{{o=JSON.parse(localStorage.getItem('bl_chk')||'{{}}');}}catch(e){{o={{}};}}
    Object.keys(o).forEach(function(f){{ if(typeof o[f]!=='object'||o[f]===null){{ o[f]={{t:0,v:o[f]?1:0}}; }} }});  // migrate old {{field:1}}
    return o; }}
  function lsSet(s){{ localStorage.setItem('bl_chk', JSON.stringify(s)); }}
  function parseVal(s){{ if(s==null) return null; s=String(s); var i=s.indexOf(':');
    if(i>-1) return {{t:(+s.slice(0,i))||0, v:(+s.slice(i+1))?1:0}}; return {{t:0, v:s?1:0}}; }}  // old "1" -> t:0
  function postField(f,on,ts){{ var t=TOK(); if(!t) return;
    fetch('/api/checklist',{{method:'POST',headers:{{Authorization:'Bearer '+t,'Content-Type':'application/json'}},body:JSON.stringify({{field:f,checked:on?1:0,ts:ts}})}}).catch(function(){{}});
  }}
  var boxes=[].slice.call(document.querySelectorAll('.chk input[data-item]'));
  function fieldOf(cb){{ return DATE+':'+cb.getAttribute('data-item'); }}
  function render(){{
    var done=boxes.filter(function(x){{return x.checked;}}).length;
    var pct=boxes.length?Math.round(100*done/boxes.length):0;
    document.getElementById('chk-pct').textContent=done+'/'+boxes.length+' · '+pct+'%';
  }}
  function streak(s){{
    var byDate={{}}; Object.keys(s).forEach(function(f){{ if(s[f]&&s[f].v===1){{var d=f.split(':')[0]; byDate[d]=(byDate[d]||0)+1;}} }});
    function key(dt){{return dt.toISOString().slice(0,10);}}
    var day=new Date(DATE+'T12:00:00'), n=0;
    if(!byDate[key(day)]) day.setDate(day.getDate()-1);
    while((byDate[key(day)]||0)>=5){{ n++; day.setDate(day.getDate()-1); }}
    document.getElementById('chk-streak').textContent = n>0 ? ('🔥 '+n+'-day streak — keep the chain alive') : '';
  }}
  function applyLocal(){{ var s=lsGet(); boxes.forEach(function(cb){{ var e=s[fieldOf(cb)]; cb.checked=!!(e&&e.v===1); }}); render(); streak(s); }}
  function setStatus(ok){{ document.getElementById('chk-status').textContent= ok ? '✓ Synced across your devices.' : 'Saved on this device.'; }}
  // 1) render immediately from localStorage — durable, survives every refresh
  applyLocal();
  boxes.forEach(function(cb){{
    cb.addEventListener('change',function(){{
      var s=lsGet(), f=fieldOf(cb), ts=Date.now();
      s[f]={{t:ts, v:cb.checked?1:0}}; lsSet(s); render(); streak(s); postField(f,cb.checked,ts);
    }});
  }});
  // 2) reconcile with backend: per field, the newest timestamp wins (check OR uncheck)
  var t=TOK();
  if(t){{
    fetch('/api/checklist',{{headers:{{Authorization:'Bearer '+t}}}})
     .then(function(r){{ if(!r.ok) throw 0; return r.json(); }})
     .then(function(d){{
        setStatus(true);
        var raw=d.state||{{}}, local=lsGet(), merged={{}}, fields={{}};
        Object.keys(raw).forEach(function(f){{fields[f]=1;}}); Object.keys(local).forEach(function(f){{fields[f]=1;}});
        Object.keys(fields).forEach(function(f){{
          var b=parseVal(raw[f]), l=local[f]||null;
          var pick = (!l) ? b : (!b ? l : (l.t>=b.t ? l : b));
          merged[f]=pick;
          if(l && (!b || l.t>b.t)) postField(f, l.v===1, l.t);  // local newer -> propagate
        }});
        lsSet(merged); applyLocal();
     }})
     .catch(function(){{ setStatus(false); }});
  }} else setStatus(false);
}})();
// interactive chart tooltips (data-tip on points/bars/cells) — follows the cursor
(function(){{
  var tip=document.createElement('div'); tip.className='tip'; document.body.appendChild(tip);
  function move(e){{ tip.style.left=(e.clientX+14)+'px'; tip.style.top=(e.clientY+14)+'px'; }}
  document.addEventListener('mouseover',function(e){{
    var t=e.target&&e.target.getAttribute&&e.target.getAttribute('data-tip');
    if(t){{ tip.textContent=t; tip.classList.add('on'); move(e); }}
  }});
  document.addEventListener('mousemove',function(e){{ if(tip.classList.contains('on')) move(e); }});
  document.addEventListener('mouseout',function(e){{
    if(e.target&&e.target.getAttribute&&e.target.getAttribute('data-tip')) tip.classList.remove('on');
  }});
}})();
</script>
</div></body></html>"""

OUT.write_text(HTML)
print(f"Wrote {OUT}  ({len(HTML)//1024} KB)")
