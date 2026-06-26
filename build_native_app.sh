#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="BeatBeam DMX"
APP_DIR="dist-native-app/${APP_NAME}.app"
CONTENTS="${APP_DIR}/Contents"
MACOS="${CONTENTS}/MacOS"
RESOURCES="${CONTENTS}/Resources"
BACKEND_RESOURCES="${RESOURCES}/backend"
ICON_MASTER="branding/beatbeam-icon-master.png"
ICONSET_DIR="dist-native-app/AppIcon.iconset"

rm -rf "$APP_DIR"
mkdir -p "$MACOS" "$BACKEND_RESOURCES"

swiftc \
  -O \
  -parse-as-library \
  -framework AppKit \
  -framework Foundation \
  -framework SwiftUI \
  native/BeatBeamDMXApp.swift \
  -o "${MACOS}/${APP_NAME}"

cat > "${CONTENTS}/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>BeatBeam DMX</string>
  <key>CFBundleDisplayName</key>
  <string>BeatBeam DMX</string>
  <key>CFBundleIdentifier</key>
  <string>com.local.beatbeamdmx.native</string>
  <key>CFBundleVersion</key>
  <string>100</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleExecutable</key>
  <string>BeatBeam DMX</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
</dict>
</plist>
PLIST

chmod +x "${MACOS}/${APP_NAME}"

cp beatbeam_app.py "${BACKEND_RESOURCES}/"
cp enttec_open_dmx.py "${BACKEND_RESOURCES}/"
cp fixtures.json "${BACKEND_RESOURCES}/"
cp beatbeam_config.json "${BACKEND_RESOURCES}/"
cp "${ICON_MASTER}" "${RESOURCES}/BrandMark.png"
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

echo "Klaar: ${APP_DIR}"
