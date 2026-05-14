#!/usr/bin/env bash
# Set the Status of a roadmap issue on the statectl Project v2 board.
# Usage: set-status.sh <issue-number> <todo|in-progress|done>
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "usage: $0 <issue-number> <todo|in-progress|done>" >&2
  exit 2
fi

N=$1
STATUS=$2

PROJ_ID=PVT_kwHOAArJt84BXrjL
STATUS_FIELD=PVTSSF_lAHOAArJt84BXrjLzhS2yIE

case "$STATUS" in
  todo)        OPT=f75ad846 ;;
  in-progress) OPT=47fc9ee4 ;;
  done)        OPT=98236657 ;;
  *) echo "status must be one of: todo, in-progress, done" >&2; exit 2 ;;
esac

ITEM_ID=$(gh api graphql -f query='
query {
  user(login:"PerArneng") {
    projectV2(number:1) {
      items(first:100) { nodes { id content { ... on Issue { number } } } }
    }
  }
}' | jq -r --argjson n "$N" '.data.user.projectV2.items.nodes[] | select(.content.number==$n) | .id')

if [ -z "$ITEM_ID" ] || [ "$ITEM_ID" = "null" ]; then
  echo "issue #$N is not on the project board — run add-to-board.sh first" >&2
  exit 1
fi

gh project item-edit \
  --project-id "$PROJ_ID" \
  --id "$ITEM_ID" \
  --field-id "$STATUS_FIELD" \
  --single-select-option-id "$OPT" > /dev/null

echo "#$N → $STATUS"
