# Capture methods in detail

## A. Launch arguments + `capture_simctl.sh` (recommended default for iOS)

Synthetic taps rarely drive custom gestures (SpriteKit drags, canvases) and can
fail to activate `NavigationLink`s, so instead the app learns to **boot straight
into each screen** from launch arguments, and the harness relaunches it per shot.

1. Add DEBUG-only hooks in the app (all inside `#if DEBUG`, so no shipped build
   can be driven by them):
   - `-screen <name>` / `-item <id>` — route to a screen on launch.
   - `-ownAll` (or similar) — force every entitlement owned, *without* writing to
     defaults. StoreKit entitlements don't exist under `simctl launch`, and an
     entitlements-as-truth store will otherwise shoot padlocks.
   - `-palette`, `-AppleInterfaceStyle Dark` (system arg) for variants.
   - Hide transient UI (resume banners, tooltips, review prompts) in this mode.
2. Produce **real state, not mock pixels**: generate it by running the app's own
   model code (e.g. a small `swiftc` tool that plays legal moves from a fixed
   seed), serialize it, and inject it as the app's save file. Record the seeds so
   recaptures are byte-reproducible.
3. Write a shots file and, if needed, a setup hook:

   ```
   # marketing/screenshots/shots.txt   name  settle  launch-args...
   01-hero      7  -ownAll -screen game
   02-library   7  -ownAll -screen library
   @hook swap_state.sh
   03-detail    8  -ownAll -screen detail -item sample
   ```

   ```sh
   # setup.sh — runs once with $UDID $BUNDLE_ID $CONTAINER exported
   cp fixtures/save.json "$CONTAINER/Library/Application Support/save.json"
   /usr/libexec/PlistBuddy -c "Add :onboarded bool true" \
     "$CONTAINER/Library/Preferences/$BUNDLE_ID.plist" 2>/dev/null || true
   ```

4. Build for the simulator (XcodeBuildMCP `build_sim`), then per device:

   ```sh
   SETUP_HOOK=marketing/screenshots/setup.sh \
     zsh $T/capture_simctl.sh "iPhone 17 Pro Max" marketing/screenshots/raw/iphone69 marketing/screenshots/shots.txt
   SETUP_HOOK=... zsh $T/capture_simctl.sh "iPad Pro 13-inch (M5)" marketing/screenshots/raw/ipad13 ...
   APPEARANCE=dark ...   # dark-mode set
   ```

   Need a canvas no stock simulator has (e.g. 1284×2778 for IAP review)? Create one:
   `xcrun simctl create "IAP-1284" com.apple.CoreSimulator.SimDeviceType.iPhone-14-Plus <runtime>`.

Anything random at launch (a puzzle seed) makes that shot non-reproducible —
add a seed launch arg.

## B. XCUITest / fastlane snapshot

Best when there are many locales. A typical setup:

```ruby
# fastlane/Snapfile
devices(["iPhone 17 Pro Max", "iPad Pro 13-inch (M5)"])
languages(["en-US", "ja-JP", "es-ES"])
scheme("App"); xcargs("-testPlan Screenshots")
override_status_bar(true); clear_previous_screenshots(true)
output_directory("./fastlane/screenshots")
```

A UI test calls `snapshot("01-hero")` at each beat (after `setupSnapshot(app)`;
pass the same DEBUG launch args as in A). Run `fastlane snapshot`, then move
output into `<paths.screenshots>/<locale>/<family>/` for `app_screenshots.py`
(fastlane's own `deliver` upload also works, but keep one uploader per project).

## C. SwiftUI `ImageRenderer` snapshot test

For a paywall/IAP review image or a single view, render the real view in a unit
test so it tracks the code:

```swift
@MainActor func testPaywallSnapshot() throws {
    let view = PaywallView(store: .preview).frame(width: 428, height: 926)
    let renderer = ImageRenderer(content: view); renderer.scale = 3   // 1284x2778
    let data = try XCTUnwrap(renderer.uiImage?.pngData())  // nsImage on macOS
    let url = FileManager.default.temporaryDirectory.appending(path: "pro.png")
    try data.write(to: url); print("SNAPSHOT_PATH=\(url.path)")
}
```

The file lands in the test host's sandbox — copy it out from the printed path.
Output is RGBA: run `images.py flatten`.

## D. Manual

- Simulator: ⌘S saves to the Desktop at native resolution (RGBA).
- Device: side+volume; AirDrop to the Mac. Device canvases differ from App Store
  canvases — check with `images.py check`, fit or re-export.
- Mac app window: `screencapture -o -l <windowid> out.png` (`-o` drops the
  shadow); size the window to 1440×900 points on a Retina display → 2880×1800.
