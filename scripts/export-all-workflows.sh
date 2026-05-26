#!/usr/bin/env bash
# =============================================================================
# export-all-workflows.sh
#
# Export all workflows from n8n into the correct n8n/workflows/<folder>/ path.
# Does NOT commit to git — use backup-workflows-to-git.sh for that.
#
# Usage:
#   ./scripts/export-all-workflows.sh
#   ./scripts/export-all-workflows.sh --folder finance   # one folder only
#   ./scripts/export-all-workflows.sh --active-only      # skip inactive
#
# Outputs:  n8n/workflows/<folder>/<workflow-slug>.json
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
ACTIVE_ONLY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --folder)      FILTER_FOLDER="$2"; shift 2 ;;
    --active-only) ACTIVE_ONLY=true; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

log() { echo "[$(date '+%H:%M:%S')] $*"; }

tag_to_folder() {
  local tags="$1"
  for tag in finance product-research creative whatsapp shared; do
    if echo "$tags" | grep -qi "$tag"; then echo "$tag"; return; fi
  done
  echo "shared"
}

slugify() {
  echo "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-\|-$//g'
}

log "Fetching workflows from $N8N_BASE_URL ..."

RESPONSE=$(curl -fsSL \
  -H "X-N8N-API-KEY: $N8N_API_KEY" \
  "$N8N_BASE_URL/api/v1/workflows?limit=250")

EXPORTED=0

while IFS=$'\t' read -r WF_ID WF_ACTIVE; do
  if $ACTIVE_ONLY && [[ "$WF_ACTIVE" != "true" ]]; then
    continue
  fi

  WF_JSON=$(curl -fsSL \
    -H "X-N8N-API-KEY: $N8N_API_KEY" \
    "$N8N_BASE_URL/api/v1/workflows/$WF_ID")

  WF_NAME=$(echo "$WF_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('name','unknown'))")
  WF_TAGS=$(echo "$WF_JSON" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(','.join(t.get('name','') for t in d.get('tags', [])))
")

  FOLDER=$(tag_to_folder "$WF_TAGS")

  # Apply folder filter if set
  if [[ -n "$FILTER_FOLDER" && "$FOLDER" != "$FILTER_FOLDER" ]]; then
    continue
  fi

  SLUG=$(slugify "$WF_NAME")
  TARGET="$WORKFLOWS_DIR/$FOLDER/$SLUG.json"
  mkdir -p "$WORKFLOWS_DIR/$FOLDER"

  echo "$WF_JSON" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for f in ('updatedAt', 'createdAt', 'triggerCount', 'staticData'):
    d.pop(f, None)
print(json.dumps(d, indent=2, ensure_ascii=False))
" > "$TARGET"

  log "  ✓ [$FOLDER] $WF_NAME"
  (( EXPORTED++ )) || true

done < <(echo "$RESPONSE" | python3 -c "
import sys, json
for wf in json.load(sys.stdin).get('data', []):
    print(wf['id'] + '\t' + str(wf.get('active', False)).lower())
")

log "Exported $EXPORTED workflows to $WORKFLOWS_DIR"
