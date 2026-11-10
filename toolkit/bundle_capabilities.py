#!/usr/bin/env python3
"""Report -- and optionally enable -- capabilities on the app's App ID.

The question this exists to answer is "does the App ID actually carry iCloud /
Game Center / In-App Purchase", which is otherwise several clicks into the
developer portal and easy to assume rather than check. A missing iCloud
capability builds fine, then the app quietly falls back to a local-only store.

    bundle_capabilities.py                         # report
    bundle_capabilities.py --enable ICLOUD --apply

Expected capabilities can be listed in asc.json as
`"capabilities": {"ICLOUD": "CloudKit sync", "GAME_CENTER": "leaderboards"}`;
any that are absent are called out.

An absent row is a prompt to look, not proof of a problem: not every capability
appears as an explicit `bundleIdCapabilities` row. This script reports what the
API says and refuses to editorialise beyond that.
"""
from __future__ import annotations

import argparse
import sys

from asc_client import ASC, CONFIG, require_bundle_id

# Capabilities the app expects, from asc.json:  "capabilities": {"ICLOUD": "why"}
INTERESTING = dict(CONFIG.get("capabilities") or {})


def report(api: ASC, identifier: str) -> tuple[str, set[str]]:
    # filter[identifier] is a prefix-ish match on some accounts, so the exact
    # identifier is re-checked rather than trusting the first row back.
    rows = api.paged("/v1/bundleIds", **{"filter[identifier]": identifier})
    exact = [b for b in rows if b["attributes"].get("identifier") == identifier]
    if not exact:
        found = ", ".join(sorted(b["attributes"].get("identifier", "?") for b in rows))
        sys.exit(f"no App ID with identifier {identifier}"
                 + (f"\n  the filter returned: {found}" if found else ""))
    bundle = exact[0]
    ref = bundle["id"]
    print(f"App ID {identifier}  [{bundle['attributes'].get('platform', '?')}]  -> {ref}")

    # Not `paged`: this relationship rejects `limit` outright with a 400, and a
    # bundle ID has few enough capabilities that a single page is always enough.
    caps = api.get(f"/v1/bundleIds/{ref}/bundleIdCapabilities").get("data", [])
    present = {c["attributes"].get("capabilityType") for c in caps}

    print(f"  {len(caps)} capability rows:")
    for cap in sorted(present):
        note = INTERESTING.get(cap, "")
        print(f"    on      {cap}" + (f"  -- {note}" if note else ""))
    for cap, note in INTERESTING.items():
        if cap in present:
            continue
        print(f"    absent  {cap}  -- {note}")
    print()
    return ref, present


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bundle-id", help="App ID to check (default: asc.json bundleId)")
    parser.add_argument("--enable", metavar="CAPABILITY", action="append", default=[],
                        help="capability type to add, e.g. ICLOUD (repeatable)")
    parser.add_argument("--apply", action="store_true",
                        help="actually write; without it this only prints the plan")
    args = parser.parse_args()

    api = ASC()
    ref, present = report(api, require_bundle_id(args.bundle_id))

    if not args.enable:
        return

    todo = [c for c in args.enable if c not in present]
    for cap in [c for c in args.enable if c in present]:
        print(f"  ok      {cap} already enabled")
    for cap in todo:
        print(f"  ENABLE  {cap}")

    if not todo:
        return
    if not args.apply:
        print(f"\ndry run: {len(todo)} to enable. Re-run with --apply to write.")
        return

    for cap in todo:
        api.post("/v1/bundleIdCapabilities", {
            "data": {
                "type": "bundleIdCapabilities",
                "attributes": {"capabilityType": cap},
                "relationships": {
                    "bundleId": {"data": {"type": "bundleIds", "id": ref}}
                },
            }
        })
        print(f"  enabled {cap}")
    print(f"\ndone: {len(todo)} enabled")


if __name__ == "__main__":
    main()
