#!/bin/sh
# Blue-green deployment of one CivicSense environment.
#
#   ci/deploy.sh <staging|production> <image>      deploy a release
#   ci/deploy.sh <staging|production> rollback     switch back to the other slot
#   ci/deploy.sh <staging|production> status       show which slot is live
#
# Every environment has two web slots, blue and green, behind one nginx. A new
# release is started in the idle slot and checked there while users are still
# served by the live slot. Only then is nginx pointed at the new slot, with a
# graceful reload. The previous slot keeps running, so a rollback is one more
# switch. If the smoke test fails after the switch, the switch is undone at once.
set -eu
[ $# -eq 2 ] || { echo "usage: $0 <staging|production> <image|rollback|status>"; exit 2; }
ENV_NAME=$1 TARGET=$2
ROOT=$(cd "$(dirname "$0")/.." && pwd)
CONF="$ROOT/deploy/env/$ENV_NAME.env"
[ -f "$CONF" ] || { echo "unknown environment: $ENV_NAME"; exit 2; }
. "$CONF"
STATE_DIR="${CIVIC_STATE:-$HOME/.civicsense}/$ENV_NAME"
export STATE_DIR
mkdir -p "$STATE_DIR/nginx"

# Secrets are created once per environment and live outside the repository.
if [ ! -f "$STATE_DIR/secrets.env" ]; then
  (umask 077; {
    echo "DJANGO_SECRET_KEY=$(openssl rand -hex 32)"
    echo "DB_PASSWORD=$(openssl rand -hex 16)"
    echo "DB_ROOT_PASSWORD=$(openssl rand -hex 16)"
  } > "$STATE_DIR/secrets.env")
fi

dc() { docker compose -p "$PROJECT" -f "$ROOT/deploy/compose.yml" \
         --env-file "$CONF" --env-file "$STATE_DIR/secrets.env" "$@"; }
log() { printf '[%s] %s\n' "$(date +%T)" "$*"; }
now() { date +%s.%N; }
since() { awk -v a="$1" -v b="$(now)" 'BEGIN { printf "%.1f", b - a }'; }
other() { [ "$1" = blue ] && echo green || echo blue; }
live_slot() { sed -n 's/.*server web-\([a-z]*\):8000.*/\1/p' "$STATE_DIR/nginx/live.conf" 2>/dev/null || true; }
state() { docker inspect -f '{{.State.Health.Status}}' "$PROJECT-web-$1-1" 2>/dev/null || echo stopped; }
healthy() { [ "$(state "$1")" = healthy ]; }

switch_to() {   # point nginx at a slot, reload it gracefully, wait until users get that slot
  printf 'upstream civic_web {\n    server web-%s:8000;\n}\n' "$1" > "$STATE_DIR/nginx/live.conf.new"
  mv "$STATE_DIR/nginx/live.conf.new" "$STATE_DIR/nginx/live.conf"
  if [ -n "$(dc ps -q nginx 2>/dev/null)" ]; then
    dc exec -T nginx nginx -t -q && dc exec -T nginx nginx -s reload 2>/dev/null
  else
    dc up -d --no-deps nginx >/dev/null 2>&1
  fi
  # "nginx -s reload" returns before the new worker processes have taken over,
  # so wait until the public address really answers from the new slot.
  i=0
  until curl -fsS -m 2 "http://localhost:$PUBLIC_PORT/healthz" 2>/dev/null | grep -q "\"slot\": \"$1\""; do
    i=$((i + 1)); [ $i -lt 100 ] || { log "nginx does not answer from slot $1"; return 1; }; sleep 0.1
  done
}

record() { echo "$(date '+%F %T') $ENV_NAME $*" >> "$STATE_DIR/history.log"; }

LIVE=$(live_slot)

case "$TARGET" in
status)
  echo "$ENV_NAME: live slot ${LIVE:-none}"
  for s in blue green; do
    printf '  %-5s %-28s %s\n' "$s" "$(cat "$STATE_DIR/slot-$s" 2>/dev/null || echo -)" "$(state "$s" | tail -1)"
  done
  exit 0 ;;
rollback)
  [ -n "$LIVE" ] || { echo "$ENV_NAME has never been deployed"; exit 1; }
  BACK=$(other "$LIVE")
  healthy "$BACK" || { echo "slot $BACK is not running and healthy, nothing to roll back to"; exit 1; }
  grep -q failed "$STATE_DIR/slot-$BACK" 2>/dev/null && { echo "slot $BACK holds a failed release, not rolling back to it"; exit 1; }
  t=$(now); switch_to "$BACK"
  log "$ENV_NAME rolled back: $LIVE -> $BACK ($(cat "$STATE_DIR/slot-$BACK")) in $(since "$t") s"
  record "rollback $LIVE -> $BACK $(cat "$STATE_DIR/slot-$BACK")"
  exit 0 ;;
esac

IMAGE=$TARGET RELEASE=${TARGET#*:}
NEW=blue; [ "$LIVE" = blue ] && NEW=green
SLOT=$(echo "$NEW" | tr a-z A-Z)
export "WEB_${SLOT}_IMAGE=$IMAGE" "WEB_${SLOT}_RELEASE=$RELEASE"
cp "$ROOT/deploy/nginx.conf" "$STATE_DIR/nginx/default.conf"
log "$ENV_NAME: live slot ${LIVE:-none}, starting $IMAGE in slot $NEW"
T0=$(now)

dc up -d --wait db >/dev/null 2>&1
t=$(now)
if ! dc up -d --no-deps --wait --wait-timeout 240 "web-$NEW" >/dev/null 2>&1; then
  log "slot $NEW did not become healthy; live slot ${LIVE:-none} untouched"
  dc logs --tail 30 "web-$NEW"; record "FAILED start $IMAGE in $NEW"; exit 1
fi
log "slot $NEW healthy after $(since "$t") s (migrations and static files included)"

# Check the new slot directly, before any user is sent to it.
dc exec -T "web-$NEW" curl -fsS -H "Host: localhost" http://localhost:8000/healthz | grep -q "\"release\": \"$RELEASE\"" \
  && dc exec -T "web-$NEW" curl -fsS -o /dev/null -H "Host: localhost" http://localhost:8000/ \
  || { log "slot $NEW answers wrongly; live slot ${LIVE:-none} untouched"; record "FAILED check $IMAGE in $NEW"; exit 1; }
log "slot $NEW serves release $RELEASE"

# First deployment of an environment: load the demonstration data once.
if [ "$(dc exec -T "web-$NEW" python manage.py shell -c 'from complaints.models import Complaint; print(Complaint.objects.count())' 2>/dev/null | tail -1)" = 0 ]; then
  log "empty database: loading the demonstration data"
  dc exec -T "web-$NEW" python manage.py seed_demo --reset >/dev/null
fi

t=$(now); switch_to "$NEW" || true
log "nginx switched ${LIVE:-none} -> $NEW in $(since "$t") s"

if ! "$ROOT/ci/smoke.sh" "http://localhost:$PUBLIC_PORT" "$RELEASE"; then
  if [ -n "$LIVE" ] && healthy "$LIVE"; then
    t=$(now); switch_to "$LIVE"
    log "smoke test failed: rolled back to slot $LIVE ($(cat "$STATE_DIR/slot-$LIVE")) in $(since "$t") s"
    record "ROLLED BACK $IMAGE in $NEW -> $LIVE"
    echo "$IMAGE (failed)" > "$STATE_DIR/slot-$NEW"
  else
    log "smoke test failed and there is no previous release to go back to"
    record "FAILED smoke $IMAGE in $NEW"
  fi
  exit 1
fi

echo "$IMAGE" > "$STATE_DIR/slot-$NEW"
record "deployed $IMAGE in $NEW"
log "$ENV_NAME now serves $RELEASE from slot $NEW (total $(since "$T0") s)${LIVE:+; slot $LIVE kept for rollback}"
