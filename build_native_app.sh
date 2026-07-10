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
ICON_MASTER="branding/beatbeam-icon-master.png"
ICONSET_DIR="dist-native-app/AppIcon-${VARIANT}.iconset"

rm -rf "$APP_DIR"
mkdir -p "$MACOS" "$BACKEND_RESOURCES"

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

cp beatbeam_app.py "${BACKEND_RESOURCES}/"
cp enttec_open_dmx.py "${BACKEND_RESOURCES}/"
cp fixtures.json "${BACKEND_RESOURCES}/"
cp beatbeam_config.json "${BACKEND_RESOURCES}/"
cp "${ICON_MASTER}" "${RESOURCES}/BrandMark.png"
cp -R assets "${RESOURCES}/"
cp -R static "${BACKEND_RESOURCES}/"
cp -R .venv "${BACKEND_RESOURCES}/"

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

echo "Klaar (${VARIANT}): ${APP_DIR}"
