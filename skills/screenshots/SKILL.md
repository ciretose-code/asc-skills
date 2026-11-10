---
name: screenshots
description: Use when creating, recapturing, captioning, resizing, validating or uploading App Store screenshots or in-app purchase review screenshots — including "screenshots are the wrong size", alpha-channel rejections, missing iPad 13" sets, localized screenshot sets, or "Missing Metadata" on an IAP.
---

# App Store screenshots

## Overview

Screenshots are a pipeline: **plan → capture → compose → validate → upload**.
Each stage has several options. Pick per stage with the user, then run the stage.
Toolkit: `$T` = `<this skill's base directory>/../../toolkit`. Requires asc:setup.

## 1. Plan

- **Which sets** — `python3 $T/app_screenshots.py --families` prints every family,
  display type and canvas. Minimums: iPhone 6.9" (or 6.5" substitute); **iPad 13"
  if the app runs on iPad — 12.9" alone does not satisfy it**; Mac 16:10; Watch,
  TV, Vision if shipped. Up to 10 per set, per locale.
- **Shot list** — ordered, with a caption each. Lead with the differentiator:
  frame 1 is the only one most people see. Write it to `marketing/screenshots/README.md`.
- **Deterministic state** — the same data on every device and every recapture.

## 2. Capture — choose one (details in `capture-methods.md`)

| Option | Best for |
|---|---|
| **A. Launch args + `capture_simctl.sh`** | Any iOS app; DEBUG-only hooks jump to each screen with injected state. No UI automation. |
| **B. XCUITest / fastlane `snapshot`** | Many locales × devices; flows needing taps. |
| **C. SwiftUI `ImageRenderer` snapshot test** | Paywalls / IAP review shots; single views; Mac. Exact, no simulator. |
| **D. Manual** (simulator ⌘S, device, Mac `screencapture -l`) | One-offs. |

Capture at the **largest canvas natively** (iPhone 17 Pro Max → 1320×2868; iPad
Pro 13" → 2064×2752) — never upscale. Pin the status bar (A does: 9:41, full).

## 3. Compose — choose one

- **Raw** — upload the captures as-is.
- **Captions generated** — `python3 $T/compose_captions.py <raw> <out> --captions captions.json --field <brand hex> --ink <hex>`. Keeps canvas size, writes RGB.
- **Designed by hand** (Pixelmator/Figma/Sketch templates with device frames) —
  export at the exact family canvas, RGB, and keep the templates in the repo.

## 4. Validate and fix

```sh
python3 $T/images.py check <folder>              # size, alpha, which family; non-zero on problems
python3 $T/images.py flatten <folder>            # RGBA -> RGB in place
python3 $T/images.py fit --family ipad13 <src> <dst>   # stopgap pad-to-canvas
```

## 5. Upload

Lay files out as `<paths.screenshots>/[<locale>/]<family>/NN-name.png` (number =
running order), then:

```sh
python3 $T/app_screenshots.py                 # dry run — show the user
python3 $T/app_screenshots.py --apply         # fills empty sets
python3 $T/app_screenshots.py --apply --replace --only ipad13   # redo one set
```

Needs an editable version (asc:release). Confirm with `python3 $T/status.py`.

## IAP / subscription review screenshots

App Review only, one per product; without it the product sits in **Missing
Metadata**. Show the purchase UI as it appears in the app. Name files by product
suffix in `paths.iapReview` (`pro.png` → `<bundleId>.pro`). iPhone: **1284×2778**
is the safe size. Mac: 16:10 — a wrong ratio fails *after* upload as
`IMAGE_BAD_ASPECT_RATIO`. Upload: `iap_review_screenshots.py`,
`subscription_review_screenshots.py` (dry run, then `--apply`; `--replace` clears a
stuck `AWAITING_UPLOAD`).

## Common mistakes

| Symptom | Cause |
|---|---|
| "wrong size" on a correctly sized file | **Alpha channel.** simctl and ImageRenderer write RGBA — flatten |
| iPad section still incomplete | 12.9" (2048×2732) uploaded; 13" (2064×2752) required |
| Shots differ between devices / recaptures | State not injected — use fixed seeds/fixtures |
| Padlocks / empty states in frames | Entitlements absent in the simulator — add a DEBUG-only "own everything" hook, compiled out of release |
| iPad frames show today's date | simctl can't pin the iPad date; note it or crop in compose |
| Upload "already has one" after a failure | Uncommitted reservation — rerun with `--replace` |
