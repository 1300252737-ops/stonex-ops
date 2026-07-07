#!/usr/bin/env bash
# Install crontab entries for stonex-ops alert (probe + Feishu push on failure).
# Run this on the server after deploying the stonex-ops code.
#
# Usage: sudo -u <user> bash scripts/setup-alert-cron.sh
# Or:    scp scripts/setup-alert-cron.sh <host>:/tmp/ && ssh <host> bash /tmp/setup-alert-cron.sh

set -euo pipefail

OPS_BIN="${STONEX_OPS_BIN:-/stonex/bin/stonex-ops}"
STONX_BIN="${STONX_BIN:-/stonex/bin/stonx}"
ENV="${STONEX_ENV:-main}"
PATH_ROOT="${STONEX_PATH:-/stonex}"
LOG_DIR="${STONEX_OPS_LOG_DIR:-/stonex/ops/logs}"
CHAT_ID="${FEISHU_CHAT_ID:-}"

TMPFILE=$(mktemp)
trap 'rm -f "$TMPFILE"' EXIT

# Capture existing crontab (may be empty).
crontab -l 2>/dev/null > "$TMPFILE" || true

# Remove any previous stonex-ops alert entries to avoid duplicates.
sed -i.bak '/stonex-ops alert/d' "$TMPFILE" && rm -f "$TMPFILE.bak"

# Build the cron command.
CRON_CMD="$OPS_BIN alert --tenant default --env $ENV --path $PATH_ROOT --stonx-bin $STONX_BIN"
if [ -n "$CHAT_ID" ]; then
  CRON_CMD="FEISHU_CHAT_ID=$CHAT_ID $CRON_CMD"
fi

# Add entry: run at minute 5 past every hour.
echo "5 * * * * $CRON_CMD >> $LOG_DIR/alert.log 2>&1" >> "$TMPFILE"

# Also probe other active tenants if they exist.
# Tenant: tn_d746376e5594df939357 (currently paused — uncomment when active)
# echo "5 * * * * $OPS_BIN alert --tenant tn_d746376e5594df939357 --env $ENV --path $PATH_ROOT --stonx-bin $STONX_BIN >> $LOG_DIR/alert.log 2>&1" >> "$TMPFILE"

# Ensure log directory exists.
mkdir -p "$LOG_DIR"

crontab "$TMPFILE"

echo "Crontab updated. Current entries:"
crontab -l
