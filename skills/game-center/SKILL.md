---
name: game-center
description: Use when adding or changing Game Center achievements for an app in App Store Connect — achievement definitions, points, localizations, 512×512 achievement icons, failed icon uploads — or checking Game Center is enabled on the App ID.
---

# Game Center achievements

## Overview

Achievements are defined in the repo as `achievements.json` and synced
idempotently — never entered by hand. `$T` = `<this skill's base directory>/../../toolkit`.
Requires asc:setup.

## Files (asc.json `paths`)

- `achievements` (default `marketing/game-center/achievements.json`):

```json
[{"id": "myapp.first.win", "referenceName": "First Win", "title": "First Win",
  "description": "Win your first game.", "points": 10, "hidden": false,
  "sortOrder": 100, "icon": "trophy.fill",
  "localizations": {"ja": {"title": "…", "description": "…"}}}]
```

`hidden: true` hides it until earned; one `description` is used before and after
earning. `icon` is free-form input for your icon generator (e.g. an SF Symbol).

- `achievementIcons` (default `marketing/game-center/icons/`): `<id>.png`,
  **512×512**, no alpha. Generate them from code (e.g. a Swift script drawing an
  SF Symbol over a brand gradient, colour picked by a stable hash of the id) so
  they re-render identically.

`id` becomes the vendor identifier and **can never change or be reused** once
created. Apple's guidance is ≤100 points per achievement and ~1000 in total;
the total is a convention the API does not enforce.

## Workflow

1. `python3 $T/bundle_capabilities.py` — `GAME_CENTER` should be on.
2. Edit `achievements.json` / icons.
3. `python3 $T/game_center_achievements.py` (dry run) → show the user →
   `--apply`. See `--help` for flags (`--skip-images`, `--only-failed-images`
   retries icons logged in `image_upload_failures.json`, which should be
   gitignored).
4. Re-run the dry run: expect `unchanged` for every achievement.
5. New achievements go live with the next app version submission (asc:release).

Leaderboards have no script — create and localize them in the App Store Connect
web UI, and record their ids in the repo alongside the code that submits scores.

## Common mistakes

| Mistake | Fix |
|---|---|
| Renaming an `id` to fix a typo | Creates a second achievement; change `referenceName`/`title` instead |
| Icon with alpha / wrong size | 512×512 RGB (`images.py check`) |
