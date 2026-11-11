---
name: setup
description: Use when a project needs App Store Connect API tooling for the first time, when an asc.json is missing, when ASC credentials fail ("missing App Store Connect credentials", 401 NOT_AUTHORIZED), or when migrating an app's copied Scripts/asc/ folder onto the shared toolkit.
---

# App Store Connect setup

## Overview

One canonical toolkit drives every app. A project holds only an **`asc.json`**
(what the app is, where its copy and images live) plus its own copy files. The
scripts live in this plugin, at `<this skill's base directory>/../../toolkit`
— call that `$T` below. Every other `asc:*` skill assumes this setup is done.

## Toolkit conventions (all scripts)

- **Dry run is the default.** Writes need `--apply`. Always run the dry run first,
  show the user the plan, and get a yes before `--apply` — it writes to the live
  store, and some things (Family Sharing on, a submission) cannot be undone.
- Run from anywhere inside the project; the scripts walk up to `asc.json`
  (or honour `$ASC_CONFIG`).
- **`--help` is the interface.** Run it before inventing flags:
  `python3 $T/<script>.py --help` or `zsh $T/<script>.sh --help`.
- If `python3` fails with an SSL/`_ssl` import error (a broken pyenv/Homebrew
  OpenSSL), use `/usr/bin/python3`.

## Steps

1. **Credentials, once per machine.** Check `~/.config/asc/.env`. If it already
   has a working key, skip to step 2 — one key with the **App Manager** role
   serves every app on the team; never mint a key per app.
   If absent, create the key with the user (Account Holder or Admin can do this):
   1. Open [App Store Connect → Users and Access → Integrations →
      App Store Connect API](https://appstoreconnect.apple.com/access/integrations/api).
   2. Under **Team Keys**, click **Generate API Key** (or **+**). Name it
      something like `asc-toolkit`, set Access to **App Manager**, Generate.
   3. Copy the **Issuer ID** (top of the page) and the key's **Key ID**.
      Download the `.p8` — Apple only offers it once.
   4. `mkdir -m 700 ~/.config/asc`, move the `.p8` there, `chmod 600` it.
      Never put the `.p8` inside a repo or `~/Code`.
   5. Copy `$T/.env.example` to `~/.config/asc/.env` and set `ASC_ISSUER_ID`,
      `ASC_KEY_ID`, and `ASC_KEY_PATH` (path to the `.p8`, or paste the PEM
      inline). A project `.env` or legacy `Scripts/asc/.env` overrides this
      file, so delete stale ones.
2. **Deps:** `python3 -m pip install -r $T/requirements.txt`.
3. **Project config:** copy `$T/asc.example.json` to the repo root as `asc.json`.
   Fill `bundleId`, `platforms` (`IOS`, `MAC_OS`, `TV_OS`, `VISION_OS`),
   `devices` (`iphone`, `ipad`, `watch` — drives required screenshot sets),
   `locales` (first = primary), `storekit`, `xcodeproj`. Delete unused keys.
   Read the real values from the Xcode project; don't guess the bundle id.
   Watch apps / extensions with their own App ID go in `extraBundleIds`.
   Keep or edit `paths` from the example, or delete the whole `paths` object to
   use the toolkit defaults (`marketing/listing`, `marketing/screenshots/upload`,
   etc. — see `asc.example.json`).
4. **gitignore:** `.env`, `.env.*`, `!.env.example`, `*.p8`,
   `image_upload_failures.json`. `asc.json` is committed — it holds no secrets.
5. **Seed the copy from the live store** (existing apps): `python3 $T/listing.py --pull`.
6. **Verify:** `python3 $T/status.py` (read-only). "no editable version" just
   means nothing is in preparation — pass `--version <live>` to read the live one.
7. **Capabilities:** `python3 $T/bundle_capabilities.py`; list expected ones under
   `capabilities` in asc.json so absences are called out.

## Migrating a project with its own `Scripts/asc/`

Map its existing folders in asc.json `paths` (e.g. `"listing": "Marketing/listing"`)
and flat screenshot names via `screenshots.patterns` — no files need moving. Run
each replaced script's dry run through `$T` and confirm it reports `ok`/no changes
before deleting the old copy. The legacy `Scripts/asc/.env` is still read.

## Common mistakes

| Mistake | Fix |
|---|---|
| Key with Developer role | Writes 403; needs App Manager |
| `bundleId` copied from a sibling app | Read `PRODUCT_BUNDLE_IDENTIFIER` from the pbxproj |
| Committing `.env` or the `.p8` | gitignore the family, keep the key in `~/.config/asc/` |
| Running `--apply` first | Dry run, show the user, then apply |
