#!/usr/bin/env bash
# List items on the roadmap board, optionally filtered by status.
# Usage: list-board.sh [todo|in-progress|done]
set -euo pipefail

FILTER=${1:-}

gh api graphql -f query='
query {
  user(login:"PerArneng") {
    projectV2(number:1) {
      items(first:100) {
        nodes {
          content { ... on Issue { number title state } }
          fieldValues(first:10) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                field { ... on ProjectV2SingleSelectField { name } }
                name
              }
            }
          }
        }
      }
    }
  }
}' | jq -r --arg f "$FILTER" '
  .data.user.projectV2.items.nodes
  | map({
      n:      .content.number,
      title:  .content.title,
      status: (.fieldValues.nodes | map(select(.field.name=="Status")) | .[0].name // "—"),
      tier:   (.fieldValues.nodes | map(select(.field.name=="Tier"))   | .[0].name // "—")
    })
  | map(select($f=="" or (.status|ascii_downcase|gsub(" ";"-")) == $f))
  | sort_by(.n)
  | (["#","STATUS","TIER","TITLE"], ["-","-","-","-"], (.[] | [.n, .status, .tier, .title]))
  | @tsv' | column -t -s$'\t'
