#!/usr/bin/env bash
# =============================================================================
# import-all-workflows.sh
#
# Import all workflow JSONs from n8n/workflows/ into n8n.
# Delegates to restore-workflows-from-git.sh (which handles upsert logic).
#
# Usage:
#   ./scripts/import-all-workflows.sh
#   ./scripts/import-all-workflows.sh --folder finance
#   ./scripts/import-all-workflows.sh --dry-run
#
# This script is the "quick import" alias — it skips the git pull step.
# For a full disaster-recovery restore (git pull + import), use:
#   ./scripts/restore-workflows-from-git.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKFLOWS_DIR="$REPO_ROOT/n8n/workflows"

if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a; source "$REPO_ROOT/.env"; set +a
fi

: "${N8N_BASE_URL:?N8N_BASE_URL is required}"
: "${N8N_API_KEY:?N8N_API_KEY is required}"

FILTER_FOLDER=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --folder)  FILTER_FOLDER="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

log()  { echo "[$(date '+%H:%M:%S')] $*"; }
warn() { echo "[WARN]  $*" >&2; }

# ---- Resolve files to import -------------------------------------------------
if [[ -n "$FILTER_FOLDER" ]]; then
  SEARCH_PATH="$WORKFLOWS_DIR/$FILTER_FOLDER"
  [[ -d "$SEARCH_PATH" ]] || { echo "Folder not found: $SEARCH_PATH" >&2; exit 1; }
else
  SEARCH_PATH="$WORKFLOWS_DIR"
fi

mapfile -d '' WORKFLOW_FILES < <(find "$SEARCH_PATH" -name "*.json" -print0 | sort -z)
log "Found ${#WORKFLOW_FILES[@]} workflow JSON files."

if $DRY_RUN; then
  for f in "${WORKFLOW_FILES[@]}"; do echo "  $f"; done
  exit 0
fi

# ---- Import ------------------------------------------------------------------
IMPORTED=0; FAILED=0

for WF_FILE in "${WORKFLOW_FILES[@]}"; do
  WF_NAME=$(python3 -c "import json; print(json.load(open('$WF_FILE')).get('name','unknown'))" 2>/dev/null || echo "unknown")
  WF_ID=$(python3   -c "import json; print(json.load(open('$WF_FILE')).get('id',''))"          2>/dev/null || echo "")

  STATUS=0
  [[ -n "$WF_ID" ]] && STATUS=$(curl -o /dev/null -s -w "%{http_code}" \
    -H "X-N8N-API-KEY: $N8N_API_KEY" "$N8N_BASE_URL/api/v1/workflows/$WF_ID")

  if [[ "$STATUS" == "200" ]]; then
    CODE=$(curl -o /dev/null -s -w "%{http_code}" -X PATCH \
      -H "X-N8N-API-KEY: $N8N_API_KEY" -H "Content-Type: application/json" \
      -d @"$WF_FILE" "$N8N_BASE_URL/api/v1/workflows/$WF_ID")
    ACTION="updated"
  else
    CODE=$(curl -o /dev/null -s -w "%{http_code}" -X POST \
      -H "X-N8N-API-KEY: $N8N_API_KEY" -H "Content-Type: application/json" \
      -d @"$WF_FILE" "$N8N_BASE_URL/api/v1/workflows")
    ACTION="created"
  fi

  if [[ "$CODE" =~ ^2 ]]; then
    log "  ✓ $ACTION: $WF_NAME"
    (( IMPORTED++ )) || true
  else
    warn "  ✗ FAILED (HTTP $CODE): $WF_NAME"
    (( FAILED++ )) || true
  fi
done

log "Import complete: $IMPORTED workflows imported, $FAILED failed."
[[ "$FAILED" -eq 0 ]] || exit 1
