#!/bin/bash
# Betterlate daily auto-refresh: pull live Strava + Oura + Apple Health, rebuild, redeploy.
# Run by launchd (com.betterlate.refresh) once daily; safe to run by hand anytime.
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
PROJ="/path/to/betterlate"
cd "$PROJ" || exit 1
mkdir -p logs
LOG="$PROJ/logs/refresh.log"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

log "=== refresh start ==="
python3 code/strava_pull.py        >>"$LOG" 2>&1 || log "WARN strava_pull failed"
python3 code/build_oura.py         >>"$LOG" 2>&1 || log "WARN oura"
python3 code/build_apple_health.py >>"$LOG" 2>&1 || log "WARN apple_health"
python3 code/build_google_health.py >>"$LOG" 2>&1 || log "WARN google_health"
python3 code/build_w2w.py          >>"$LOG" 2>&1 || log "WARN w2w"
python3 code/build_tracker.py      >>"$LOG" 2>&1 || log "WARN tracker"
python3 code/build_vo2max.py       >>"$LOG" 2>&1 || log "WARN vo2max"
python3 code/build_risk.py         >>"$LOG" 2>&1 || log "WARN risk"
python3 code/build_dashboard.py    >>"$LOG" 2>&1 || log "WARN dashboard"
python3 code/build_vercel.py       >>"$LOG" 2>&1 || log "WARN vercel-pkg"
if (cd deploy && vercel --prod --scope your-vercel-scope --yes >>"$LOG" 2>&1); then
  log "deployed OK"
else
  log "WARN deploy failed"
fi
log "=== refresh done ==="
