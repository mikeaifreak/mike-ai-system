#!/usr/bin/env bash
# =============================================================================
# restore-workflows-from-git.sh
#
# Pulls the latest workflow JSONs from GitHub and imports them into n8n.
#
# Safe to run repeatedly — n8n CLI uses workflow IDs for deduplication:
#   • If the workflow ID already exists → UPDATE in place
#   • If the workflow ID does not exist → CREATE new
#
# Usage:
#   ./scripts/restore-workflows-from-git.sh [--folder finance]
#
# Options:
#   --folder <name>   Restore only one subfolder (finance, whatsapp, etc.)
#   --dry-run         List files that WOULD be imported, then exit
#
# Required env vars:
#   N8N_BASE_URL, N8N_API_KEY
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKFLOWS_DIR="$REPO_ROOT/n8n/workflows"

# Load .env if present
if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$REPO_ROOT/.env"
  set +a
fi

: "${N8N_BASE_URL:?N8N_BASE_URL is required}"
: "${N8N_API_KEY:?N8N_API_KEY is required}"

FILTER_FOLDER=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --folder) FILTER_FOLDER="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

log()  { echo "[$(date '+%H:%M:%S')] $*"; }
warn() { echo "[WARN]  $*" >&2; }

# ---- Pull latest from GitHub -------------------------------------------------
log "Pulling latest from GitHub..."
cd "$REPO_ROOT"
git pull --rebase origin "${GITHUB_BRANCH:-main}" 2>/dev/null || {
  warn "git pull failed — using local files as-is."
}

# ---- Find workflow files to import -------------------------------------------
if [[ -n "$FILTER_FOLDER" ]]; then
  SEARCH_PATH="$WORKFLOWS_DIR/$FILTER_FOLDER"
  [[ -d "$SEARCH_PATH" ]] || { echo "Folder not found: $SEARCH_PATH" >&2; exit 1; }
else
  SEARCH_PATH="$WORKFLOWS_DIR"
fi

WORKFLOW_FILES=()
while IFS= read -r -d '' f; do
  WORKFLOW_FILES+=("$f")
done < <(find "$SEARCH_PATH" -name "*.json" -not -name ".gitkeep" -print0 | sort -z)

log "Found ${#WORKFLOW_FILES[@]} workflow files to import."

if $DRY_RUN; then
  log "--- DRY RUN — files that would be imported: ---"
  for f in "${WORKFLOW_FILES[@]}"; do
    echo "  $f"
  done
  exit 0
fi

# ---- Import each workflow via n8n REST API -----------------------------------
IMPORTED=0
FAILED=0

for WF_FILE in "${WORKFLOW_FILES[@]}"; do
  WF_NAME=$(python3 -c "
import json, sys
d = json.load(open('$WF_FILE'))
print(d.get('name', 'unknown'))
" 2>/dev/null || echo "unknown")

  WF_ID=$(python3 -c "
import json, sys
d = json.load(open('$WF_FILE'))
print(d.get('id', ''))
" 2>/dev/null || echo "")

  # Check if workflow already exists in n8n
  EXISTING_STATUS=0
  if [[ -n "$WF_ID" ]]; then
    EXISTING_STATUS=$(curl -o /dev/null -s -w "%{http_code}" \
      -H "X-N8N-API-KEY: $N8N_API_KEY" \
      "$N8N_BASE_URL/api/v1/workflows/$WF_ID")
  fi

  if [[ "$EXISTING_STATUS" == "200" ]]; then
    # Update existing workflow (preserve active state)
    HTTP_STATUS=$(curl -o /dev/null -s -w "%{http_code}" \
      -X PATCH \
      -H "X-N8N-API-KEY: $N8N_API_KEY" \
      -H "Content-Type: application/json" \
      -d @"$WF_FILE" \
      "$N8N_BASE_URL/api/v1/workflows/$WF_ID")
    ACTION="updated"
  else
    # Create new workflow
    HTTP_STATUS=$(curl -o /dev/null -s -w "%{http_code}" \
      -X POST \
      -H "X-N8N-API-KEY: $N8N_API_KEY" \
      -H "Content-Type: application/json" \
      -d @"$WF_FILE" \
      "$N8N_BASE_URL/api/v1/workflows")
    ACTION="created"
  fi

  if [[ "$HTTP_STATUS" =~ ^2 ]]; then
    log "  ✓ $ACTION: $WF_NAME"
    (( IMPORTED++ )) || true
  else
    warn "  ✗ FAILED (HTTP $HTTP_STATUS): $WF_NAME — $WF_FILE"
    (( FAILED++ )) || true
  fi
done

log "Restore complete: $IMPORTED imported, $FAILED failed."
[[ "$FAILED" -eq 0 ]] || exit 1
