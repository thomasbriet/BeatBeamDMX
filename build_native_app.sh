#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

VARIANT="${1:-release}"

if [[ "$VARIANT" == "both" ]]; then
  "$0" release
  "$0" beta
  exit 0
fi

case "$VARIANT" in
  release|stable)
    APP_NAME="BeatBeam DMX"
    BUNDLE_ID="com.local.beatbeamdmx.native"
    DEFAULTS_PREFIX="BeatBeamDMX"
    BACKEND_PORT="8780"
    BACKEND_OSC_PORT="4461"
    SUPPORT_DIRECTORY_NAME="BeatBeamDMX Native"
    STABLE_SUPPORT_DIRECTORY_NAME="BeatBeamDMX Native"
    TEMP_DIRECTORY_NAME="BeatBeamDMX"
    LOG_STEM="beatbeam"
    APP_SLUG="BeatBeamDMX"
    VERSION="1.1.0"
    BUILD_NUMBER="110"
    ;;
  beta)
    APP_NAME="BeatBeam DMX Beta"
    BUNDLE_ID="com.local.beatbeamdmx.beta"
    DEFAULTS_PREFIX="BeatBeamDMXBeta"
    BACKEND_PORT="8781"
    BACKEND_OSC_PORT="4462"
    SUPPORT_DIRECTORY_NAME="BeatBeamDMX Beta Native"
    STABLE_SUPPORT_DIRECTORY_NAME="BeatBeamDMX Native"
    TEMP_DIRECTORY_NAME="BeatBeamDMXBeta"
    LOG_STEM="beatbeam-beta"
    APP_SLUG="BeatBeamDMXBeta"
    VERSION="1.2.0-beta"
    BUILD_NUMBER="120"
    ;;
  *)
    echo "Onbekende variant: $VARIANT" >&2
    echo "Gebruik: $0 [release|beta|both]" >&2
    exit 1
    ;;
esac

APP_DIR="dist-native-app/${APP_NAME}.app"
CONTENTS="${APP_DIR}/Contents"
MACOS="${CONTENTS}/MacOS"
RESOURCES="${CONTENTS}/Resources"
BACKEND_RESOURCES="${RESOURCES}/backend"
BACKEND_PYTHON_RUNTIME="${BACKEND_RESOURCES}/python-runtime"
ICON_MASTER="branding/beatbeam-icon-master.png"
ICONSET_DIR="dist-native-app/AppIcon-${VARIANT}.iconset"
PYTHON_RUNTIME="${BEATBEAM_PYTHON:-python3}"
VENV_PYTHON=".venv/bin/python3"

fail() {
  echo "Buildfout: $*" >&2
  exit 1
}

[[ -x "$VENV_PYTHON" ]] || fail "Geen projectvenv-interpreter gevonden op $VENV_PYTHON"
command -v "$PYTHON_RUNTIME" >/dev/null 2>&1 || fail "Python runtime '$PYTHON_RUNTIME' is niet uitvoerbaar"

IFS=$'\t' read -r PYTHON_RUNTIME_EXECUTABLE PYTHON_RUNTIME_SOURCE PYTHON_STDLIB_VERSION PYTHON_ARCHITECTURE PYTHON_RUNTIME_VERSION < <("$PYTHON_RUNTIME" - <<'PY'
import platform, sys
print("\t".join((sys.executable, sys.base_prefix, f"{sys.version_info.major}.{sys.version_info.minor}", platform.machine(), sys.version.split()[0])))
PY
)

IFS=$'\t' read -r VENV_PYTHON_EXECUTABLE VENV_PYTHON_VERSION PYTHON_SITE_PACKAGES_SOURCE < <("$VENV_PYTHON" - <<'PY'
import site, sys, sysconfig
paths = [path for path in [*site.getsitepackages(), sysconfig.get_path("purelib"), sysconfig.get_path("platlib")] if path]
project_paths = [path for path in paths if "/.venv/" in path]
print("\t".join((sys.executable, f"{sys.version_info.major}.{sys.version_info.minor}", project_paths[0] if project_paths else "")))
PY
)
[[ -n "$PYTHON_SITE_PACKAGES_SOURCE" && -d "$PYTHON_SITE_PACKAGES_SOURCE" ]] || fail "De venv rapporteert geen geldige project-site-packages-directory"

if [[ ! -x "${PYTHON_RUNTIME_SOURCE}/bin/python3" ]]; then
  fail "Geen portable Python runtime bron gevonden op ${PYTHON_RUNTIME_SOURCE}"
fi
[[ "$PYTHON_ARCHITECTURE" == "arm64" ]] || fail "Python runtime moet arm64 zijn, gevonden: $PYTHON_ARCHITECTURE"

# A venv may intentionally use a different minor version when its dependency
# set is pure Python. Never copy CPython ABI-bound modules across versions.
NATIVE_EXTENSIONS="$(find "$PYTHON_SITE_PACKAGES_SOURCE" -type f \( -name '*.so' -o -name '*.dylib' \) -print)"
if [[ -n "$NATIVE_EXTENSIONS" && "$VENV_PYTHON_VERSION" != "$PYTHON_STDLIB_VERSION" ]]; then
  fail "Native extensies in $PYTHON_SITE_PACKAGES_SOURCE zijn niet veilig voor Python $PYTHON_STDLIB_VERSION: $NATIVE_EXTENSIONS"
fi

rm -rf "$APP_DIR"
mkdir -p "$MACOS" "$BACKEND_RESOURCES"

echo "Python runtime: ${PYTHON_RUNTIME_EXECUTABLE} (${PYTHON_RUNTIME_VERSION}, ${PYTHON_ARCHITECTURE})"
echo "Dependencies: ${PYTHON_SITE_PACKAGES_SOURCE} (venv Python ${VENV_PYTHON_VERSION})"

swiftc \
  -O \
  -parse-as-library \
  -framework AppKit \
  -framework AVFoundation \
  -framework CoreAudio \
  -framework Foundation \
  -framework Metal \
  -framework MetalKit \
  -framework SwiftUI \
  native/BeatBeamDMXApp.swift \
  native/LiveShowUX.swift \
  -o "${MACOS}/${APP_NAME}"

cat > "${CONTENTS}/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>${APP_NAME}</string>
  <key>CFBundleDisplayName</key>
  <string>${APP_NAME}</string>
  <key>CFBundleIdentifier</key>
  <string>${BUNDLE_ID}</string>
  <key>CFBundleVersion</key>
  <string>${BUILD_NUMBER}</string>
  <key>CFBundleShortVersionString</key>
  <string>${VERSION}</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleExecutable</key>
  <string>${APP_NAME}</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>NSMicrophoneUsageDescription</key>
  <string>BeatBeam gebruikt live audio-input om BPM, energie en dimmerdynamiek te sturen.</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>BeatBeamDefaultsPrefix</key>
  <string>${DEFAULTS_PREFIX}</string>
  <key>BeatBeamBackendPort</key>
  <integer>${BACKEND_PORT}</integer>
  <key>BeatBeamBackendOscPort</key>
  <integer>${BACKEND_OSC_PORT}</integer>
  <key>BeatBeamSupportDirectoryName</key>
  <string>${SUPPORT_DIRECTORY_NAME}</string>
  <key>BeatBeamStableSupportDirectoryName</key>
  <string>${STABLE_SUPPORT_DIRECTORY_NAME}</string>
  <key>BeatBeamTemporaryDirectoryName</key>
  <string>${TEMP_DIRECTORY_NAME}</string>
  <key>BeatBeamLogStem</key>
  <string>${LOG_STEM}</string>
  <key>BeatBeamAppSlug</key>
  <string>${APP_SLUG}</string>
</dict>
</plist>
PLIST

chmod +x "${MACOS}/${APP_NAME}"

BACKEND_PYTHON_SOURCES=(
  beatbeam_app.py
  enttec_open_dmx.py
  show_intent.py
  show_interpreter_input.py
  show_intent_candidate_mapper.py
  show_interpreter_input_adapter.py
  rich_musical_events.py
  rme_preview.py
  dynamic_composer.py
  production_show_selector.py
  live_intensity.py
  musical_event_envelope.py
)
for backend_source in "${BACKEND_PYTHON_SOURCES[@]}"; do
  cp "${backend_source}" "${BACKEND_RESOURCES}/"
done
cp fixtures.json "${BACKEND_RESOURCES}/"
cp beatbeam_config.json "${BACKEND_RESOURCES}/"
cp "${ICON_MASTER}" "${RESOURCES}/BrandMark.png"
cp -R assets "${RESOURCES}/"
cp -R static "${BACKEND_RESOURCES}/"
mkdir -p "${BACKEND_PYTHON_RUNTIME}"
ditto "${PYTHON_RUNTIME_SOURCE}" "${BACKEND_PYTHON_RUNTIME}"
# Homebrew's framework contains a site-packages symlink back to the host
# installation. Replace it inside the generated bundle with real dependencies.
rm -f "${BACKEND_PYTHON_RUNTIME}/lib/python${PYTHON_STDLIB_VERSION}/site-packages"
mkdir -p "${BACKEND_PYTHON_RUNTIME}/lib/python${PYTHON_STDLIB_VERSION}/site-packages"
ditto "${PYTHON_SITE_PACKAGES_SOURCE}" "${BACKEND_PYTHON_RUNTIME}/lib/python${PYTHON_STDLIB_VERSION}/site-packages"

rm -rf "${ICONSET_DIR}"
mkdir -p "${ICONSET_DIR}"

sips -s format png -z 16 16   "${ICON_MASTER}" --out "${ICONSET_DIR}/icon_16x16.png" >/dev/null
sips -s format png -z 32 32   "${ICON_MASTER}" --out "${ICONSET_DIR}/icon_16x16@2x.png" >/dev/null
sips -s format png -z 32 32   "${ICON_MASTER}" --out "${ICONSET_DIR}/icon_32x32.png" >/dev/null
sips -s format png -z 64 64   "${ICON_MASTER}" --out "${ICONSET_DIR}/icon_32x32@2x.png" >/dev/null
sips -s format png -z 128 128 "${ICON_MASTER}" --out "${ICONSET_DIR}/icon_128x128.png" >/dev/null
sips -s format png -z 256 256 "${ICON_MASTER}" --out "${ICONSET_DIR}/icon_128x128@2x.png" >/dev/null
sips -s format png -z 256 256 "${ICON_MASTER}" --out "${ICONSET_DIR}/icon_256x256.png" >/dev/null
sips -s format png -z 512 512 "${ICON_MASTER}" --out "${ICONSET_DIR}/icon_256x256@2x.png" >/dev/null
sips -s format png -z 512 512 "${ICON_MASTER}" --out "${ICONSET_DIR}/icon_512x512.png" >/dev/null
sips -s format png -z 1024 1024 "${ICON_MASTER}" --out "${ICONSET_DIR}/icon_512x512@2x.png" >/dev/null

iconutil -c icns "${ICONSET_DIR}" -o "${RESOURCES}/AppIcon.icns"
rm -rf "${ICONSET_DIR}"

[[ -x "${MACOS}/${APP_NAME}" ]] || fail "Native executable ontbreekt"
file "${MACOS}/${APP_NAME}" | grep -q 'arm64' || fail "Native executable is niet arm64"
[[ -x "${BACKEND_PYTHON_RUNTIME}/bin/python3" ]] || fail "Bundled Python runtime ontbreekt"
[[ -f "${BACKEND_RESOURCES}/beatbeam_app.py" ]] || fail "Bundled backend ontbreekt"
[[ -d "${BACKEND_PYTHON_RUNTIME}/lib/python${PYTHON_STDLIB_VERSION}/site-packages" ]] || fail "Bundled dependencies ontbreken"
cmp -s beatbeam_app.py "${BACKEND_RESOURCES}/beatbeam_app.py" || fail "Bundled backend wijkt af van de bron"
(cd "${BACKEND_RESOURCES}" && ./python-runtime/bin/python3 -c 'import beatbeam_app; print("Backend smoke: PASS")') \
  || fail "Bundled backend-import mislukt"
xattr -cr "${APP_DIR}"
codesign --force --deep --sign - "${APP_DIR}"
codesign --verify --deep --strict "${APP_DIR}"

SOURCE_HASH="$(shasum -a 256 beatbeam_app.py | awk '{print $1}')"
BUNDLE_HASH="$(shasum -a 256 "${BACKEND_RESOURCES}/beatbeam_app.py" | awk '{print $1}')"
echo "Backend hash: ${SOURCE_HASH}"
echo "Bundle backend hash: ${BUNDLE_HASH}"
echo "Sign: PASS"
echo "Klaar (${VARIANT}): ${APP_DIR}"
