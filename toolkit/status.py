#!/usr/bin/env python3
"""Read-only readiness report: what is still missing before this version can be submitted.

    status.py                       # the editable version on the app's first platform
    status.py --platform MAC_OS     # the editable Mac version
    status.py --version 1.8

Makes GET requests only, so it is safe to run at any time and never needs
`--apply`. Prints one line per requirement and exits non-zero if any blocker
remains, so it can gate a release script.

It reports what App Store Connect will insist on at submission, in the order
they tend to be forgotten: a processed build attached to the version, the store
copy and URLs, screenshots for every device family the app ships on, the
category and age rating, and reviewer contact details.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asc_client import (ASC, APP_PLATFORMS, CONFIG, LOCALES, PLATFORMS,  # noqa: E402
                        project_version)
from app_screenshots import FAMILIES  # noqa: E402  (display types)

LOCALE = LOCALES[0]
DEVICES = set(CONFIG.get("devices") or ("iphone",))

# What App Store Connect insists on, per platform: each entry is satisfied by
# any one of its families. iPhone 6.5" substitutes for 6.9"; iPad 12.9" does
# NOT substitute for 13" (both upload into the same 13" display type, though).
REQUIRED_SETS = {
    "IOS": [("iphone", ("iphone69", "iphone65"))]
           + ([("ipad", ("ipad13",))] if "ipad" in DEVICES else [])
           + ([("watch", ("watch", "watch10"))] if "watch" in DEVICES else []),
    "MAC_OS": [("mac", ("mac",))],
    "TV_OS": [("tv", ("tv",))],
    "VISION_OS": [("vision", ("vision",))],
}
blockers: list[str] = []


def check(ok: bool, label: str, detail: str = "", *, blocker: bool = True) -> None:
    """Print one requirement. Failing ones count as blockers unless marked advisory."""
    if ok:
        print(f"  ok       {label}" + (f"  {detail}" if detail else ""))
        return
    print(f"  {'MISSING ' if blocker else 'note    '} {label}" + (f"  {detail}" if detail else ""))
    if blocker:
        blockers.append(label)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bundle-id")
    parser.add_argument("--platform", choices=PLATFORMS, default=APP_PLATFORMS[0])
    parser.add_argument("--version", help="version string (default: the editable version "
                        "on --platform)")
    args = parser.parse_args()

    api = ASC()
    app = api.app_id(args.bundle_id)
    version = api.store_version(app, args.version, args.platform)
    vid = version["id"]
    vstr = version["attributes"].get("versionString")
    print(f"{args.bundle_id or app}  {args.platform} version {vstr}  "
          f"[{version['attributes'].get('appStoreState')}]\n")

    print("version:")
    local = project_version()
    check(local == vstr, "project version matches App Store Connect",
          f"(project {local}, App Store Connect {vstr})")

    print("\nbuild:")
    builds = api.get("/v1/builds", **{"filter[app]": app, "sort": "-uploadedDate",
                                      "limit": 5}).get("data", [])
    for b in builds[:3]:
        a = b["attributes"]
        print(f"  build    {a.get('version')}  {a.get('processingState')}  "
              f"uploaded {a.get('uploadedDate', '?')[:10]}"
              + ("  EXPIRED" if a.get("expired") else ""))
    attached = api.get_soft(f"/v1/appStoreVersions/{vid}/build")
    attached_data = (attached or {}).get("data")
    if attached_data:
        a = attached_data["attributes"]
        check(a.get("processingState") == "VALID", "a processed build is attached",
              f"(build {a.get('version')}, {a.get('processingState')})")
    else:
        check(False, "a processed build is attached",
              "— none attached; pick one under the version's Build section")

    print("\nstore copy:")
    info = api.editable_app_info(app)
    info_loc = next((l for l in api.paged(f"/v1/appInfos/{info['id']}/appInfoLocalizations")
                     if l["attributes"].get("locale") == LOCALE), None)
    ver_loc = next((l for l in api.paged(f"/v1/appStoreVersions/{vid}/appStoreVersionLocalizations")
                    if l["attributes"].get("locale") == LOCALE), None)
    ia = (info_loc or {}).get("attributes", {})
    va = (ver_loc or {}).get("attributes", {})
    check(bool(ia.get("name")), "name")
    check(bool(ia.get("privacyPolicyUrl")), "privacy policy URL")
    check(bool(va.get("description")), "description")
    check(bool(va.get("keywords")), "keywords")
    check(bool(va.get("supportUrl")), "support URL")
    released = [v for v in api.versions(app, args.platform)
                if v["id"] != vid and v["attributes"].get("appStoreState")
                in ("READY_FOR_SALE", "REPLACED_WITH_NEW_VERSION", "REMOVED_FROM_SALE",
                    "DEVELOPER_REMOVED_FROM_SALE")]
    if released:
        check(bool(va.get("whatsNew")), "what's new", "(required for an update)")
    else:
        print("  n/a      what's new  (first release: App Store Connect does not take it)")
    check(bool(ia.get("subtitle")), "subtitle", blocker=False)
    check(bool(va.get("promotionalText")), "promotional text", blocker=False)

    print("\nscreenshots:")
    sets = {}
    if ver_loc:
        for s in api.paged(f"/v1/appStoreVersionLocalizations/{ver_loc['id']}/appScreenshotSets"):
            sets[s["attributes"].get("screenshotDisplayType")] = len(
                api.paged(f"/v1/appScreenshotSets/{s['id']}/appScreenshots"))
    for label, families in REQUIRED_SETS[args.platform]:
        counts = {f: sets.get(FAMILIES[f][0], 0) for f in families}
        best = max(counts.values()) if counts else 0
        check(best > 0, f"{label} screenshots",
              "  ".join(f"{f}={n}" for f, n in counts.items()))

    print("\napp information:")
    category = api.get_soft(f"/v1/appInfos/{info['id']}/relationships/primaryCategory")
    check(bool((category or {}).get("data")), "primary category")
    age = api.get_soft(f"/v1/appInfos/{info['id']}/ageRatingDeclaration")
    check(bool((age or {}).get("data")), "age rating declaration")

    app_attrs = api.get(f"/v1/apps/{app}")["data"]["attributes"]
    check(bool(app_attrs.get("contentRightsDeclaration")), "content rights declaration",
          f"({app_attrs.get('contentRightsDeclaration') or 'unset'})")

    print("\nreview:")
    review = (api.get_soft(f"/v1/appStoreVersions/{vid}/appStoreReviewDetail") or {}).get("data")
    ra = (review or {}).get("attributes", {})
    check(bool(ra.get("contactEmail") and ra.get("contactPhone")),
          "reviewer contact details", "(email and phone)")
    check(bool(ra.get("notes")), "review notes", blocker=False)

    print()
    if blockers:
        print(f"{len(blockers)} blocker(s): " + ", ".join(blockers))
        sys.exit(1)
    print("zero blockers")


if __name__ == "__main__":
    main()
