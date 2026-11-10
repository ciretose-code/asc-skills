#!/usr/bin/env python3
"""Upload the subscription's App Review screenshot via the App Store Connect API.

The same three-step asset flow as `iap_review_screenshots.py` (reserve, upload,
commit), against the subscription's own resource — a subscription stays in Missing
Metadata until it has one.

    subscription_review_screenshots.py                    # dry run: every subscription
    subscription_review_screenshots.py --apply            # upload
    subscription_review_screenshots.py --apply --replace  # overwrite
    subscription_review_screenshots.py --only pro.annual  # one product suffix

Files are `<paths.iapReview>/<suffix>.png`, named for the product id minus the
product prefix (`<bundleId>.pro.annual` -> `pro.annual.png`), the same naming as
the one-time purchases.

`ImageRenderer` writes RGBA and App Store Connect refuses an alpha channel while
complaining about the *size*, so an RGBA file is flattened onto white into a temporary
copy before upload. Every pixel of the render is already opaque, so nothing changes
visibly; the original in the repository is left alone.

The aspect ratio is the other way a good-looking file fails: macOS screenshots must be
16:10 (2560x1600 and 1280x800 have both been accepted), and anything else reaches
`assetDeliveryState` as `IMAGE_BAD_ASPECT_RATIO` *after* the upload appears to succeed.
The record it leaves behind then reports "already has one", so retry with `--replace`.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asc_client import ASC, API, product_prefix, project_path  # noqa: E402
from iap_review_screenshots import md5, upload  # noqa: E402  (same asset flow)

SHOTS_DIR = project_path("iapReview")
RESOURCE = "subscriptionAppStoreReviewScreenshots"


def flattened(path: Path) -> Path:
    """`path` itself if it has no alpha channel, else an RGB copy in a temp file."""
    from PIL import Image
    with Image.open(path) as im:
        if im.mode not in ("RGBA", "LA") and "transparency" not in im.info:
            return path
        rgba = im.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, (255, 255, 255))
        canvas.paste(rgba, mask=rgba.getchannel("A"))
    out = Path(tempfile.mkdtemp()) / path.name
    canvas.save(out, "PNG")
    print(f"  flattened alpha channel -> {out}")
    return out


def subscriptions(api: ASC, app_id: str) -> list:
    out = []
    for group in api.paged(f"/v1/apps/{app_id}/subscriptionGroups"):
        out.extend(api.paged(f"/v1/subscriptionGroups/{group['id']}/subscriptions"))
    return out


def push(api: ASC, sub: dict, path: Path, args) -> int:
    sub_id = sub["id"]
    product = sub["attributes"].get("productId")
    print(f"{product} -> {sub_id}  [{sub['attributes'].get('state')}]")
    existing = api.get_soft(f"/v1/subscriptions/{sub_id}/appStoreReviewScreenshot")
    existing = (existing or {}).get("data")
    if existing and not args.replace:
        state = (existing["attributes"].get("assetDeliveryState") or {}).get("state")
        print(f"  ok      already has one ({existing['attributes'].get('fileName')}, {state}); "
              f"--replace to overwrite")
        return 0
    print(f"  {'REPLACE' if existing else 'UPLOAD '}  {path.name}")
    if not args.apply:
        return 1
    if existing:
        api.delete(f"/v1/{RESOURCE}/{existing['id']}")
    flat = flattened(path)
    reserved = api.post(f"/v1/{RESOURCE}", {"data": {
        "type": RESOURCE,
        "attributes": {"fileName": path.name, "fileSize": flat.stat().st_size},
        "relationships": {"subscription": {"data": {"type": "subscriptions", "id": sub_id}}},
    }})["data"]
    upload(reserved["attributes"].get("uploadOperations") or [], flat)
    api.patch(f"/v1/{RESOURCE}/{reserved['id']}", {"data": {
        "type": RESOURCE, "id": reserved["id"],
        "attributes": {"uploaded": True, "sourceFileChecksum": md5(flat)}}})
    state: dict = {}
    for _ in range(12):
        data = api.get(f"/v1/{RESOURCE}/{reserved['id']}")["data"]
        state = data["attributes"].get("assetDeliveryState") or {}
        if state.get("errors"):
            sys.exit(f"  FAILED: {state['errors']}")
        if state.get("state") == "COMPLETE":
            print("  COMPLETE")
            return 1
        time.sleep(2)
    print(f"  {state.get('state', 'still processing')}")
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--replace", action="store_true",
                        help="delete an existing screenshot first")
    parser.add_argument("--only", action="append", metavar="SUFFIX",
                        help="product id suffix to limit to (repeatable)")
    parser.add_argument("--bundle-id")
    args = parser.parse_args()

    api = ASC()
    prefix = product_prefix()
    total = 0
    for sub in subscriptions(api, api.app_id(args.bundle_id)):
        suffix = sub["attributes"].get("productId", "").removeprefix(prefix)
        if args.only and suffix not in args.only:
            continue
        path = SHOTS_DIR / f"{suffix}.png"
        if not path.exists():
            print(f"  !!      no {path.name} in {SHOTS_DIR} for {sub['attributes'].get('productId')}")
            continue
        total += push(api, sub, path, args)
    print(f"\n{'done' if args.apply else 'dry run'}: {total} change(s)"
          + ("" if args.apply else ". Re-run with --apply to write."))


if __name__ == "__main__":
    main()
