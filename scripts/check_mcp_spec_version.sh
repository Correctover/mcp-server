#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MCP Protocol Spec Version Monitor
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Monitors MCP spec + SDK releases for updates.
# When a new version is detected, writes a signal file.
#
# Sources:
#   https://github.com/modelcontextprotocol/modelcontextprotocol/releases
#   https://github.com/modelcontextprotocol/typescript-sdk
#   https://github.com/modelcontextprotocol/go-sdk
#
# Cron (weekly, Monday 9am local):
#   0 9 * * 1 /path/to/check_mcp_spec_version.sh
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
STATE_FILE="$REPO_DIR/.mcp-version-state"
SIGNAL_FILE="$REPO_DIR/.mcp-version-updated"
LOGFILE="$REPO_DIR/mcp-spec-monitor.log"

PYTHON=""
for cmd in python python3; do
  if command -v "$cmd" &>/dev/null; then
    PYTHON="$cmd"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "[ERROR] Python not found — cannot parse GitHub API responses." | tee -a "$LOGFILE"
  exit 1
fi

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOGFILE"
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. Fetch latest spec release from GitHub API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

fetch_github_release() {
  local repo="$1"
  curl -sL --max-time 10 "https://api.github.com/repos/$repo/releases/latest" 2>/dev/null | "$PYTHON" -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('tag_name', 'unknown'))
    print(d.get('published_at', '')[:10])
    print(d.get('html_url', ''))
except:
    print('fetch_failed')
    print('')
    print('')
" 2>/dev/null | tr -d '\r' || { echo -e "fetch_failed\n\n"; }
}

log "=== MCP Spec Version Check ==="

# ── Spec core ──
readarray -t SPEC < <(fetch_github_release "modelcontextprotocol/modelcontextprotocol")
SPEC_VERSION="${SPEC[0]}"
SPEC_DATE="${SPEC[1]}"
SPEC_URL="${SPEC[2]}"
log "Spec: $SPEC_VERSION ($SPEC_DATE)"

# ── TypeScript SDK ──
readarray -t TS < <(fetch_github_release "modelcontextprotocol/typescript-sdk")
TS_VERSION="${TS[0]}"
TS_DATE="${TS[1]}"
log "TS SDK: $TS_VERSION ($TS_DATE)"

# ── Go SDK ──
readarray -t GO < <(fetch_github_release "modelcontextprotocol/go-sdk")
GO_VERSION="${GO[0]}"
GO_DATE="${GO[1]}"
log "Go SDK: $GO_VERSION ($GO_DATE)"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. Compare with stored state
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

NEW_STATE="spec=${SPEC_VERSION}|spec_date=${SPEC_DATE}|ts=${TS_VERSION}|ts_date=${TS_DATE}|go=${GO_VERSION}|go_date=${GO_DATE}|checked=$(date '+%Y-%m-%d')"

if [ -f "$STATE_FILE" ]; then
  OLD_STATE=$(cat "$STATE_FILE")
  if [ "$NEW_STATE" != "$OLD_STATE" ]; then
    log "⚠️  MCP spec version CHANGED!"
    echo "MCP 协议版本更新！" > "$SIGNAL_FILE"
    echo "  Spec: $SPEC_VERSION (was: $(echo "$OLD_STATE" | cut -d'|' -f1 | cut -d= -f2))" >> "$SIGNAL_FILE"
    echo "  Released: $SPEC_DATE" >> "$SIGNAL_FILE"
    echo "  URL: $SPEC_URL" >> "$SIGNAL_FILE"
    echo "  TS SDK: $TS_VERSION ($TS_DATE)" >> "$SIGNAL_FILE"
    echo "  Go SDK: $GO_VERSION ($GO_DATE)" >> "$SIGNAL_FILE"
    echo "$NEW_STATE" > "$STATE_FILE"
  else
    log "No change detected."
    rm -f "$SIGNAL_FILE"
  fi
else
  log "First run — storing initial state."
  echo "$NEW_STATE" > "$STATE_FILE"
fi

log "Done."
