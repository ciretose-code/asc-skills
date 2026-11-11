# asc-skills

Claude Code skills for publishing iOS / macOS apps through App Store Connect,
backed by **one** shared Python toolkit for the App Store Connect API.

Every app keeps only an `asc.json` (bundle id, platforms, locales, paths) and its
own copy and images. The scripts live here, so a fix reaches every app at once
instead of drifting across per-project copies.

## Install

```
/plugin marketplace add ciretose-code/asc-skills     # or a local path to this repo
/plugin install asc@asc-skills
```

Then, once per machine: put the App Store Connect API key in `~/.config/asc/.env`
(template: `toolkit/.env.example`) and `python3 -m pip install -r toolkit/requirements.txt`.
In each project, run `/asc:setup`.

## Skills

| Skill | For |
|---|---|
| `/asc:setup` | Credentials, `asc.json`, migrating an app's old `Scripts/asc/` copy |
| `/asc:screenshots` | Plan, capture (4 methods), caption, validate, upload; IAP review shots |
| `/asc:listing` | What's New, description, keywords, promo text, subtitle, URLs, locales |
| `/asc:release` | Create version, attach build, export compliance, review details, readiness, submit |
| `/asc:in-app-purchases` | IAPs and subscriptions from the `.storekit` file |
| `/asc:app-preview` | Record and encode an App Preview video to spec |
| `/asc:game-center` | Achievements + icons from `achievements.json` |

## Toolkit

All scripts are **dry run by default** (`--apply` writes), read current state
first and are safe to re-run. Run them from anywhere inside a project.

| Script | Does |
|---|---|
| `status.py` | Read-only submission readiness report; exits non-zero on blockers |
| `version.py` | Create version, attach build, export compliance, review details, release type, submit |
| `listing.py` | Push/pull listing copy, per locale and platform |
| `app_screenshots.py` | Upload screenshot sets for every device family and locale |
| `images.py` | `check` / `flatten` / `fit` images to App Store canvases |
| `capture_simctl.sh` | Capture a shot list on a simulator via launch arguments |
| `compose_captions.py` | Caption raw captures inside the canvas |
| `make_preview.sh` | Encode an App Preview to Apple's spec, with checks |
| `iap_setup.py` | IAP products, localizations, prices, review notes from `.storekit` |
| `iap_review_screenshots.py` | IAP review screenshots |
| `subscription_setup.py` | Subscription groups, subscriptions, availability, prices |
| `subscription_review_screenshots.py` | Subscription review screenshots |
| `bundle_capabilities.py` | Report / enable App ID capabilities |
| `game_center_achievements.py` | Sync Game Center achievements and icons |

`toolkit/ENDPOINTS.md` records the API traps found by running against the live API.

## Verification status

Read paths of every script were exercised against six live apps (iOS, Mac,
iOS+Mac, iPhone+iPad+Watch, Game Center) on 2026-11-10, matching the
per-project scripts they replaced.
Write paths of `listing.py` (PATCH), `app_screenshots.py`, the IAP/subscription
scripts and the achievements sync are proven by the per-project scripts they
came from. **Not yet exercised live:** `version.py` (all writes), `listing.py`
creating a new locale, and screenshot uploads for Watch / TV / Vision.
