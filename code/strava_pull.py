#!/usr/bin/env python3
"""Pull live Strava data into the pipeline (for the daily auto-refresh).

Uses the stored OAuth refresh token (data/strava-live/strava_api.json) to:
  * pull recent activities  -> data/strava-live/recent.json   (build_tracker reads this)
  * pull HR streams for recent runs -> data/processed/w2w_runs.json
    (per-run avg HR while moving, % time in Zone 2 ≤139 — the jog-pace-discipline metric)

Replaces the manual MCP pulls. Run before the build scripts in refresh.sh.
"""
import json, time, datetime, urllib.request, urllib.parse, statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "data" / "strava-live" / "strava_api.json"
RECENT = ROOT / "data" / "strava-live" / "recent.json"
W2W_RUNS = ROOT / "data" / "processed" / "w2w_runs.json"
Z2 = 139
API = "https://www.strava.com/api/v3"

def api_get(path, token, **params):
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    return json.load(urllib.request.urlopen(req, timeout=30))

def access_token():
    cfg = json.loads(CFG.read_text())
    data = urllib.parse.urlencode({
        "client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
        "refresh_token": cfg["refresh_token"], "grant_type": "refresh_token"}).encode()
    tok = json.load(urllib.request.urlopen(
        urllib.request.Request("https://www.strava.com/oauth/token", data=data), timeout=30))
    if tok.get("refresh_token") and tok["refresh_token"] != cfg["refresh_token"]:
        cfg["refresh_token"] = tok["refresh_token"]
        CFG.write_text(json.dumps(cfg, indent=2))  # Strava rotates refresh tokens
    return tok["access_token"]

def pace(moving_s, miles):
    s = moving_s / miles; return f"{int(s//60)}:{int(s%60):02d}"

def main():
    today = datetime.date.today()
    tok = access_token()
    after = int(time.mktime((today - datetime.timedelta(days=60)).timetuple()))

    # ---- recent activities -> recent.json ----
    acts, page = [], 1
    while True:
        batch = api_get("/athlete/activities", tok, per_page=100, after=after, page=page)
        if not batch:
            break
        acts.extend(batch); page += 1
        if len(batch) < 100:
            break
    recent = [{"date": a["start_date_local"][:10], "type": a["sport_type"],
               "moving_s": a.get("moving_time", 0), "dist_m": round(a.get("distance", 0)),
               "rel_effort": a.get("suffer_score") or 0} for a in acts]
    RECENT.write_text(json.dumps({"synced": today.isoformat(), "source": "Strava API",
                                  "activities": recent}, indent=2))

    # ---- HR streams for recent runs (last 40 days) -> w2w_runs.json ----
    cutoff = (today - datetime.timedelta(days=40)).isoformat()
    runs = [a for a in acts if a["sport_type"] == "Run" and a["start_date_local"][:10] >= cutoff]
    runs.sort(key=lambda a: a["start_date_local"])
    out = []
    for a in runs:
        try:
            s = api_get(f"/activities/{a['id']}/streams", tok, keys="heartrate,moving", key_by_type="true")
        except Exception:
            continue
        hr = s.get("heartrate", {}).get("data") or []
        mv = s.get("moving", {}).get("data") or [True]*len(hr)
        moving_hr = [h for h, m in zip(hr, mv) if m and h]
        if not moving_hr:
            continue
        miles = a["distance"] / 1609.34; n = len(moving_hr); half = n // 2
        out.append({
            "date": a["start_date_local"][:10], "miles": round(miles, 2),
            "pace": pace(a["moving_time"], miles),
            "avg_hr_moving": round(statistics.mean(moving_hr)),
            "pct_zone2": round(100 * sum(1 for h in moving_hr if h <= Z2) / n),
            "max_hr": max(moving_hr),
            "drift": round(statistics.mean(moving_hr[half:]) - statistics.mean(moving_hr[:half])),
            "in_control": statistics.mean(moving_hr) <= Z2 and (100*sum(1 for h in moving_hr if h<=Z2)/n) >= 50,
        })
    W2W_RUNS.write_text(json.dumps({"generated": today.isoformat(), "z2_ceiling": Z2, "runs": out}, indent=2))

    print(f"Strava pull: {len(recent)} activities (60d) -> recent.json; {len(out)} runs w/ HR -> w2w_runs.json")
    for r in out[-4:]:
        print(f"  {r['date']} {r['miles']}mi {r['pace']}/mi  avgHR {r['avg_hr_moving']} {r['pct_zone2']}%Z2  {'ok' if r['in_control'] else 'hot'}")

if __name__ == "__main__":
    main()
