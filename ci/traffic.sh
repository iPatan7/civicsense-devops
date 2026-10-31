#!/bin/sh
# Sends requests to an environment for a while and counts the answers, to show
# whether users notice a deployment or a rollback.
#
#   ci/traffic.sh http://localhost:8092 120 [log-file]
#
# Every 0.1 s it requests the home page and one stylesheet. Each answer is written
# to the log file as "<seconds since start> <path> <status>"; a summary follows.
URL=${1%/} DURATION=${2:-60} LOG=${3:-/dev/null}
css=$(curl -s "$URL/" | grep -o '/static/[^"]*\.css' | head -1)
start=$(date +%s.%N); end=$(awk -v s="$start" -v d="$DURATION" 'BEGIN { printf "%.3f", s + d }')
: > "$LOG"
while [ "$(awk -v e="$end" -v n="$(date +%s.%N)" 'BEGIN { print (n < e) }')" = 1 ]; do
  for path in / "$css"; do
    code=$(curl -s -o /dev/null -m 5 -w '%{http_code}' "$URL$path")
    echo "$(awk -v s="$start" -v n="$(date +%s.%N)" 'BEGIN { printf "%.2f", n - s }') $path $code" >> "$LOG"
  done
  sleep 0.1
done
awk '{ n++; c[$3]++; if ($3 != 200) { bad++; if (!first) first = $1; last = $1 } }
     END { printf "traffic: %d requests, %d OK, %d failed", n, c[200], bad;
           for (k in c) if (k != 200) printf ", %d x HTTP %s", c[k], k;
           if (bad) printf " (between t=%ss and t=%ss)", first, last; print "" }' "$LOG"
