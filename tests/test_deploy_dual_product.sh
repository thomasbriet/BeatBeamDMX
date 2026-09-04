#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT
APPS="$SANDBOX/Applications"
BACKUPS="$SANDBOX/Backups"
mkdir -p "$APPS" "$BACKUPS"

make_bundle() {
  local destination="$1" app_name="$2" bundle_id="$3" marker="$4"
  mkdir -p "$destination/Contents/MacOS" "$destination/Contents/Resources/backend"
  printf '#!/bin/sh\necho %s\n' "$marker" > "$destination/Contents/MacOS/$app_name"
  chmod +x "$destination/Contents/MacOS/$app_name"
  printf 'test-backend\n' > "$destination/Contents/Resources/backend/beatbeam_app.py"
  cat > "$destination/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict><key>CFBundleIdentifier</key><string>${bundle_id}</string><key>CFBundleShortVersionString</key><string>1.1.0</string></dict></plist>
PLIST
}

release_candidate_one="$SANDBOX/release-one.app"
release_candidate_two="$SANDBOX/release-two.app"
beta_candidate_one="$SANDBOX/beta-one.app"
beta_candidate_two="$SANDBOX/beta-two.app"
make_bundle "$release_candidate_one" "BeatBeam DMX" "com.local.beatbeamdmx.native" release-one
make_bundle "$release_candidate_two" "BeatBeam DMX" "com.local.beatbeamdmx.native" release-two
make_bundle "$beta_candidate_one" "BeatBeam DMX Beta" "com.local.beatbeamdmx.beta" beta-one
make_bundle "$beta_candidate_two" "BeatBeam DMX Beta" "com.local.beatbeamdmx.beta" beta-two

TEST_SOURCE="$(git -C "$ROOT_DIR" rev-parse HEAD)"
TEST_MANIFEST="$SANDBOX/release-source.env"
cat > "$TEST_MANIFEST" <<MANIFEST
RELEASE_SOURCE_COMMIT=${TEST_SOURCE}
RELEASE_PRODUCT_VERSION=1.1.0
RELEASE_BUNDLE_ID=com.local.beatbeamdmx.native
RELEASE_BACKEND_SHA256=$(shasum -a 256 "$release_candidate_one/Contents/Resources/backend/beatbeam_app.py" | awk '{print $1}')
MANIFEST

run_release() {
  BEATBEAM_ALLOW_UNSIGNED=1 BEATBEAM_SKIP_STOP=1 BEATBEAM_APPLICATIONS_DIR="$APPS" BEATBEAM_BACKUPS_DIR="$BACKUPS" BEATBEAM_RELEASE_SOURCE_MANIFEST="$TEST_MANIFEST" "$ROOT_DIR/deploy_release_app.sh" --source "$TEST_SOURCE" "$1"
}
run_beta() {
  BEATBEAM_ALLOW_UNSIGNED=1 BEATBEAM_SKIP_STOP=1 BEATBEAM_APPLICATIONS_DIR="$APPS" BEATBEAM_BACKUPS_DIR="$BACKUPS" "$ROOT_DIR/deploy_beta_app.sh" "$1"
}

# Historical names and an unrelated app deliberately look similar. The fixed
# deploy targets must preserve them rather than guessing from a fuzzy name.
make_bundle "$APPS/BeatBeam DMX Beta.app.before-v1" "BeatBeam DMX Beta" "com.local.beatbeamdmx.beta" historic-beta
make_bundle "$APPS/BeatBeam DMX.app.before-v1" "BeatBeam DMX" "com.local.beatbeamdmx.native" historic-release
make_bundle "$APPS/BeatBeam DMX Tools.app" "BeatBeam DMX Tools" "com.example.unknown" unknown

if BEATBEAM_ALLOW_UNSIGNED=1 BEATBEAM_SKIP_STOP=1 BEATBEAM_APPLICATIONS_DIR="$APPS" BEATBEAM_BACKUPS_DIR="$BACKUPS" BEATBEAM_RELEASE_SOURCE_MANIFEST="$TEST_MANIFEST" "$ROOT_DIR/deploy_release_app.sh" "$release_candidate_one"; then
  echo "Expected implicit release deployment rejection" >&2; exit 1
fi
if BEATBEAM_ALLOW_UNSIGNED=1 BEATBEAM_SKIP_STOP=1 BEATBEAM_APPLICATIONS_DIR="$APPS" BEATBEAM_BACKUPS_DIR="$BACKUPS" BEATBEAM_RELEASE_SOURCE_MANIFEST="$TEST_MANIFEST" "$ROOT_DIR/deploy_release_app.sh" --source v1.0.0 "$release_candidate_one"; then
  echo "Expected unpinned release source rejection" >&2; exit 1
fi

run_release "$release_candidate_one"
run_beta "$beta_candidate_one"
grep -q release-one "$APPS/BeatBeam DMX.app/Contents/MacOS/BeatBeam DMX"
grep -q beta-one "$APPS/BeatBeam DMX Beta.app/Contents/MacOS/BeatBeam DMX Beta"

run_release "$release_candidate_two"
grep -q release-two "$APPS/BeatBeam DMX.app/Contents/MacOS/BeatBeam DMX"
grep -q beta-one "$APPS/BeatBeam DMX Beta.app/Contents/MacOS/BeatBeam DMX Beta"
grep -q release-one "$BACKUPS/BeatBeam DMX Previous.app/Contents/MacOS/BeatBeam DMX"

run_beta "$beta_candidate_two"
grep -q release-two "$APPS/BeatBeam DMX.app/Contents/MacOS/BeatBeam DMX"
grep -q beta-two "$APPS/BeatBeam DMX Beta.app/Contents/MacOS/BeatBeam DMX Beta"
grep -q beta-one "$BACKUPS/BeatBeam DMX Beta Previous.app/Contents/MacOS/BeatBeam DMX Beta"

for preserved in "BeatBeam DMX Beta.app.before-v1" "BeatBeam DMX.app.before-v1" "BeatBeam DMX Tools.app"; do
  [[ -d "$APPS/$preserved" ]]
done

if BEATBEAM_ALLOW_UNSIGNED=1 BEATBEAM_SKIP_STOP=1 BEATBEAM_DEPLOY_FAIL_AFTER_ROLLBACK=1 BEATBEAM_APPLICATIONS_DIR="$APPS" BEATBEAM_BACKUPS_DIR="$BACKUPS" BEATBEAM_RELEASE_SOURCE_MANIFEST="$TEST_MANIFEST" "$ROOT_DIR/deploy_release_app.sh" --source "$TEST_SOURCE" "$release_candidate_one"; then
  echo "Expected release deployment failure" >&2; exit 1
fi
grep -q release-two "$APPS/BeatBeam DMX.app/Contents/MacOS/BeatBeam DMX"
grep -q beta-two "$APPS/BeatBeam DMX Beta.app/Contents/MacOS/BeatBeam DMX Beta"

if BEATBEAM_ALLOW_UNSIGNED=1 BEATBEAM_SKIP_STOP=1 BEATBEAM_DEPLOY_FAIL_AFTER_ROLLBACK=1 BEATBEAM_APPLICATIONS_DIR="$APPS" BEATBEAM_BACKUPS_DIR="$BACKUPS" "$ROOT_DIR/deploy_beta_app.sh" "$beta_candidate_one"; then
  echo "Expected Beta deployment failure" >&2; exit 1
fi
grep -q release-two "$APPS/BeatBeam DMX.app/Contents/MacOS/BeatBeam DMX"
grep -q beta-two "$APPS/BeatBeam DMX Beta.app/Contents/MacOS/BeatBeam DMX Beta"
[[ "$(find "$BACKUPS" -maxdepth 1 -type d -name 'BeatBeam DMX*.app' | wc -l | tr -d ' ')" == "2" ]]
echo "dual release/Beta deployment policy: PASS"
