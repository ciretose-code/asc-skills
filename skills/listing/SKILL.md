---
name: listing
description: Use when writing or updating App Store product page text — What's New / release notes, description, keywords, promotional text, subtitle, app name, support/marketing/privacy URLs — or adding a new App Store locale.
---

# App Store listing copy

## Overview

The listing lives in the repo as `<paths.listing>/<locale>.txt` (default
`marketing/listing/en-US.txt`), so every copy change is a reviewable diff, and is
pushed with `listing.py`. Never type copy into the web form — it drifts.
`$T` = `<this skill's base directory>/../../toolkit`. Requires asc:setup.

## File format

```
name: MyApp                         # app-level ┐ appInfoLocalizations:
subtitle: A calm puzzle             #           │ shared by every version
privacyPolicyUrl: https://…         #           ┘
keywords: puzzle,daily,calm         # version-level ┐ appStoreVersionLocalizations:
promotionalText: …                  #               │ a new version starts as a
supportUrl: https://…               #               │ copy of the last one
marketingUrl: https://…             #               ┘
--- description ---
Multi-paragraph prose…
--- whatsNew ---
This release's notes…
```

Only keys present are pushed. Per-platform differences go in
`<locale>.MAC_OS.txt`, layered over the shared file for `--platform MAC_OS`.

## Workflow

1. **No file yet?** `python3 $T/listing.py --pull` writes the live copy, so the
   first push changes only what is edited.
2. **Edit the file.** Rules per field:

| Field | Limit | Notes |
|---|---|---|
| name | 30 | Changes need a new version in review |
| subtitle | 30 | Benefit, not a repeat of the name |
| keywords | 100 | Commas, no spaces; don't repeat words in name/subtitle (already indexed); singulars |
| promotionalText | 170 | The only field editable **without** a review — use it for timely news |
| description | 4000 | First 2–3 lines show above "more"; lead with what makes it different |
| whatsNew | 4000 | Rewrite every release — replace, never append. Not accepted on a 1.0 |

3. **Dry run:** `python3 $T/listing.py` prints field-by-field `was/now` with
   lengths and fails locally on any overlong field. Show it to the user.
4. **Apply** after a yes: `python3 $T/listing.py --apply`. Re-run the dry run: it
   should show all `ok`.

Flags: `--locale de-DE` (repeatable), `--all-locales`, `--platform MAC_OS`,
`--version 1.3`. A locale with a file but no App Store Connect localization is
**created** on `--apply` (needs at least `name:`).

## Writing What's New

1. Find the last shipped version (`python3 $T/status.py --version <live>`, or the
   git tag), then collect what changed: `git log --oneline <tag>..HEAD`, merged
   PR titles (`gh pr list --state merged --search "merged:>YYYY-MM-DD"`), closed
   issues.
2. Keep only what a **user** would notice. Drop refactors, CI, tests, internal
   tooling.
3. Shape: one warm lead line, then 2–6 short bullets ("•"), new things first,
   then improvements, then "Fixes" in a single line. Plain language, the app's
   own voice, no issue numbers, no "bug fixes and performance improvements"
   filler when real changes exist.
4. Check the description still matches the app — a release that adds or removes
   a feature usually means a description edit too.

## Common mistakes

| Mistake | Fix |
|---|---|
| Editing the live (READY_FOR_SALE) version | Version-level fields need an editable version — create one (asc:release) |
| What's New on version 1.0 | App Store Connect rejects it; leave it out of the file |
| Appending to last release's What's New | Replace it |
| Opaque 409 on push | Usually an overlong field or a forbidden character; the dry run checks limits |
| Promising things the app doesn't do ("no ads", "offline") | Verify each claim against the code before pushing |
