#!/usr/bin/env python3
"""Prepare an App Store version for review: create it, attach the build, fill in
App Review details, set the release type — and, only when asked, submit it.

    version.py                               # dry run: what would change on the editable version
    version.py --create 1.3 --apply          # create version 1.3 (default: the project's MARKETING_VERSION)
    version.py --attach-build --apply        # attach the newest VALID build for that version
    version.py --review --apply              # push App Review contact + notes
    version.py --release-type MANUAL --apply # MANUAL | AFTER_APPROVAL
    version.py --encryption-exempt --apply   # answer export compliance on the build (no non-exempt crypto)
    version.py --submit --apply              # SUBMIT FOR REVIEW (needs status.py at zero blockers)

Steps compose: `--create 1.3 --attach-build --review --apply` does all three.

App Review details come from two files:

  * contact — `review_contact.txt`, looked up in `<paths.review>/` then
    `~/.config/asc/` (the same person reviews every app, and a phone number does
    not belong in a public repo):

        firstName: Ada
        lastName: Lovelace
        phone: +1 555 0100
        email: review@example.com

  * notes — `<paths.review>/notes.txt` in the project, prose for the reviewer
    (how to reach the feature, that no account is needed, …). Version-controlled
    so it cannot drift from how the app behaves. Optional; limit 4000.

  An optional `<paths.review>/demo_account.txt` (`username:` / `password:`) marks
  sign-in as required. Keep it out of git if it is real.

Submitting is a separate, explicit flag because it is the one irreversible-ish
step here: it puts the version in Apple's queue and emails the team. The script
refuses unless a build is attached.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asc_client import (ASC, APP_PLATFORMS, EDITABLE, PLATFORMS,  # noqa: E402
                        project_path, project_version)

NOTES_LIMIT = 4000


def kv_file(path: Path) -> dict:
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and ":" in line:
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


def find_contact() -> Path | None:
    for folder in (project_path("review"), Path("~/.config/asc").expanduser()):
        if (folder / "review_contact.txt").exists():
            return folder / "review_contact.txt"
    return None


def wanted_review() -> dict:
    attrs = {}
    contact = find_contact()
    if contact:
        c = kv_file(contact)
        for src, dst in (("firstName", "contactFirstName"), ("lastName", "contactLastName"),
                         ("phone", "contactPhone"), ("email", "contactEmail")):
            if c.get(src):
                attrs[dst] = c[src]
    notes = project_path("review") / "notes.txt"
    if notes.exists():
        text = notes.read_text().strip()
        if len(text) > NOTES_LIMIT:
            sys.exit(f"{notes}: {len(text)} characters, limit is {NOTES_LIMIT}")
        attrs["notes"] = text
    demo = project_path("review") / "demo_account.txt"
    if demo.exists():
        d = kv_file(demo)
        attrs.update(demoAccountRequired=True, demoAccountName=d.get("username", ""),
                     demoAccountPassword=d.get("password", ""))
    else:
        attrs["demoAccountRequired"] = False
    return attrs


def newest_build(api: ASC, app: str, version: str, platform: str) -> dict | None:
    builds = api.get("/v1/builds", **{
        "filter[app]": app, "filter[preReleaseVersion.version]": version,
        "filter[preReleaseVersion.platform]": platform,
        "filter[processingState]": "VALID", "filter[expired]": "false",
        "sort": "-uploadedDate", "limit": 1}).get("data", [])
    return builds[0] if builds else None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="actually write")
    parser.add_argument("--bundle-id")
    parser.add_argument("--platform", choices=PLATFORMS, default=APP_PLATFORMS[0])
    parser.add_argument("--version", help="version to act on (default: the editable one)")
    parser.add_argument("--create", nargs="?", const="", metavar="X.Y",
                        help="create this version (default: MARKETING_VERSION)")
    parser.add_argument("--attach-build", action="store_true")
    parser.add_argument("--build", help="build number to attach (default: newest VALID)")
    parser.add_argument("--review", action="store_true", help="push App Review details")
    parser.add_argument("--release-type", choices=("MANUAL", "AFTER_APPROVAL"))
    parser.add_argument("--encryption-exempt", action="store_true",
                        help="set usesNonExemptEncryption=false on the attached build")
    parser.add_argument("--submit", action="store_true", help="submit for App Review")
    args = parser.parse_args()

    api = ASC()
    app = api.app_id(args.bundle_id)
    mode = "" if args.apply else "(dry run) "

    # -- the version -----------------------------------------------------------
    if args.create is not None:
        wanted = args.create or project_version()
        if not wanted:
            sys.exit("no version given and no MARKETING_VERSION found in the project")
        existing = {v["attributes"]["versionString"]: v for v in api.versions(app, args.platform)}
        if wanted in existing:
            print(f"  ok      version {wanted} exists "
                  f"[{existing[wanted]['attributes'].get('appStoreState')}]")
            version = existing[wanted]
        else:
            editable = [v for v in existing.values()
                        if v["attributes"].get("appStoreState") in EDITABLE]
            if editable:
                sys.exit(f"version {editable[0]['attributes']['versionString']} is still "
                         "editable; App Store Connect allows one at a time. Rename it in the "
                         "web UI or pass --version to work on it.")
            print(f"  {mode}CREATE  {args.platform} version {wanted}")
            if not args.apply:
                print("\nre-run with --apply to create it; later steps need it to exist.")
                return
            version = api.post("/v1/appStoreVersions", {"data": {
                "type": "appStoreVersions",
                "attributes": {"platform": args.platform, "versionString": wanted},
                "relationships": {"app": {"data": {"type": "apps", "id": app}}}}})["data"]
    else:
        version = api.store_version(app, args.version, args.platform)
    vid = version["id"]
    vstr = version["attributes"]["versionString"]
    print(f"{args.platform} version {vstr} [{version['attributes'].get('appStoreState')}]")

    # -- build -----------------------------------------------------------------
    attached = (api.get_soft(f"/v1/appStoreVersions/{vid}/build") or {}).get("data")
    if args.attach_build:
        if args.build:
            rows = api.get("/v1/builds", **{"filter[app]": app, "filter[version]": args.build,
                                            "filter[preReleaseVersion.version]": vstr}).get("data", [])
            build = rows[0] if rows else None
        else:
            build = newest_build(api, app, vstr, args.platform)
        if build is None:
            sys.exit(f"no VALID build for {vstr} yet — has Xcode Cloud / the upload finished "
                     "processing? (`status.py` lists recent builds)")
        if attached and attached["id"] == build["id"]:
            print(f"  ok      build {build['attributes']['version']} attached")
        else:
            print(f"  {mode}ATTACH  build {build['attributes']['version']}"
                  + (f" (replacing {attached['attributes']['version']})" if attached else ""))
            if args.apply:
                api.patch(f"/v1/appStoreVersions/{vid}/relationships/build",
                          {"data": {"type": "builds", "id": build["id"]}})
                attached = build

    if args.encryption_exempt:
        if not attached:
            sys.exit("no build attached; pass --attach-build too")
        current = api.get(f"/v1/builds/{attached['id']}")["data"]["attributes"]
        if current.get("usesNonExemptEncryption") is False:
            print("  ok      export compliance: no non-exempt encryption")
        else:
            print(f"  {mode}SET     usesNonExemptEncryption=false on build "
                  f"{attached['attributes']['version']}  (tip: set "
                  "ITSAppUsesNonExemptEncryption=NO in Info.plist so every build carries it)")
            if args.apply:
                api.patch(f"/v1/builds/{attached['id']}", {"data": {
                    "type": "builds", "id": attached["id"],
                    "attributes": {"usesNonExemptEncryption": False}}})

    # -- release type ----------------------------------------------------------
    if args.release_type:
        now = version["attributes"].get("releaseType")
        if now == args.release_type:
            print(f"  ok      release type {now}")
        else:
            print(f"  {mode}SET     release type {now} -> {args.release_type}")
            if args.apply:
                api.patch(f"/v1/appStoreVersions/{vid}", {"data": {
                    "type": "appStoreVersions", "id": vid,
                    "attributes": {"releaseType": args.release_type}}})

    # -- App Review details ----------------------------------------------------
    if args.review:
        want = wanted_review()
        if not any(k.startswith("contact") for k in want):
            print("  !!      no review_contact.txt found (project review folder or ~/.config/asc/)")
        detail = (api.get_soft(f"/v1/appStoreVersions/{vid}/appStoreReviewDetail") or {}).get("data")
        live = (detail or {}).get("attributes", {})
        changed = {k: v for k, v in want.items() if live.get(k) != v}
        for k in want:
            shown = "***" if "Password" in k else repr(want[k])[:70]
            print(f"  {'UPDATE' if k in changed else 'ok    '}  review {k}"
                  + (f": {shown}" if k in changed else ""))
        if changed and args.apply:
            if detail:
                api.patch(f"/v1/appStoreReviewDetails/{detail['id']}", {"data": {
                    "type": "appStoreReviewDetails", "id": detail["id"], "attributes": changed}})
            else:
                api.post("/v1/appStoreReviewDetails", {"data": {
                    "type": "appStoreReviewDetails", "attributes": want,
                    "relationships": {"appStoreVersion": {
                        "data": {"type": "appStoreVersions", "id": vid}}}}})

    # -- submit ----------------------------------------------------------------
    if args.submit:
        if not attached:
            sys.exit("refusing to submit: no build attached")
        print(f"  {mode}SUBMIT  {args.platform} {vstr} for App Review")
        if args.apply:
            sub = api.post("/v1/reviewSubmissions", {"data": {
                "type": "reviewSubmissions", "attributes": {"platform": args.platform},
                "relationships": {"app": {"data": {"type": "apps", "id": app}}}}})["data"]
            api.post("/v1/reviewSubmissionItems", {"data": {
                "type": "reviewSubmissionItems",
                "relationships": {
                    "reviewSubmission": {"data": {"type": "reviewSubmissions", "id": sub["id"]}},
                    "appStoreVersion": {"data": {"type": "appStoreVersions", "id": vid}}}}})
            api.patch(f"/v1/reviewSubmissions/{sub['id']}", {"data": {
                "type": "reviewSubmissions", "id": sub["id"], "attributes": {"submitted": True}}})
            print("  submitted — Apple emails the team when review starts")

    if not args.apply:
        print("\ndry run. Re-run with --apply to write.")


if __name__ == "__main__":
    main()
