#!/usr/bin/env bash
# Add an existing issue to the roadmap board: sets Tier + Kind + Status=Todo,
# and applies the matching issue labels.
# Usage: add-to-board.sh <issue-number> <tier> <kind>
#   tier: cap | 1 | 2 | 3 | 4 | 5 | 6
#   kind: cap | sc        (cap=Capability, sc=State changer)
set -euo pipefail

if [ $# -ne 3 ]; then
  echo "usage: $0 <issue-number> <cap|1|2|3|4|5|6> <cap|sc>" >&2
  exit 2
fi

N=$1
TIER=$2
KIND=$3

PROJ_ID=PVT_kwHOAArJt84BXrjL
TIER_FIELD=PVTSSF_lAHOAArJt84BXrjLzhS2yLg
KIND_FIELD=PVTSSF_lAHOAArJt84BXrjLzhS2yLk
STATUS_FIELD=PVTSSF_lAHOAArJt84BXrjLzhS2yIE
TODO=f75ad846

case "$TIER" in
  cap) TIER_OPT=549db4a3; TIER_LBL=tier-cap ;;
  1)   TIER_OPT=6ad8225a; TIER_LBL=tier-1 ;;
  2)   TIER_OPT=1971fbaf; TIER_LBL=tier-2 ;;
  3)   TIER_OPT=05687cd6; TIER_LBL=tier-3 ;;
  4)   TIER_OPT=4e8ca854; TIER_LBL=tier-4 ;;
  5)   TIER_OPT=c2d7ea55; TIER_LBL=tier-5 ;;
  6)   TIER_OPT=d37b6572; TIER_LBL=tier-6 ;;
  *) echo "tier must be cap|1|2|3|4|5|6" >&2; exit 2 ;;
esac

case "$KIND" in
  cap) KIND_OPT=44a0039a; KIND_LBL="kind:capability" ;;
  sc)  KIND_OPT=5c1a9572; KIND_LBL="kind:state-changer" ;;
  *) echo "kind must be cap|sc" >&2; exit 2 ;;
esac

URL="https://github.com/PerArneng/statectl/issues/$N"
ITEM_ID=$(gh project item-add 1 --owner PerArneng --url "$URL" --format json | jq -r .id)

gh project item-edit --project-id "$PROJ_ID" --id "$ITEM_ID" \
  --field-id "$TIER_FIELD"   --single-select-option-id "$TIER_OPT"   > /dev/null
gh project item-edit --project-id "$PROJ_ID" --id "$ITEM_ID" \
  --field-id "$KIND_FIELD"   --single-select-option-id "$KIND_OPT"   > /dev/null
gh project item-edit --project-id "$PROJ_ID" --id "$ITEM_ID" \
  --field-id "$STATUS_FIELD" --single-select-option-id "$TODO"       > /dev/null

gh issue edit "$N" --repo PerArneng/statectl \
  --add-label "$KIND_LBL" --add-label "$TIER_LBL" > /dev/null

echo "added #$N (tier=$TIER_LBL kind=$KIND_LBL status=Todo)"
