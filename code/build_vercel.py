#!/usr/bin/env python3
"""Package the dashboard as a token-gated Vercel app (private hosting of PHI).

Architecture (so health data is NEVER in a public file):
  deploy/public/index.html  — public shell: prompts for a token, fetches the dashboard
  deploy/api/dashboard.js    — serverless function: returns the dashboard ONLY if the
                               token matches process.env.DASHBOARD_TOKEN (set in Vercel,
                               never in code). The full dashboard HTML is embedded here
                               base64-encoded, so it is only ever served through the
                               token check — it is not a static asset.

Re-run after each dashboard rebuild, then redeploy (`vercel --prod`).
"""
import base64, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "report" / "index.html"
DEPLOY = ROOT / "deploy"

html = SRC.read_text()
b64 = base64.b64encode(html.encode("utf-8")).decode("ascii")
(DEPLOY / "api").mkdir(parents=True, exist_ok=True)
(DEPLOY / "public").mkdir(parents=True, exist_ok=True)

# ---- serverless function: token-gated data ----
FUNC = '''// Token-gated dashboard. The health data is embedded base64 below and is only
// returned when the request carries the correct token (Vercel env var DASHBOARD_TOKEN).
export default function handler(req, res) {
  const auth = req.headers.authorization || "";
  const token = auth.replace(/^Bearer\\s+/i, "") || (req.query && req.query.token) || "";
  const expected = process.env.DASHBOARD_TOKEN || "";
  if (!expected || !timingSafeEqual(token, expected)) {
    res.setHeader("Cache-Control", "no-store");
    res.status(401).json({ error: "unauthorized" });
    return;
  }
  const out = Buffer.from(HTML_B64, "base64").toString("utf8");
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("X-Robots-Tag", "noindex");
  res.status(200).send(out);
}
function timingSafeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}
const HTML_B64 = "%s";
''' % b64
(DEPLOY / "api" / "dashboard.js").write_text(FUNC)

# ---- checklist state function: token-gated, backed by Upstash Redis (Vercel KV) ----
CHK = '''// Daily-checklist state, token-gated, persisted in Upstash Redis (Vercel KV).
// GET  -> { state: { "YYYY-MM-DD:item": 1, ... } }
// POST { field, checked } -> sets/clears one item.
// If no KV store is configured yet, returns 503 so the dashboard falls back to localStorage.
const KEY = "betterlate:checklist";
const URL = process.env.KV_REST_API_URL || process.env.UPSTASH_REDIS_REST_URL;
const TOKEN = process.env.KV_REST_API_TOKEN || process.env.UPSTASH_REDIS_REST_TOKEN;

async function redis(cmd) {
  const r = await fetch(URL, {
    method: "POST",
    headers: { Authorization: "Bearer " + TOKEN, "Content-Type": "application/json" },
    body: JSON.stringify(cmd),
  });
  if (!r.ok) throw new Error("redis " + r.status);
  return (await r.json()).result;
}
function timingSafeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let x = 0; for (let i = 0; i < a.length; i++) x |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return x === 0;
}
export default async function handler(req, res) {
  const auth = req.headers.authorization || "";
  const token = auth.replace(/^Bearer\\s+/i, "");
  if (!timingSafeEqual(token, process.env.DASHBOARD_TOKEN || "")) {
    return res.status(401).json({ error: "unauthorized" });
  }
  if (!URL || !TOKEN) return res.status(503).json({ error: "no store configured" });
  res.setHeader("Cache-Control", "no-store");
  try {
    if (req.method === "POST") {
      const body = typeof req.body === "string" ? JSON.parse(req.body || "{}") : (req.body || {});
      const field = String(body.field || "");
      if (!field) return res.status(400).json({ error: "field required" });
      const ts = Number(body.ts) || Date.now();
      // store "ts:state" — tombstone (state 0) on uncheck so deletes sync (last-write-wins)
      await redis(["HSET", KEY, field, ts + ":" + (body.checked ? 1 : 0)]);
      return res.status(200).json({ ok: true });
    }
    const flat = (await redis(["HGETALL", KEY])) || [];
    const state = {};
    for (let i = 0; i < flat.length; i += 2) state[flat[i]] = flat[i + 1]; // raw "ts:state"
    return res.status(200).json({ state });
  } catch (e) {
    return res.status(500).json({ error: String(e.message || e) });
  }
}
'''
(DEPLOY / "api" / "checklist.js").write_text(CHK)

# ---- public shell (no PHI) ----
SHELL = '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Betterlate</title>
<style>
  html,body{height:100%;margin:0}
  body{background:#0f1115;color:#e7ebf2;font:15px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
       display:flex;align-items:center;justify-content:center}
  .card{width:min(360px,88vw);text-align:center}
  h1{font-size:30px;margin:0 0 2px;letter-spacing:-.5px}
  .tag{color:#5aa9ff;font-weight:600;font-size:13px;margin-bottom:22px}
  input{width:100%;box-sizing:border-box;padding:12px 14px;border-radius:10px;border:1px solid #2a2f3a;
        background:#171a21;color:#e7ebf2;font-size:15px;margin-bottom:10px}
  button{width:100%;padding:12px;border:none;border-radius:10px;background:#5aa9ff;color:#001;
         font-weight:650;font-size:15px;cursor:pointer}
  .err{color:#ff6b6b;font-size:13px;height:18px;margin-top:10px}
  .muted{color:#9aa4b4;font-size:12px;margin-top:18px}
</style></head><body>
<div class="card" id="card">
  <h1>Betterlate</h1>
  <div class="tag">cardiovascular health 360</div>
  <input id="tok" type="password" placeholder="Access token" autocomplete="current-password"
         onkeydown="if(event.key==='Enter')go()">
  <button onclick="go()">View dashboard</button>
  <div class="err" id="err"></div>
  <div class="muted">Private. The data only loads with a valid token.</div>
</div>
<script>
async function load(token){
  const r = await fetch("/api/dashboard", { headers: { "Authorization": "Bearer " + token } });
  if (r.status !== 200) { localStorage.removeItem("bl_tok"); throw new Error("bad"); }
  const html = await r.text();
  localStorage.setItem("bl_tok", token);
  document.open(); document.write(html); document.close();
}
function go(){
  const t = document.getElementById("tok").value.trim();
  if (!t) return;
  document.getElementById("err").textContent = "";
  load(t).catch(() => { document.getElementById("err").textContent = "Incorrect token"; });
}
const saved = localStorage.getItem("bl_tok");
if (saved) load(saved).catch(() => {});
</script></body></html>
'''
(DEPLOY / "public" / "index.html").write_text(SHELL)

# ---- config + minimal package.json ----
(DEPLOY / "vercel.json").write_text('{\n  "cleanUrls": true,\n  "headers": [\n'
    '    { "source": "/(.*)", "headers": [ { "key": "X-Robots-Tag", "value": "noindex" } ] }\n  ]\n}\n')
(DEPLOY / "package.json").write_text('{\n  "name": "betterlate",\n  "private": true,\n  "version": "1.0.0"\n}\n')

# ---- deploy instructions ----
(DEPLOY / "DEPLOY.md").write_text(f"""# Deploy Betterlate (private, token-gated)

Generated {datetime.date.today().isoformat()}. Embedded dashboard: {len(html)//1024} KB.

## One-time setup (use your PERSONAL Vercel account, not the business one)

1. Install the CLI and log into your **personal** account:
   ```bash
   npm i -g vercel
   vercel login          # pick your personal email/account
   ```
2. From this `deploy/` folder, deploy once to create the project:
   ```bash
   cd deploy && vercel
   ```
   (Accept defaults; framework = Other. When asked the scope, choose your **personal** account.)
3. Pick a strong token and set it as a secret env var (do NOT put it in code):
   ```bash
   openssl rand -base64 24            # copy the output — this is your token
   vercel env add DASHBOARD_TOKEN     # paste it; choose Production (and Preview if you want)
   ```
4. Deploy to production:
   ```bash
   vercel --prod
   ```
5. Open the URL, enter the token once (it's remembered on that device). Share the URL + token
   with anyone you choose; they enter it once too. For the doctor, send the PDFs instead.

## Updating the data later
```bash
# from the project root, after syncing data:
python3 code/build_tracker.py && python3 code/build_dashboard.py && python3 code/build_vercel.py
cd deploy && vercel --prod
```

## Rotating / revoking the token
```bash
vercel env rm DASHBOARD_TOKEN && vercel env add DASHBOARD_TOKEN   # set a new value
vercel --prod
```
Everyone re-enters the new token next time; the old one stops working.

## Enable cloud-synced checklist (cross-device + shared users)
The daily checklist works on each device via localStorage out of the box. To **sync check-offs across
your phone/laptop** (and feed real streaks), add a free Redis store — the `api/checklist.js` function
auto-detects it:
1. Vercel dashboard → your **betterlate** project → **Storage** → **Create Database** →
   **Upstash for Redis** (or "KV") → Free tier → **Connect** to the betterlate project.
   This auto-injects `KV_REST_API_URL` + `KV_REST_API_TOKEN` env vars.
2. Redeploy: `cd deploy && vercel --prod --scope your-vercel-scope`
3. The checklist status line will switch from "Saved on this device" to "✓ Synced across your devices."
No store yet = it quietly uses localStorage (per-device); nothing breaks.

## Notes
- The health data lives only inside `api/dashboard.js` and is returned only on a valid token —
  the public `index.html` shell contains no PHI.
- `noindex` headers keep it out of search engines.
- This is a single shared token (fine for a few trusted people). If you ever need per-person logins with
  individual revocation, switch to Cloudflare Pages + Access instead.
""")

print(f"Wrote {DEPLOY}/ (shell + token-gated function, dashboard {len(html)//1024} KB)")
print("Files:")
for p in sorted(DEPLOY.rglob("*")):
    if p.is_file():
        print(f"  {p.relative_to(ROOT)}  ({p.stat().st_size//1024} KB)" if p.stat().st_size > 1024
              else f"  {p.relative_to(ROOT)}")
