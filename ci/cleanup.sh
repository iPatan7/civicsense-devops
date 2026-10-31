#!/bin/sh
# Removes what a build leaves behind: its CI containers and networks, and old
# civicsense image tags (the five newest are kept; tags still used by a slot
# cannot be removed and are skipped). Images of other projects are never touched.
ID=$(printf '%s' "${BUILD_TAG:-local}" | tr -c 'a-zA-Z0-9_.-' '-' | tr 'A-Z' 'a-z')
docker ps -aq --filter "name=ci-$ID" | xargs -r docker rm -f >/dev/null 2>&1
docker network ls -q --filter "name=ci-$ID" | xargs -r docker network rm >/dev/null 2>&1
docker image ls civicsense --format '{{.CreatedAt}}\t{{.Repository}}:{{.Tag}}' | sort -r \
  | tail -n +6 | cut -f2 | xargs -r docker image rm >/dev/null 2>&1
exit 0
