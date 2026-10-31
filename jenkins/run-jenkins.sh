#!/bin/sh
# Starts the CivicSense Jenkins controller from nothing but the files in this folder:
# plugins.txt (what to install) and casc.yaml (how it is configured, including the job).
#
#   JENKINS_ADMIN_PASSWORD='...' jenkins/run-jenkins.sh
#
# It runs as the current user, so builds can use the local Docker engine, and it
# listens on 127.0.0.1:8090 (8080 is taken by the system Jenkins on this machine).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
: "${JENKINS_ADMIN_PASSWORD:?set JENKINS_ADMIN_PASSWORD first}"
export JENKINS_ADMIN_PASSWORD
export JENKINS_HOME="${JENKINS_HOME:-$HOME/jenkins-civic}"
WAR="${JENKINS_WAR:-/usr/share/java/jenkins.war}"
PORT="${JENKINS_PORT:-8090}"
PM_VERSION=2.15.0
PM="$JENKINS_HOME/jenkins-plugin-manager-$PM_VERSION.jar"

mkdir -p "$JENKINS_HOME/plugins"
[ -f "$PM" ] || curl -fsSL -o "$PM" \
  "https://github.com/jenkinsci/plugin-installation-manager-tool/releases/download/$PM_VERSION/jenkins-plugin-manager-$PM_VERSION.jar"

# Install (or update) the plugins and everything they depend on.
java -jar "$PM" --war "$WAR" --plugin-download-directory "$JENKINS_HOME/plugins" \
  --plugin-file "$HERE/plugins.txt"

exec java -Xmx1g -Djava.awt.headless=true \
  -Djenkins.install.runSetupWizard=false \
  -Dcasc.jenkins.config="$HERE/casc.yaml" \
  -jar "$WAR" --httpPort="$PORT" --httpListenAddress=127.0.0.1
