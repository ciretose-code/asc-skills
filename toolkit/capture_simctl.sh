#!/bin/zsh
# Capture App Store screenshots on a simulator by relaunching the app into each
# screen with launch arguments — no UI automation needed.
#
#   capture_simctl.sh <device-name-or-udid> <out-dir> <shots-file> [app-path]
#
# Env:
#   BUNDLE_ID     default: "bundleId" from the nearest asc.json
#   SETUP_HOOK    script run once after install + first launch, with
#                 $UDID $BUNDLE_ID $CONTAINER exported — inject saved state,
#                 defaults, fixtures here (see the screenshots skill)
#   APPEARANCE    light | dark (default: light)
#
# <shots-file>: one shot per line —   <name> <settle-seconds> [launch args...]
#   # comments and blank lines are ignored
#   01-hero      6  -screenshotMode -screen home
#   02-detail    7  -screenshotMode -screen detail -item sample
#   03-dark      6  -screenshotMode -screen home -AppleInterfaceStyle Dark
#   @hook prepare_run.sh       (a line starting @hook runs that script with the
#                               same env, between shots — e.g. swap saved state)
#
# Each shot: terminate, relaunch with its args, wait <settle>, screenshot. The
# status bar is pinned to 9:41 / full battery / full bars. Output is the
# simulator's native size, RGBA PNG: run `images.py flatten` before uploading.
set -eu

DEV="${1:?usage: capture_simctl.sh <device> <out-dir> <shots-file> [app-path]}"
OUT="${2:?out dir}"
SHOTS="${3:?shots file}"
APP="${4:-}"
HERE="${0:A:h}"

if [[ -z "${BUNDLE_ID:-}" ]]; then
  BUNDLE_ID=$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import asc_client as a; print(a.BUNDLE_ID or "")' "$HERE")
fi
[[ -n "$BUNDLE_ID" ]] || { echo "no BUNDLE_ID (set it, or add bundleId to asc.json)"; exit 1; }

# Accept a device name ("iPhone 17 Pro Max") or a UDID.
if [[ "$DEV" =~ ^[0-9A-F-]{36}$ ]]; then
  UDID="$DEV"
else
  UDID=$(xcrun simctl list devices available -j | python3 -c '
import json, sys
name = sys.argv[1]
for runtime, devs in json.load(sys.stdin)["devices"].items():
    for d in devs:
        if d["name"] == name:
            print(d["udid"]); sys.exit()
' "$DEV")
  [[ -n "$UDID" ]] || { echo "no available simulator named \"$DEV\" (xcrun simctl list devices)"; exit 1; }
fi

# Newest Debug-iphonesimulator build of the app, unless one was given.
if [[ -z "$APP" ]]; then
  APP=$(ls -dt ~/Library/Developer/XcodeBuildMCP/workspaces/*/DerivedData/*/Build/Products/Debug-iphonesimulator/*.app \
               ~/Library/Developer/Xcode/DerivedData/*/Build/Products/Debug-iphonesimulator/*.app 2>/dev/null \
        | while read -r a; do
            [[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$a/Info.plist" 2>/dev/null)" == "$BUNDLE_ID" ]] && { echo "$a"; break; }
          done)
fi
[[ -d "$APP" ]] || { echo "no built .app for $BUNDLE_ID — build for the simulator first, or pass app-path"; exit 1; }
echo "==> $BUNDLE_ID on $DEV ($UDID)"
echo "==> app: $APP"
mkdir -p "$OUT"

xcrun simctl boot "$UDID" 2>/dev/null || true
xcrun simctl bootstatus "$UDID" -b >/dev/null
xcrun simctl ui "$UDID" appearance "${APPEARANCE:-light}" >/dev/null 2>&1 || true
xcrun simctl install "$UDID" "$APP"

# 9:41 is the convention. (iPad status bars show the date, which simctl can't pin.)
xcrun simctl status_bar "$UDID" override \
  --time "9:41" --batteryState charged --batteryLevel 100 \
  --cellularMode active --cellularBars 4 --wifiMode active --wifiBars 3 \
  --dataNetwork wifi >/dev/null 2>&1 || true

# The data container only exists after a first launch.
xcrun simctl launch "$UDID" "$BUNDLE_ID" >/dev/null 2>&1 || true
sleep 4
xcrun simctl terminate "$UDID" "$BUNDLE_ID" >/dev/null 2>&1 || true
CONTAINER=$(xcrun simctl get_app_container "$UDID" "$BUNDLE_ID" data)
export UDID BUNDLE_ID CONTAINER

if [[ -n "${SETUP_HOOK:-}" ]]; then
  echo "==> setup hook: $SETUP_HOOK"
  zsh "$SETUP_HOOK"
fi

echo "==> capturing into $OUT"
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%%#*}"
  [[ -z "${line// /}" ]] && continue
  if [[ "$line" == @hook* ]]; then
    hook="${${line#@hook}// /}"
    xcrun simctl terminate "$UDID" "$BUNDLE_ID" >/dev/null 2>&1 || true
    zsh "${SHOTS:h}/$hook"
    continue
  fi
  args=(${(z)line})
  name="${args[1]}"; settle="${args[2]}"; launch=("${(@)args[3,-1]}")
  xcrun simctl terminate "$UDID" "$BUNDLE_ID" >/dev/null 2>&1 || true
  sleep 1
  xcrun simctl launch "$UDID" "$BUNDLE_ID" "${launch[@]}" >/dev/null
  sleep "$settle"
  xcrun simctl io "$UDID" screenshot --type=png "$OUT/$name.png" >/dev/null 2>&1
  echo "    $name.png"
done < "$SHOTS"

xcrun simctl status_bar "$UDID" clear >/dev/null 2>&1 || true
echo "==> done"
sips -g pixelWidth -g pixelHeight "$OUT"/*.png 2>/dev/null | awk '/\.png/{f=$0; sub(/.*\//,"",f)} /pixelWidth/{w=$2} /pixelHeight/{print "    " f "  " w "x" $2}'
