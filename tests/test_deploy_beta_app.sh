#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT
APPS="$SANDBOX/Applications"
BACKUPS="$SANDBOX/Backups"
mkdir -p "$APPS" "$BACKUPS"

make_bundle() {
  local destination="$1" marker="$2"
  mkdir -p "$destination/Contents/MacOS"
  printf '#!/bin/sh\necho %s\n' "$marker" > "$destination/Contents/MacOS/BeatBeam DMX Beta"
  chmod +x "$destination/Contents/MacOS/BeatBeam DMX Beta"
  cat > "$destination/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict><key>CFBundleIdentifier</key><string>com.local.beatbeamdmx.beta</string><key>CFBundleShortVersionString</key><string>1.2.0-beta</string></dict></plist>
PLIST
}

CANDIDATE_ONE="$SANDBOX/candidate-one.app"
CANDIDATE_TWO="$SANDBOX/candidate-two.app"
make_bundle "$CANDIDATE_ONE" one
make_bundle "$CANDIDATE_TWO" two

run_deploy() {
  BEATBEAM_ALLOW_UNSIGNED=1 BEATBEAM_SKIP_STOP=1 BEATBEAM_APPLICATIONS_DIR="$APPS" BEATBEAM_BACKUPS_DIR="$BACKUPS" "$ROOT_DIR/deploy_beta_app.sh" "$1"
}

run_deploy "$CANDIDATE_ONE"
run_deploy "$CANDIDATE_TWO"
[[ -d "$APPS/BeatBeam DMX Beta.app" ]]
[[ -d "$BACKUPS/BeatBeam DMX Beta Previous.app" ]]
[[ "$(find "$APPS" -maxdepth 1 -type d -name '*BeatBeam*' | wc -l | tr -d ' ')" == "1" ]]
[[ "$(find "$BACKUPS" -maxdepth 1 -type d -name '*BeatBeam*' | wc -l | tr -d ' ')" == "1" ]]
grep -q two "$APPS/BeatBeam DMX Beta.app/Contents/MacOS/BeatBeam DMX Beta"
grep -q one "$BACKUPS/BeatBeam DMX Beta Previous.app/Contents/MacOS/BeatBeam DMX Beta"

if BEATBEAM_ALLOW_UNSIGNED=1 BEATBEAM_SKIP_STOP=1 BEATBEAM_DEPLOY_FAIL_AFTER_ROLLBACK=1 BEATBEAM_APPLICATIONS_DIR="$APPS" BEATBEAM_BACKUPS_DIR="$BACKUPS" "$ROOT_DIR/deploy_beta_app.sh" "$CANDIDATE_ONE"; then
  echo "Expected forced deployment failure" >&2; exit 1
fi
grep -q two "$APPS/BeatBeam DMX Beta.app/Contents/MacOS/BeatBeam DMX Beta"
echo "deploy backup policy: PASS"
