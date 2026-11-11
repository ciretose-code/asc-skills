---
name: app-preview
description: Use when making an App Store App Preview video — scripting, recording gameplay or app footage, encoding to Apple's preview spec, or when a preview is rejected for resolution, frame rate, length or silent/missing audio.
---

# App Preview video

## Overview

Optional, but the one way to sell *motion* (a reveal, an animation) that stills
only half show. Pipeline: **script → record on device → encode → upload**.
`$T` = `<this skill's base directory>/../../toolkit`.

## 1. Script (15–30 s, aim ~28)

A beat table: cold open on the hook (same idea as screenshot 1, text overlay),
core interaction, the payoff, a quick montage, end card with icon + tagline.
Real footage only — no device frames, no hands, no licensed music. Either the
app's own audio or silence.

## 2. Record

- Use **iOS Screen Recording** (Control Center, long-press → Microphone **off**).
  **QuickTime "New Movie Recording" drops app audio** — takes come back silent.
- Ring/silent switch **on** (an `.ambient` audio session is silent when muted),
  the app's sound setting on, volume up, Do Not Disturb on.
- Have the needed state ready (unlocked content, discovered items).
- One continuous take, 45–60 s, longer than needed; trim later. AirDrop to Mac.

## 3. Encode

```sh
zsh $T/make_preview.sh --help
zsh $T/make_preview.sh take.mov out.mp4 <start-s> <duration-s>
CANVAS=1200x1600 PAD_COLOR=0xE8E6DC zsh $T/make_preview.sh ...   # iPad, app bg padding
```

Canvases: iPhone **886×1920** (all modern sizes; landscape 1920×886), iPad
1200×1600, Mac/TV 1920×1080. It scales-to-fit and pads with `PAD_COLOR` (use the
app's background), H.264 High ≤4.0, 30 fps, ~11 Mbps, stereo AAC 256k; adds a
silent stereo track if the source has none. It prints PASS/FAIL for every spec
item and the **peak audio level** — `-91 dB`/`-inf` means a silent take: fix the
recording, not the encode. Needs `ffmpeg` (`brew install ffmpeg`).

## 4. Upload

In App Store Connect (version → Previews and Screenshots → the device size),
up to 3 per locale; choose the poster frame there. Uploading needs an editable
version (asc:release).

## Common mistakes

| Symptom | Fix |
|---|---|
| Rejected resolution | Device-native size uploaded — encode to the preview canvas |
| Silent preview | QuickTime capture or muted phone — re-record with iOS Screen Recording |
| Over 30 s | Trim with start/duration args |
| Shows UI not in the app / a mockup | Previews must be captured from the app itself |
