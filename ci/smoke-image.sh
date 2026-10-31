#!/bin/sh
# Starts the freshly built image on its own (SQLite, production settings) and
# waits for /healthz: proves the image itself boots, runs its entrypoint and does
# not run as root. Runs for every branch, including those that are not deployed.
#
#   ci/smoke-image.sh civicsense:<tag>
set -eu
IMAGE=$1
C="ci-$(printf '%s' "${BUILD_TAG:-local-$$}" | tr -c 'a-zA-Z0-9_.-' '-' | tr 'A-Z' 'a-z')-smoke"
trap 'docker rm -f "$C" >/dev/null 2>&1 || true' EXIT
docker run -d --name "$C" -e DJANGO_SECRET_KEY=smoke -e DJANGO_DEBUG=0 \
  -e DJANGO_ALLOWED_HOSTS=localhost -e CIVIC_RELEASE="${IMAGE#*:}" "$IMAGE" >/dev/null
i=0
until docker exec "$C" curl -fsS http://localhost:8000/healthz 2>/dev/null; do
  i=$((i + 1))
  [ $i -lt 60 ] || { echo "no answer from /healthz"; docker logs "$C" | tail -30; exit 1; }
  sleep 1
done
echo
echo "image answered /healthz after about ${i} s"
uid=$(docker exec "$C" id -u)
[ "$uid" != 0 ] || { echo "the application runs as root"; exit 1; }
echo "application runs as uid $uid, not root"
