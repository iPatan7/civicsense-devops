#!/bin/sh
# Lists the exact Python packages inside the built image and checks them against
# the public vulnerability databases (pip-audit). The package list is kept as a
# build artifact (reports/requirements.lock), so every release records what it
# shipped.
#
#   ci/audit.sh civicsense:<tag>     exit status 1 if a known vulnerability is found
set -eu
IMAGE=$1
mkdir -p reports
docker build -q -t civicsense-ci-tools -f ci/Dockerfile.tools ci >/dev/null
docker run --rm --entrypoint pip "$IMAGE" freeze --disable-pip-version-check > reports/requirements.lock
echo "image $IMAGE contains $(grep -c . reports/requirements.lock) Python packages"
status=0
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD/reports:/r" civicsense-ci-tools \
  pip-audit --no-deps --disable-pip --progress-spinner off -r /r/requirements.lock \
  2>&1 | grep -v 'WARNING:pip_audit' > reports/pip-audit.txt || status=$?
cat reports/pip-audit.txt
# pip-audit prints a table and exits 1 when it finds something; the pipe hides
# that status, so look at the report itself.
grep -q 'No known vulnerabilities found' reports/pip-audit.txt || status=1
exit $status
