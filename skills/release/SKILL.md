---
name: release
description: Use when shipping an app update or first release to the App Store — creating the new App Store Connect version, checking what still blocks submission, attaching a TestFlight/Xcode Cloud build, export compliance, App Review contact and notes, release type, or submitting for review.
---

# Releasing a version

## Overview

`status.py` is the read-only checklist; `version.py` does the steps. Run status
first and last. `$T` = `<this skill's base directory>/../../toolkit`. Requires asc:setup.

## Workflow

1. **Bump `MARKETING_VERSION`** in the project (branch + PR per the repo's rules).
   Don't add CI build-number scripts if Xcode Cloud manages build numbers.
2. **Create the version** (one editable version per platform at a time):
   `python3 $T/version.py --create` (defaults to MARKETING_VERSION) → `--apply`.
3. **Copy:** asc:listing — rewrite What's New; check the description still holds.
4. **Screenshots:** a new version inherits the previous set. Recapture only if the
   UI visibly changed (asc:screenshots).
5. **New IAPs/subscriptions?** asc:in-app-purchases. First-time products must be
   submitted **with** this version.
6. **Build:** wait for the build to finish processing (Xcode Cloud → TestFlight),
   then `python3 $T/version.py --attach-build --encryption-exempt` → `--apply`.
   Only use `--encryption-exempt` if the app uses no non-exempt crypto; better,
   set `ITSAppUsesNonExemptEncryption = NO` in Info.plist once.
7. **Review details:** `version.py --review` pushes contact from
   `~/.config/asc/review_contact.txt` (template `$T/review_contact.example.txt`;
   keep phone/email out of repos) and notes from `<paths.review>/notes.txt` —
   tell the reviewer how to reach every gated feature and that no account is
   needed (or add `demo_account.txt`, gitignored).
8. **Release type:** `--release-type MANUAL` (you press release) or
   `AFTER_APPROVAL`.
9. **Gate:** `python3 $T/status.py` must print `zero blockers` (exit 0).
10. **Submit — only on the user's explicit go-ahead in this conversation.**
    Show the status output, ask, then `python3 $T/version.py --submit --apply`.
    Submission emails the team and enters Apple's queue.

## What status.py checks

Project version = ASC version · processed (VALID) build attached · name, privacy
URL, description, keywords, support URL · What's New (updates only) · required
screenshot sets per asc.json `devices` · primary category · age rating · content
rights · reviewer contact. Subtitle, promo text, review notes are advisory.

## Web-UI-only items (no script — walk the user through)

App Privacy nutrition label · age-rating questionnaire answers · pricing &
availability for a paid app · phased release toggle · a first-ever app record ·
Game Center leaderboards (achievements: asc:game-center).

## Common mistakes

| Symptom | Fix |
|---|---|
| "no editable version" | Step 2 — or `--version <x.y>` to read the live one |
| "version x is still editable" on create | Only one at a time; finish or rename it |
| No VALID build for the version | Still processing, or the build's version ≠ MARKETING_VERSION |
| Missing Compliance on the build | Step 6 / Info.plist key |
| IAP not reviewed with the release | First-time IAPs must ride this submission |
| Rejected: reviewer couldn't find a feature | Notes must give the exact path to it |
