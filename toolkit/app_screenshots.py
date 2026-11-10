#!/usr/bin/env python3
"""Upload App Store listing screenshots via the App Store Connect API.

    app_screenshots.py                          # dry run: every family found, every locale
    app_screenshots.py --apply                  # upload into empty sets
    app_screenshots.py --apply --replace        # clear the chosen sets and re-upload
    app_screenshots.py --only ipad13            # one family (repeatable)
    app_screenshots.py --locale en-US           # one locale (repeatable)
    app_screenshots.py --platform MAC_OS        # the Mac version's screenshots
    app_screenshots.py --families               # print the family table and exit

Listing screenshots hang off an **appScreenshotSet**, which hangs off a version's
*localization*, one set per display type. The set must exist before anything can
be reserved into it; then each file goes through the three-step asset flow:
reserve, upload (pre-signed, no auth header), commit with an MD5.

Folder layout, under asc.json `paths.screenshots` (default
`marketing/screenshots/upload`):

    <family>/01-hero.png               shared: used for every locale without its own
    <locale>/<family>/01-hero.png      localized: wins for that locale

Files upload in natural filename order, which is the order on the product page,
so the number prefix is the running order — and the first frame is the only one
most people see. PNG or JPEG, **no alpha channel** (checked locally, fatal).

Sizes are *reported*, never enforced: Apple has changed accepted sizes before and
the API is the authority, so a guess here would reject valid files. A size that
matches none of the family's known canvases is flagged in the dry run.

Projects with legacy flat file names can map them instead of moving files:

    "screenshots": {"patterns": {"iphone65": "^AppStore\\\\d+\\\\.png$"}}

in asc.json; patterns are matched against file names directly in
`paths.screenshots`.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asc_client import (ASC, APP_PLATFORMS, CONFIG, LOCALES, PLATFORMS,  # noqa: E402
                        alpha_problem, delivery_state, dimensions, md5,
                        project_path, upload)

# family -> (screenshotDisplayType, platform, known canvases (portrait w x h), note)
FAMILIES = {
    "iphone69": ("APP_IPHONE_67", "IOS", [(1320, 2868), (1290, 2796), (1260, 2736)],
                 '6.9"/6.7" — the primary iPhone slot; Apple scales it down for smaller iPhones'),
    "iphone65": ("APP_IPHONE_65", "IOS", [(1284, 2778), (1242, 2688)],
                 '6.5" — accepted in place of 6.9" when 6.9" is not provided'),
    "iphone61": ("APP_IPHONE_61", "IOS", [(1206, 2622), (1179, 2556)], '6.3"/6.1" — optional'),
    "iphone55": ("APP_IPHONE_55", "IOS", [(1242, 2208)], '5.5" — only for apps supporting old devices'),
    "ipad13":   ("APP_IPAD_PRO_3GEN_129", "IOS", [(2064, 2752), (2048, 2732)],
                 '13" — REQUIRED if the app runs on iPad; 12.9" (2048x2732) alone does not satisfy it'),
    "ipad11":   ("APP_IPAD_PRO_3GEN_11", "IOS", [(1668, 2420), (1668, 2388), (1640, 2360), (1488, 2266)],
                 '11" — optional'),
    "watch":    ("APP_WATCH_ULTRA", "IOS", [(422, 514), (410, 502)], "Apple Watch Ultra — the primary watch slot"),
    "watch10":  ("APP_WATCH_SERIES_10", "IOS", [(416, 496), (374, 446)], "Apple Watch Series 10"),
    "mac":      ("APP_DESKTOP", "MAC_OS", [(2880, 1800), (2560, 1600), (1440, 900), (1280, 800)],
                 "Mac — 16:10, landscape"),
    "tv":       ("APP_APPLE_TV", "TV_OS", [(3840, 2160), (1920, 1080)], "Apple TV — landscape"),
    "vision":   ("APP_APPLE_VISION_PRO", "VISION_OS", [(3840, 2160)], "Apple Vision Pro"),
}
PLATFORM_FAMILIES = {p: tuple(n for n, f in FAMILIES.items() if f[1] == p) for p in PLATFORMS}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


def natural(path: Path):
    """02 before 10."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", path.name)]


def images_in(folder: Path) -> list:
    if not folder.is_dir():
        return []
    return sorted((f for f in folder.iterdir() if f.suffix.lower() in IMAGE_SUFFIXES),
                  key=natural)


def files_for(root: Path, family: str, locale: str) -> tuple:
    """(files, source label) for one family in one locale."""
    patterns = ((CONFIG.get("screenshots") or {}).get("patterns") or {})
    if family in patterns:
        rx = re.compile(patterns[family])
        return sorted((f for f in images_in(root) if rx.match(f.name)), key=natural), "pattern"
    localized = images_in(root / locale / family)
    if localized:
        return localized, f"{locale}/{family}"
    return images_in(root / family), f"{family} (shared)"


def size_flag(path: Path, family: str) -> str:
    size = dimensions(path)
    if size is None:
        return "?"
    known = FAMILIES[family][2]
    ok = size in known or (size[1], size[0]) in known
    label = f"{size[0]}x{size[1]}"
    return label if ok else f"{label}   <- not a known {family} canvas " \
                            f"({', '.join(f'{w}x{h}' for w, h in known)})"


def screenshot_set(api: ASC, loc_id: str, display_type: str, create: bool):
    """(set id, existing screenshots), creating the set if asked."""
    for s in api.paged(f"/v1/appStoreVersionLocalizations/{loc_id}/appScreenshotSets"):
        if s["attributes"].get("screenshotDisplayType") == display_type:
            return s["id"], api.paged(f"/v1/appScreenshotSets/{s['id']}/appScreenshots")
    if not create:
        return None, []
    created = api.post("/v1/appScreenshotSets", {"data": {
        "type": "appScreenshotSets",
        "attributes": {"screenshotDisplayType": display_type},
        "relationships": {"appStoreVersionLocalization": {
            "data": {"type": "appStoreVersionLocalizations", "id": loc_id}}},
    }})
    return created["data"]["id"], []


def put(api: ASC, set_id: str, path: Path) -> str:
    asset = api.post("/v1/appScreenshots", {"data": {
        "type": "appScreenshots",
        "attributes": {"fileName": path.name, "fileSize": path.stat().st_size},
        "relationships": {"appScreenshotSet": {"data": {"type": "appScreenshotSets", "id": set_id}}},
    }})["data"]
    upload(asset["attributes"].get("uploadOperations") or [], path)
    api.patch(f"/v1/appScreenshots/{asset['id']}", {"data": {
        "type": "appScreenshots", "id": asset["id"],
        "attributes": {"uploaded": True, "sourceFileChecksum": md5(path)}}})
    return delivery_state(api, f"/v1/appScreenshots/{asset['id']}")


def print_families() -> None:
    for name, (display, platform, sizes, note) in FAMILIES.items():
        print(f"  {name:<9} {display:<24} {platform:<9} "
              f"{', '.join(f'{w}x{h}' for w, h in sizes)}\n            {note}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="actually upload")
    parser.add_argument("--replace", action="store_true",
                        help="delete every existing screenshot in the chosen sets first")
    parser.add_argument("--only", choices=sorted(FAMILIES), action="append",
                        help="limit to a device family (repeatable)")
    parser.add_argument("--locale", action="append",
                        help=f"limit to a locale (repeatable; default: {', '.join(LOCALES)})")
    parser.add_argument("--platform", choices=PLATFORMS, default=APP_PLATFORMS[0])
    parser.add_argument("--bundle-id")
    parser.add_argument("--version", help="version string (default: the editable one)")
    parser.add_argument("--dir", type=Path, help="root folder (default: asc.json paths.screenshots)")
    parser.add_argument("--families", action="store_true", help="print the family table and exit")
    args = parser.parse_args()

    if args.families:
        print_families()
        return

    root = args.dir or project_path("screenshots")
    allowed = PLATFORM_FAMILIES[args.platform]
    wrong = [n for n in (args.only or ()) if n not in allowed]
    if wrong:
        sys.exit(f"--only {', '.join(wrong)} is not a {args.platform} family "
                 f"(its families: {', '.join(allowed)})")
    families = args.only or allowed
    locales = args.locale or list(LOCALES)

    plan = {}  # (locale, family) -> files
    for locale in locales:
        for family in families:
            files, source = files_for(root, family, locale)
            if files:
                plan[(locale, family)] = (files, source)
    if not plan:
        sys.exit(f"no screenshots found under {root} for {args.platform} "
                 f"(expected <family>/NN-name.png with family in: {', '.join(families)})")

    problems = [(f, why) for files, _ in plan.values() for f in files if (why := alpha_problem(f))]
    for path, why in problems:
        print(f"  INVALID {path.relative_to(root)}  {why}")
    if problems:
        sys.exit(f"\n{len(problems)} file(s) would be rejected — fix before uploading")

    api = ASC()
    app = api.app_id(args.bundle_id)
    version = api.store_version(app, args.version, args.platform)
    print(f"{args.platform} version {version['attributes'].get('versionString')} "
          f"[{version['attributes'].get('appStoreState')}]\n")

    total = 0
    for (locale, family), (files, source) in plan.items():
        display_type = FAMILIES[family][0]
        loc = api.version_localization(version["id"], locale)
        if loc is None:
            print(f"[{locale} {family}] no {locale} localization on this version — "
                  "add the locale in App Store Connect (or push its listing) first\n")
            continue
        set_id, existing = screenshot_set(api, loc["id"], display_type, create=False)
        print(f"[{locale} {family}] {display_type} from {source}: "
              f"{len(existing)} already uploaded")
        if existing and not args.replace:
            print("  nothing to do — pass --replace to clear and re-upload\n")
            continue
        for path in files:
            print(f"  UPLOAD  {path.name}  ({size_flag(path, family)}, "
                  f"{path.stat().st_size / 1e6:.2f} MB)")
        if existing:
            print(f"  DELETE  {len(existing)} existing first")
        if len(files) > 10:
            print("  !! more than 10 files; App Store Connect keeps at most 10 per set")
        print()
        if not args.apply:
            total += len(files)
            continue
        for s in existing:
            api.delete(f"/v1/appScreenshots/{s['id']}")
        set_id, _ = screenshot_set(api, loc["id"], display_type, create=True)
        for path in files:
            print(f"  uploaded {path.name}  {put(api, set_id, path)}")
            total += 1
        print()

    print(f"done: {total} uploaded" if args.apply
          else f"dry run: {total} to upload. Re-run with --apply to write.")


if __name__ == "__main__":
    main()
