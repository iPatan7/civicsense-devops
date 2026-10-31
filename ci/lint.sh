#!/bin/sh
# Static analysis in the tools image (ci/Dockerfile.tools), so the build agent
# needs nothing but Docker.
#
#   flake8 errors that mean broken code (syntax errors, undefined names) fail the build;
#   style warnings and bandit's findings are reported in reports/ but do not;
#   a high-severity, high-confidence bandit finding fails the build.
set -eu
mkdir -p reports
docker build -q -t civicsense-ci-tools -f ci/Dockerfile.tools ci >/dev/null
run() { docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/src" -w /src civicsense-ci-tools "$@"; }
SRC="accounts complaints dashboard nlpengine civicsense manage.py"

run flake8 --max-line-length=100 --exclude=migrations --count --statistics \
    --output-file=reports/flake8.txt $SRC >/dev/null || true
echo "flake8: $(grep -c . reports/flake8.txt || true) style warnings (reports/flake8.txt)"
run flake8 --select=E9,F63,F7,F82 --exclude=migrations --show-source $SRC
echo "flake8: no syntax errors or undefined names"

run bandit -q -r $SRC -x '*/migrations/*,*/tests.py' -f txt -o reports/bandit.txt || true
echo "bandit: $(grep -c '^>> Issue' reports/bandit.txt || true) findings (reports/bandit.txt)"
run bandit -q -r $SRC -x '*/migrations/*,*/tests.py' --severity-level high --confidence-level high
echo "bandit: no high-severity findings"
