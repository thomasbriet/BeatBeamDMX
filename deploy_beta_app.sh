#!/usr/bin/env bash
set -euo pipefail

# Install one already-built Beta bundle without exposing rollback copies in
# /Applications.  The only public installation name is always fixed.
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
CANDIDATE="${1:-${ROOT_DIR}/dist-native-app/BeatBeam DMX Beta.app}"
APPLICATIONS_DIR="${BEATBEAM_APPLICATIONS_DIR:-/Applications}"
BACKUPS_DIR="${BEATBEAM_BACKUPS_DIR:-${HOME}/Library/Application Support/BeatBeam/Backups}"
CANONICAL_APP="${APPLICATIONS_DIR}/BeatBeam DMX Beta.app"
ROLLBACK_APP="${BACKUPS_DIR}/BeatBeam DMX Beta Previous.app"
ALLOW_UNSIGNED="${BEATBEAM_ALLOW_UNSIGNED:-0}"
FAIL_AFTER_ROLLBACK="${BEATBEAM_DEPLOY_FAIL_AFTER_ROLLBACK:-0}"
SKIP_STOP="${BEATBEAM_SKIP_STOP:-0}"

fail() { echo "Deployfout: $*" >&2; exit 1; }

[[ -d "$CANDIDATE" ]] || fail "Kandidaatbundle ontbreekt: $CANDIDATE"
[[ -d "$APPLICATIONS_DIR" ]] || fail "Applications-map ontbreekt: $APPLICATIONS_DIR"
[[ "$CANONICAL_APP" == "$APPLICATIONS_DIR/BeatBeam DMX Beta.app" ]] || fail "Ongeldig canoniek pad"
[[ "$ROLLBACK_APP" == "$BACKUPS_DIR/BeatBeam DMX Beta Previous.app" ]] || fail "Ongeldig rollback-pad"
[[ "$BACKUPS_DIR" != /Applications && "$BACKUPS_DIR" != /Applications/* ]] || fail "Rollback mag niet in /Applications staan"

verify_bundle() {
  local app="$1"
  local plist="${app}/Contents/Info.plist"
  local executable="${app}/Contents/MacOS/BeatBeam DMX Beta"
  [[ -d "$app" && -f "$plist" && -x "$executable" ]] || return 1
  [[ "$(plutil -extract CFBundleIdentifier raw "$plist" 2>/dev/null)" == "com.local.beatbeamdmx.beta" ]] || return 1
  if [[ "$ALLOW_UNSIGNED" != "1" ]]; then
    codesign --verify --deep --strict "$app" >/dev/null 2>&1 || return 1
  fi
}

verify_bundle "$CANDIDATE" || fail "Kandidaat is geen geldige BeatBeam Beta-bundle"
mkdir -p "$BACKUPS_DIR"

# Keep staging hidden and beside the canonical destination so the final move is
# atomic. It is never an application visible to Launchpad.
STAGING_DIR="$(mktemp -d "${APPLICATIONS_DIR}/.beatbeam-beta-deploy.XXXXXX")"
STAGED_APP="${STAGING_DIR}/BeatBeam DMX Beta.app"
cleanup() { rm -rf "$STAGING_DIR"; }
trap cleanup EXIT

ditto "$CANDIDATE" "$STAGED_APP"
verify_bundle "$STAGED_APP" || fail "Gestagede kandidaatvalidatie mislukt"

if [[ "$SKIP_STOP" != "1" ]] && pgrep -f "${CANONICAL_APP}/Contents/MacOS/BeatBeam DMX Beta" >/dev/null; then
  osascript -e 'tell application "BeatBeam DMX Beta" to quit' 2>/dev/null || true
  for _attempt in 1 2 3 4 5 6 7 8 9 10; do
    pgrep -f "${CANONICAL_APP}/Contents/MacOS/BeatBeam DMX Beta" >/dev/null || break
    sleep 1
  done
  pgrep -f "${CANONICAL_APP}/Contents/MacOS/BeatBeam DMX Beta" >/dev/null && fail "Lopende canonieke Beta kon niet veilig stoppen"
fi

had_canonical=0
if [[ -d "$CANONICAL_APP" ]]; then
  verify_bundle "$CANONICAL_APP" || fail "Bestaande canonieke Beta is ongeldig; handmatige beoordeling vereist"
  had_canonical=1
  # Candidate is valid before replacing the one permitted external rollback.
  if [[ -e "$ROLLBACK_APP" ]]; then rm -rf "$ROLLBACK_APP"; fi
  mv "$CANONICAL_APP" "$ROLLBACK_APP"
fi

if [[ "$FAIL_AFTER_ROLLBACK" == "1" ]]; then
  if [[ "$had_canonical" == "1" ]]; then mv "$ROLLBACK_APP" "$CANONICAL_APP"; fi
  fail "Geforceerde hersteltest na rollback"
fi

if ! mv "$STAGED_APP" "$CANONICAL_APP" || ! verify_bundle "$CANONICAL_APP"; then
  rm -rf "$CANONICAL_APP"
  if [[ "$had_canonical" == "1" && -d "$ROLLBACK_APP" ]]; then mv "$ROLLBACK_APP" "$CANONICAL_APP"; fi
  fail "Installatievalidatie mislukt; vorige canonieke Beta is hersteld"
fi

echo "Canoniek: $CANONICAL_APP"
if [[ -d "$ROLLBACK_APP" ]]; then echo "Rollback: $ROLLBACK_APP"; fi
