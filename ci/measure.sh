#!/bin/sh
# Runs a deployment or a rollback while ci/traffic.sh sends requests to the same
# environment, and reports how many requests failed. Used to measure whether a
# release is noticed by users.
#
#   ci/measure.sh <staging|production> <image|rollback> <log-file> [seconds]
set -u
ENV_NAME=$1 TARGET=$2 LOG=$3 SECONDS_=${4:-75}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/deploy/env/$ENV_NAME.env"
"$ROOT/ci/traffic.sh" "http://localhost:$PUBLIC_PORT" "$SECONDS_" "$LOG" > "$LOG.summary" 2>&1 &
TRAFFIC=$!
sleep 5                                   # some normal traffic before the change
t=$(date +%s.%N)
"$ROOT/ci/deploy.sh" "$ENV_NAME" "$TARGET"
status=$?
awk -v a="$t" -v b="$(date +%s.%N)" 'BEGIN { printf "deploy.sh finished with status %d after %.1f s\n", '"$status"', b - a }'
wait "$TRAFFIC"
cat "$LOG.summary"
exit $status
