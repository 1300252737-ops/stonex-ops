#!/usr/bin/env bash
# Push a message to a Discord webhook.
#
# Usage:
#   DISCORD_URL="https://discord.com/api/webhooks/..." ./push-discord.sh < message.md
#   echo "Hello" | DISCORD_URL="..." ./push-discord.sh
#
# The message is read from stdin.  Max 2000 characters per Discord embed;
# longer messages are split into multiple embeds.
#
# Environment variable:
#   DISCORD_URL         Webhook URL (required).  Can also be set via .env.

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$DIR/../.env"

# Load .env if present
if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

URL="${DISCORD_URL:-}"
if [[ -z "$URL" ]]; then
  echo "ERROR: DISCORD_URL is not set. Provide it via env or .env file." >&2
  exit 1
fi

CONTENT=$(cat)

# Split into chunks if too long (Discord limit ~2000 per message)
while [[ -n "$CONTENT" ]]; do
  chunk="${CONTENT:0:1999}"
  CONTENT="${CONTENT:1999}"

  payload=$(cat <<EOF
{
  "content": $(echo "$chunk" | jq -Rs '.'),
  "username": "StoneX Daily Ops"
}
EOF
)

  response=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$URL" \
    -H "Content-Type: application/json" \
    -d "$payload")

  if [[ "$response" != "204" ]]; then
    echo "ERROR: Discord returned HTTP $response" >&2
    exit 1
  fi

  # Rate-limit safety
  sleep 0.5
done
