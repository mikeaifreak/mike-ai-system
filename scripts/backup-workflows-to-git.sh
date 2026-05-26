#!/usr/bin/env bash
# =============================================================================
# backup-workflows-to-git.sh
#
# Exports ALL n8n workflows to the correct folder inside n8n/workflows/,
# then commits and pushes to GitHub.
#
# Called by the n8n "Backup to GitHub" workflow OR manually.
#
# Usage:
#   ./scripts/backup-workflows-to-git.sh
#
# Required env vars (loaded from .env if present):
#   N8N_BASE_URL, N8N_API_KEY, GITHUB_TOKEN, GITHUB_REPO, GITHUB_BRANCH
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKFLOWS_DIR="$REPO_ROOT/n8n/workflows"

# Load .env if present (non-CI environments)
if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$REPO_ROOT/.env"
  set +a
fi

# ---- Validate required vars --------------------------------------------------
: "${N8N_BASE_URL:?N8N_BASE_URL is required}"
: "${N8N_API_KEY:?N8N_API_KEY is required}"

# ---- Helpers -----------------------------------------------------------------
log()  { echo "[$(date '+%H:%M:%S')] $*"; }
die()  { echo "[ERROR] $*" >&2; exit 1; }

# Maps n8n workflow tags → subfolder names.
# First matching tag wins; untagged workflows land in shared/.
tag_to_folder() {
  local tags="$1"
  for tag in finance product-research creative whatsapp shared; do
    if echo "$tags" | grep -qi "$tag"; then
      echo "$tag"
      return
    fi
  done
  echo "shared"
}

# Slugify a workflow name into a safe filename.
slugify() {
  echo "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-\|-$//g'
}

# ---- Export all workflows from n8n API ---------------------------------------
log "Fetching workflow list from $N8N_BASE_URL ..."

WORKFLOWS_JSON=$(curl -fsSL \
  -H "X-N8N-API-KEY: $N8N_API_KEY" \
  "$N8N_BASE_URL/api/v1/workflows?limit=250")

TOTAL=$(echo "$WORKFLOWS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('data', [])))")
log "Found $TOTAL workflows."

if [[ "$TOTAL" -eq 0 ]]; then
  log "No workflows found — nothing to back up."
  exit 0
fi

EXPORTED=0
FAILED=0

while IFS= read -r WORKFLOW_ID; do
  WF_JSON=$(curl -fsSL \
    -H "X-N8N-API-KEY: $N8N_API_KEY" \
    "$N8N_BASE_URL/api/v1/workflows/$WORKFLOW_ID")

  WF_NAME=$(echo "$WF_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('name','unknown'))")
  WF_TAGS=$(echo "$WF_JSON" | python3 -c "
import sys, json
d = json.load(sys.stdin)
tags = [t.get('name','') for t in d.get('tags', [])]
print(','.join(tags))
")

  FOLDER=$(tag_to_folder "$WF_TAGS")
  SLUG=$(slugify "$WF_NAME")
  TARGET_DIR="$WORKFLOWS_DIR/$FOLDER"
  TARGET_FILE="$TARGET_DIR/$SLUG.json"

  mkdir -p "$TARGET_DIR"

  # Pretty-print the JSON for clean diffs
  echo "$WF_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
# Strip volatile runtime fields that create noisy diffs
for field in ('updatedAt', 'createdAt', 'triggerCount', 'staticData'):
    data.pop(field, None)
print(json.dumps(data, indent=2, ensure_ascii=False))
" > "$TARGET_FILE"

  log "  ✓ [$FOLDER] $WF_NAME → $SLUG.json"
  (( EXPORTED++ )) || true

done < <(echo "$WORKFLOWS_JSON" | python3 -c "
import sys, json
for wf in json.load(sys.stdin).get('data', []):
    print(wf['id'])
")

log "Exported $EXPORTED workflows ($FAILED failures)."

# ---- Git commit & push -------------------------------------------------------
cd "$REPO_ROOT"

if ! git diff --quiet || git ls-files --others --exclude-standard n8n/workflows/ | grep -q .; then
  git add n8n/workflows/
  TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S UTC')
  git commit -m "chore(backup): auto-export $EXPORTED workflows — $TIMESTAMP"
  log "Committed $EXPORTED workflow files."

  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    # Inject token into remote URL for CI/automated runs
    REMOTE_URL=$(git remote get-url origin)
    AUTHED_URL=$(echo "$REMOTE_URL" | sed "s|https://|https://$GITHUB_TOKEN@|")
    git push "$AUTHED_URL" HEAD:"${GITHUB_BRANCH:-main}"
    log "Pushed to GitHub (branch: ${GITHUB_BRANCH:-main})."
  else
    git push
    log "Pushed to GitHub."
  fi
else
  log "No workflow changes detected — nothing to commit."
fi

log "Backup complete."
