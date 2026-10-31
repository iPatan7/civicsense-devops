#!/bin/sh
# Smoke test of a running CivicSense, through its public address: the checks a
# person would make by hand after a release, done in about a second.
#
#   ci/smoke.sh http://localhost:8092 [expected-release]
#
# Stops at the first failed check and exits with status 1.
set -u
URL=${1%/}
EXPECT=${2:-}
JAR=$(mktemp)
trap 'rm -f "$JAR" "$JAR.body"' EXIT

ms() { date +%s%3N; }
check() {   # check <name> <command...>
  name=$1; shift; t=$(ms)
  if out=$("$@" 2>&1); then
    printf '  ok    %-36s %5d ms\n' "$name" $(( $(ms) - t ))
  else
    printf '  FAIL  %-36s %s\n' "$name" "$out"; exit 1
  fi
}
get() {     # get <expected status> <path> [curl options]: body is kept in $JAR.body
  want=$1 path=$2; shift 2
  got=$(curl -s -o "$JAR.body" -w '%{http_code}' -b "$JAR" -c "$JAR" "$@" "$URL$path")
  [ "$got" = "$want" ] || { echo "GET $path returned $got, expected $want"; return 1; }
}
has() { grep -q "$1" "$JAR.body" || { echo "response does not contain '$1'"; return 1; }; }

health() {
  get 200 /healthz && has '"status": "ok"' || return 1
  [ -z "$EXPECT" ] || has "\"release\": \"$EXPECT\""
}
home() { get 200 / && has "CivicSense"; }
static() {
  css=$(curl -s "$URL/" | grep -o '/static/[^"]*\.css' | head -1)
  [ -n "$css" ] || { echo "no stylesheet linked from the home page"; return 1; }
  get 200 "$css"
}
login_page() { get 200 /accounts/login/ && has csrfmiddlewaretoken; }
login() {
  token=$(awk '$6 == "csrftoken" { print $7 }' "$JAR")
  got=$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' -b "$JAR" -c "$JAR" \
    -H "Referer: $URL/accounts/login/" -H "Origin: $URL" \
    --data-urlencode "csrfmiddlewaretoken=$token" -d username=citizen1 -d password=civic123 \
    "$URL/accounts/login/")
  case "$got" in 302*) ;; *) echo "login returned $got (expected a 302 redirect)"; return 1 ;; esac
}
my_complaints() { get 200 /mine/ && has 'accounts/logout'; }
access_control() {
  got=$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" "$URL/authority/")
  case "$got" in 302|403) ;; *) echo "a citizen got $got from the authority dashboard"; return 1 ;; esac
}

echo "smoke test of $URL${EXPECT:+ (expecting release $EXPECT)}"
check "health endpoint and release"        health
check "home page renders"                  home
check "static files served by nginx"       static
check "login page with CSRF token"         login_page
check "citizen can log in"                 login
check "citizen sees own complaints"        my_complaints
check "authority dashboard is protected"   access_control
echo "smoke test passed"
