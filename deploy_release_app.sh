#!/usr/bin/env bash
set -euo pipefail

# Install one already-built release bundle.  This script is intentionally
# separate from the Beta installer: each product has a fixed identity, public
# name and rollback slot, so a release deploy cannot replace the Beta app.
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
RELEASE_SOURCE_MANIFEST="${BEATBEAM_RELEASE_SOURCE_MANIFEST:-${ROOT_DIR}/release_source.env}"
APPLICATIONS_DIR="${BEATBEAM_APPLICATIONS_DIR:-/Applications}"
BACKUPS_DIR="${BEATBEAM_BACKUPS_DIR:-${HOME}/Library/Application Support/BeatBeam/Backups}"
CANONICAL_APP="${APPLICATIONS_DIR}/BeatBeam DMX.app"
ROLLBACK_APP="${BACKUPS_DIR}/BeatBeam DMX Previous.app"
ALLOW_UNSIGNED="${BEATBEAM_ALLOW_UNSIGNED:-0}"
FAIL_AFTER_ROLLBACK="${BEATBEAM_DEPLOY_FAIL_AFTER_ROLLBACK:-0}"
SKIP_STOP="${BEATBEAM_SKIP_STOP:-0}"

fail() { echo "Deployfout: $*" >&2; exit 1; }

[[ -f "$RELEASE_SOURCE_MANIFEST" ]] || fail "Release-bronmanifest ontbreekt: $RELEASE_SOURCE_MANIFEST"
# shellcheck source=/dev/null
source "$RELEASE_SOURCE_MANIFEST"
[[ -n "${RELEASE_SOURCE_COMMIT:-}" && -n "${RELEASE_PRODUCT_VERSION:-}" && -n "${RELEASE_BUNDLE_ID:-}" && -n "${RELEASE_BACKEND_SHA256:-}" ]] \
  || fail "Release-bronmanifest is onvolledig"
[[ $# -eq 3 && "$1" == "--source" ]] || fail "Gebruik: $0 --source <commit-of-tag> <BeatBeam DMX.app>"
SOURCE_REF="$2"
CANDIDATE="$3"
SOURCE_COMMIT="$(git -C "$ROOT_DIR" rev-parse --verify "${SOURCE_REF}^{commit}" 2>/dev/null)" \
  || fail "Ongeldige release-bron: $SOURCE_REF"
[[ "$SOURCE_COMMIT" == "$RELEASE_SOURCE_COMMIT" ]] \
  || fail "Release-bron $SOURCE_COMMIT is niet de gepinde productiebron $RELEASE_SOURCE_COMMIT"

[[ -d "$CANDIDATE" ]] || fail "Kandidaatbundle ontbreekt: $CANDIDATE"
[[ -d "$APPLICATIONS_DIR" ]] || fail "Applications-map ontbreekt: $APPLICATIONS_DIR"
[[ "$CANONICAL_APP" == "$APPLICATIONS_DIR/BeatBeam DMX.app" ]] || fail "Ongeldig canoniek pad"
[[ "$ROLLBACK_APP" == "$BACKUPS_DIR/BeatBeam DMX Previous.app" ]] || fail "Ongeldig rollback-pad"
[[ "$BACKUPS_DIR" != /Applications && "$BACKUPS_DIR" != /Applications/* ]] || fail "Rollback mag niet in /Applications staan"

verify_bundle() {
  local app="$1"
  local plist="${app}/Contents/Info.plist"
  local executable="${app}/Contents/MacOS/BeatBeam DMX"
  local backend="${app}/Contents/Resources/backend/beatbeam_app.py"
  [[ -d "$app" && -f "$plist" && -x "$executable" && -f "$backend" ]] || return 1
  [[ "$(plutil -extract CFBundleIdentifier raw "$plist" 2>/dev/null)" == "$RELEASE_BUNDLE_ID" ]] || return 1
  [[ "$(plutil -extract CFBundleShortVersionString raw "$plist" 2>/dev/null)" == "$RELEASE_PRODUCT_VERSION" ]] || return 1
  [[ "$(shasum -a 256 "$backend" | awk '{print $1}')" == "$RELEASE_BACKEND_SHA256" ]] || return 1
  if [[ "$ALLOW_UNSIGNED" != "1" ]]; then
    codesign --verify --deep --strict "$app" >/dev/null 2>&1 || return 1
  fi
}

verify_bundle "$CANDIDATE" || fail "Kandidaat is geen geldige BeatBeam release-bundle"
mkdir -p "$BACKUPS_DIR"

# Staging remains hidden beside the final destination and is not a public app.
STAGING_DIR="$(mktemp -d "${APPLICATIONS_DIR}/.beatbeam-release-deploy.XXXXXX")"
STAGED_APP="${STAGING_DIR}/BeatBeam DMX.app"
cleanup() { rm -rf "$STAGING_DIR"; }
trap cleanup EXIT

ditto "$CANDIDATE" "$STAGED_APP"
verify_bundle "$STAGED_APP" || fail "Gestagede kandidaatvalidatie mislukt"

if [[ "$SKIP_STOP" != "1" ]] && pgrep -f "${CANONICAL_APP}/Contents/MacOS/BeatBeam DMX" >/dev/null; then
  osascript -e 'tell application "BeatBeam DMX" to quit' 2>/dev/null || true
  for _attempt in 1 2 3 4 5 6 7 8 9 10; do
    pgrep -f "${CANONICAL_APP}/Contents/MacOS/BeatBeam DMX" >/dev/null || break
    sleep 1
  done
  pgrep -f "${CANONICAL_APP}/Contents/MacOS/BeatBeam DMX" >/dev/null && fail "Lopende canonieke release kon niet veilig stoppen"
fi

had_canonical=0
if [[ -d "$CANONICAL_APP" ]]; then
  verify_bundle "$CANONICAL_APP" || fail "Bestaande canonieke release is ongeldig; handmatige beoordeling vereist"
  had_canonical=1
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
  fail "Installatievalidatie mislukt; vorige canonieke release is hersteld"
fi

echo "Canoniek: $CANONICAL_APP"
if [[ -d "$ROLLBACK_APP" ]]; then echo "Rollback: $ROLLBACK_APP"; fi
