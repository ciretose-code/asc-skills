#!/usr/bin/env python3
"""Push the App Store listing copy from `<paths.listing>/<locale>.txt`.

The listing is the one piece of store metadata that is easy to leave out of
version control, and then it drifts: text typed into a web form has nothing to
diff and nothing to review, so a description keeps advertising something the app
no longer does and nobody notices. Keeping it in a file means a change to the
copy is a diff in a pull request.

    listing.py                        # dry run: field-by-field diff
    listing.py --apply                # writes
    listing.py --locale de-DE         # another locale (default: first in asc.json)
    listing.py --all-locales          # every locale in asc.json
    listing.py --platform MAC_OS      # the Mac version's copy
    listing.py --version 1.8
    listing.py --pull                 # first time: write the live copy to the file

An app record has one App Store version per platform. The description, what's
new and URLs belong to a *version*, so each platform is pushed separately with
`--platform`; the name, subtitle and privacy URL are app-level and shared.

A locale that has a file here but no localization in App Store Connect yet is
*created* on `--apply` (both the app-info and the version localization).

`<locale>.txt` is the shared copy, used for the app's first platform in
asc.json. Where another platform's version genuinely differs, put just those
fields in
`<locale>.<PLATFORM>.txt`, e.g. `en-US.MAC_OS.txt`; it is layered over the shared
file when pushing that platform. `--pull --platform MAC_OS` writes only the fields
that differ from the shared file.

Dry run is the default and prints only the fields that differ, with lengths, so
a change is obvious and a no-op is silent.

Apple splits these across two resources, and the split matters:

  * **appInfoLocalizations** — name, subtitle, privacy policy URL. App-level;
    survives across versions and can only be edited while the app info is
    editable.
  * **appStoreVersionLocalizations** — description, keywords, promotional text,
    what's new, support and marketing URLs. Version-level, so a new version starts from a
    copy of the last one and drifts from there.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asc_client import (ASC, APP_PLATFORMS, EDITABLE, LOCALES, PLATFORMS, TOOLKIT,  # noqa: E402
                        project_path)

LISTING_DIR = project_path("listing")
BASE_PLATFORM = APP_PLATFORMS[0]  # the platform <locale>.txt describes

# Which resource owns which field.
APP_INFO_FIELDS = ("name", "subtitle", "privacyPolicyUrl")
VERSION_FIELDS = ("description", "keywords", "promotionalText", "whatsNew",
                  "supportUrl", "marketingUrl")

# App Store Connect's documented limits. Checked locally so an overlong field
# names itself rather than coming back as an opaque 409.
LIMITS = {"name": 30, "subtitle": 30, "keywords": 100,
          "promotionalText": 170, "description": 4000, "whatsNew": 4000}


def parse(path: Path) -> dict[str, str]:
    """`key: value` lines, then `--- key ---` blocks for the long fields.

    Deliberately not YAML: the description is multi-paragraph prose full of
    colons, em dashes and quotes, and the point of this file is that a human
    edits it and reviews the diff.
    """
    text = path.read_text()
    head, *blocks = re.split(r"^--- (\w+) ---$", text, flags=re.M)

    fields: dict[str, str] = {}
    for line in head.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()

    # re.split hands back [key, body, key, body, ...]
    for key, body in zip(blocks[0::2], blocks[1::2]):
        fields[key] = body.strip()

    for key, limit in LIMITS.items():
        if key in fields and len(fields[key]) > limit:
            sys.exit(f"{path.name}: {key} is {len(fields[key])} characters, "
                     f"limit is {limit}")
    return fields


# Short fields print as `key: value`; these are long or multi-line, so they get a block.
BLOCK_FIELDS = ("description", "whatsNew")

PULL_HEADER = """\
# App Store listing -- {locale}
#
# The source of truth for what App Store Connect shows. Push it with:
#     python3 {toolkit}/listing.py            (dry run: read the diff first)
#     python3 {toolkit}/listing.py --apply
#
# Written from the live listing by `listing.py --pull`, so a first push changes
# only what is edited here. Always run listing.py without --apply first and read
# the diff. Only keys present here are pushed. whatsNew is per-release: rewrite it
# for each version rather than appending.
#
# Limits, checked before anything is sent: name 30, subtitle 30, keywords 100,
# promotionalText 170, description 4000, whatsNew 4000.
"""


def override_path(locale: str, platform: str) -> Path:
    """Fields that differ on a non-iOS version live beside the shared file."""
    return LISTING_DIR / f"{locale}.{platform}.txt"


def render(fields: dict[str, str], locale: str = "en-US", note: str = "") -> str:
    """The inverse of `parse`: the file format, from a dict of live values."""
    out = [PULL_HEADER.format(locale=locale, toolkit=TOOLKIT)]
    if note:
        out.append("".join(f"# {line}\n" for line in note.splitlines()))
    heads = [k for k in APP_INFO_FIELDS + VERSION_FIELDS
             if fields.get(k) and k not in BLOCK_FIELDS and "\n" not in fields[k]]
    blocks = [k for k in APP_INFO_FIELDS + VERSION_FIELDS
              if fields.get(k) and (k in BLOCK_FIELDS or "\n" in fields[k])]
    out.extend(f"{k}: {fields[k]}" for k in heads)
    for k in blocks:
        out.append(f"\n--- {k} ---\n{fields[k].strip()}")
    return "\n".join(out) + "\n"


def report(kind: str, wanted: dict, live: dict, keys) -> list[str]:
    changed = []
    for key in keys:
        if key not in wanted:
            continue
        new, old = wanted[key], (live.get(key) or "")
        if new == old:
            print(f"  ok      {key}")
            continue
        changed.append(key)
        print(f"  UPDATE  {key}  ({len(old)} -> {len(new)} chars)")
        if len(new) < 200 and len(old) < 200:
            print(f"            was: {old!r}")
            print(f"            now: {new!r}")
    return changed


def localizations(api: ASC, path: str) -> dict:
    return {l["attributes"].get("locale"): l for l in api.paged(path)}


def push_locale(api: ASC, app: str, info: dict, version: dict, locale: str, args) -> int:
    shared = LISTING_DIR / f"{locale}.txt"
    # The base platform is the shared file itself; another platform pulls into
    # (and pushes from) an override file layered over it.
    base = args.platform == BASE_PLATFORM
    path = shared if base else override_path(locale, args.platform)
    if args.pull:
        if path.exists() and not args.force:
            sys.exit(f"{path} already exists; pass --force to overwrite it")
        wanted: dict = {}
    else:
        if not shared.exists():
            sys.exit(f"no listing file at {shared} (run with --pull to create it "
                     "from the live listing)")
        wanted = parse(shared)
        extra = override_path(locale, args.platform)
        if not base and extra.exists():
            wanted.update(parse(extra))
            print(f"(layering {extra.name} over {shared.name}: {', '.join(parse(extra))})")

    info_loc = localizations(api, f"/v1/appInfos/{info['id']}/appInfoLocalizations").get(locale)
    ver_loc = localizations(
        api, f"/v1/appStoreVersions/{version['id']}/appStoreVersionLocalizations").get(locale)

    print(f"== {locale}")
    if args.pull:
        if info_loc is None or ver_loc is None:
            sys.exit(f"no {locale} localization in App Store Connect to pull")
        live = {**info_loc["attributes"], **ver_loc["attributes"]}
        if not base and shared.exists():
            shared_fields = parse(shared)
            live = {k: v for k, v in live.items() if shared_fields.get(k) != v}
        path.parent.mkdir(parents=True, exist_ok=True)
        note = ("" if base else
                f"Only the fields that differ on the {args.platform} version. Layered over "
                f"{shared.name} when pushing --platform {args.platform}.")
        path.write_text(render(live, locale, note), encoding="utf-8")
        got = [k for k in APP_INFO_FIELDS + VERSION_FIELDS if live.get(k)]
        print(f"wrote {path}\n  fields: {', '.join(got)}\n")
        return 0

    # A version already on sale accepts only promotional text; everything else
    # waits for the next version. Say so instead of sending a doomed PATCH.
    live_version = version["attributes"].get("appStoreState") not in EDITABLE
    live_info = info["attributes"].get("appStoreState") not in EDITABLE
    if live_version:
        print(f"(version {version['attributes'].get('versionString')} is live: only "
              "promotionalText can change; other differences wait for the next version)")
    print("app-level (name, subtitle, privacy policy):")
    info_changed = report("appInfo", wanted, (info_loc or {}).get("attributes", {}),
                          APP_INFO_FIELDS)
    print("version-level (description, keywords, promo, what's new, URLs):")
    ver_changed = report("version", wanted, (ver_loc or {}).get("attributes", {}),
                         VERSION_FIELDS)
    if live_info and info_changed:
        print(f"  (held: {', '.join(info_changed)} — app info is not editable)")
        info_changed = []
    if live_version:
        held = [k for k in ver_changed if k != "promotionalText"]
        if held:
            print(f"  (held: {', '.join(held)} — need an editable version)")
        ver_changed = [k for k in ver_changed if k == "promotionalText"]
    if info_loc is None:
        print(f"  CREATE  {locale} app-info localization")
        if "name" not in wanted:
            sys.exit(f"{shared.name}: a new locale needs at least `name:`")
    if ver_loc is None:
        print(f"  CREATE  {locale} version localization")
    total = len(info_changed) + len(ver_changed)
    if not args.apply or not total:
        print()
        return total

    if info_changed:
        attrs = {k: wanted[k] for k in info_changed}
        if info_loc is None:
            api.post("/v1/appInfoLocalizations", {"data": {
                "type": "appInfoLocalizations", "attributes": {"locale": locale, **attrs},
                "relationships": {"appInfo": {"data": {"type": "appInfos", "id": info["id"]}}}}})
        else:
            api.patch(f"/v1/appInfoLocalizations/{info_loc['id']}", {"data": {
                "type": "appInfoLocalizations", "id": info_loc["id"], "attributes": attrs}})
        print(f"  wrote {', '.join(info_changed)}")
    if ver_changed:
        attrs = {k: wanted[k] for k in ver_changed}
        if ver_loc is None:
            api.post("/v1/appStoreVersionLocalizations", {"data": {
                "type": "appStoreVersionLocalizations",
                "attributes": {"locale": locale, **attrs},
                "relationships": {"appStoreVersion": {
                    "data": {"type": "appStoreVersions", "id": version["id"]}}}}})
        else:
            api.patch(f"/v1/appStoreVersionLocalizations/{ver_loc['id']}", {"data": {
                "type": "appStoreVersionLocalizations", "id": ver_loc["id"], "attributes": attrs}})
        print(f"  wrote {', '.join(ver_changed)}")
    print()
    return total


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="actually write; without it this only prints a diff")
    parser.add_argument("--locale", action="append",
                        help=f"locale to push (repeatable; default: {LOCALES[0]})")
    parser.add_argument("--all-locales", action="store_true",
                        help=f"every locale in asc.json ({', '.join(LOCALES)})")
    parser.add_argument("--bundle-id")
    parser.add_argument("--platform", choices=PLATFORMS, default=BASE_PLATFORM,
                        help=f"which store version to edit (default: {BASE_PLATFORM})")
    parser.add_argument("--version", help="version string to edit (default: the "
                        "version on --platform that is still editable)")
    parser.add_argument("--pull", action="store_true",
                        help="write the live listing to the file instead of pushing it")
    parser.add_argument("--force", action="store_true",
                        help="with --pull, overwrite an existing file")
    args = parser.parse_args()
    locales = list(LOCALES) if args.all_locales else (args.locale or [LOCALES[0]])

    api = ASC()
    app = api.app_id(args.bundle_id)
    info = api.editable_app_info(app)
    version = api.store_version(app, args.version, args.platform)
    print(f"app info      {info['id']}  [{info['attributes'].get('appStoreState')}]")
    print(f"{args.platform} version {version['attributes'].get('versionString'):<5} "
          f"{version['id']}  [{version['attributes'].get('appStoreState')}]\n")

    total = sum(push_locale(api, app, info, version, loc, args) for loc in locales)
    if args.pull:
        return
    if not args.apply:
        print(f"dry run: {total} field(s) to update. Re-run with --apply to write.")
    elif not total:
        print("nothing to do")
    else:
        print(f"done: {total} field(s) updated")


if __name__ == "__main__":
    main()
