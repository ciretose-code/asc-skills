#!/usr/bin/env python3
"""Upload the in-app purchase's App Review screenshot via the App Store Connect API.

App Store Connect holds an IAP in Missing Metadata until it has a screenshot
showing the purchase inside the app. Unlike the localization this is not a
single POST — it is Apple's three-step asset flow:

  1. **reserve** — POST the file name and size; Apple replies with
     `uploadOperations` describing where and how to PUT the bytes, possibly in
     several chunks
  2. **upload** — perform those operations verbatim
  3. **commit** — PATCH `uploaded: true` with the file's MD5, which is how Apple
     confirms it received exactly what was reserved

    iap_review_screenshots.py                     # dry run
    iap_review_screenshots.py --apply             # upload
    iap_review_screenshots.py --apply --replace   # overwrite
    iap_review_screenshots.py --only pro          # one product suffix

Files come from `<paths.iapReview>/`, whose names encode their product:
`pro.png` -> `<bundleId>.pro`, `packs.forest.png` -> `<bundleId>.packs.forest`. Render
them from the real paywall view (an ImageRenderer snapshot test) or capture them
from the simulator — either way, flatten the alpha channel.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asc_client import ASC, API, product_prefix, project_path  # noqa: E402  (shared auth)

SHOTS_DIR = project_path("iapReview")
PRODUCT_PREFIX = product_prefix()


def product_id_for(path: Path) -> str:
    """`pro.png` -> `<prefix>pro`."""
    return PRODUCT_PREFIX + path.name[: -len(path.suffix)]


def check_image(path: Path) -> str | None:
    """Reject locally what App Store Connect would reject remotely, naming the file.

    Only the alpha channel is treated as fatal, and it is the classic failure:
    App Store Connect refuses an RGBA file while complaining about its *size*,
    which sends you chasing the wrong thing. `ImageRenderer` writes RGBA, so
    this is a live risk here and not a theoretical one.

    **Dimensions are reported, not enforced.** Apple documents accepted review
    screenshot sizes for iOS and says nothing usable for macOS, so hardcoding a
    list would
    reject valid files on a guess. The API is the authority; let it answer.
    """
    try:
        from PIL import Image
    except ImportError:
        return None  # Pillow is optional; the API will still catch problems
    with Image.open(path) as im:
        if im.mode in ("RGBA", "LA") or "transparency" in im.info:
            return f"has an alpha channel ({im.mode}) — flatten to RGB"
    return None


def dimensions(path: Path) -> str:
    try:
        from PIL import Image
    except ImportError:
        return "?"
    with Image.open(path) as im:
        return f"{im.size[0]}x{im.size[1]} {im.mode}"


def md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reserve(api: ASC, iap_id: str, path: Path) -> dict:
    """Step 1. The relationship member is `inAppPurchaseV2`, matching the
    localization endpoint; the older `inAppPurchase` is tried as a fallback."""
    body = {
        "data": {
            "type": "inAppPurchaseAppStoreReviewScreenshots",
            "attributes": {"fileName": path.name, "fileSize": path.stat().st_size},
            "relationships": {
                "inAppPurchaseV2": {"data": {"type": "inAppPurchases", "id": iap_id}}
            },
        }
    }
    url = f"{API}/v1/inAppPurchaseAppStoreReviewScreenshots"
    response = api.session.post(url, json=body)
    if response.status_code >= 400 and "inAppPurchase" in response.text:
        body["data"]["relationships"] = {
            "inAppPurchase": {"data": {"type": "inAppPurchases", "id": iap_id}}
        }
        response = api.session.post(url, json=body)
    return api._check(response, f"reserve {path.name}")["data"]


def upload(operations: list[dict], path: Path) -> None:
    """Step 2. Apple may split the file; honour each operation's offset/length.

    Deliberately *not* the authenticated session. These URLs are pre-signed
    Apple object storage, and sending our `Authorization: Bearer <JWT>` alongside
    the signature gets a bare `400 Invalid request` — which reads like a bad file
    rather than a bad header. Send only the headers Apple handed back.
    """
    blob = path.read_bytes()
    if not operations:
        sys.exit(f"no uploadOperations returned for {path.name}")
    for op in operations:
        headers = {h["name"]: h["value"] for h in (op.get("requestHeaders") or [])}
        offset, length = op.get("offset", 0), op.get("length", len(blob))
        response = requests.request(op.get("method", "PUT"), op["url"],
                                    headers=headers, data=blob[offset:offset + length])
        if response.status_code >= 400:
            sys.exit(f"upload of {path.name} failed [{response.status_code}] "
                     f"{response.text[:200]}")


def commit(api: ASC, asset_id: str, path: Path) -> dict:
    """Step 3. The checksum is how Apple confirms the bytes arrived intact."""
    return api.patch(f"/v1/inAppPurchaseAppStoreReviewScreenshots/{asset_id}", {
        "data": {
            "type": "inAppPurchaseAppStoreReviewScreenshots",
            "id": asset_id,
            "attributes": {"uploaded": True, "sourceFileChecksum": md5(path)},
        }
    })["data"]


def delivery_state(api: ASC, asset_id: str, tries: int = 12) -> str:
    """Apple processes asynchronously; COMPLETE means it actually took the file.

    A reservation that is created but never reaches COMPLETE leaves the product
    holding an AWAITING_UPLOAD screenshot, which this script then reports as
    "already has one" — clear it with --replace.
    """
    for attempt in range(tries):
        data = api.get(f"/v1/inAppPurchaseAppStoreReviewScreenshots/{asset_id}")["data"]
        state = (data["attributes"].get("assetDeliveryState") or {})
        name, errors = state.get("state"), state.get("errors")
        if errors:
            return f"FAILED: {errors}"
        if name and name not in ("UPLOAD_COMPLETE", "PROCESSING"):
            return name
        if name == "UPLOAD_COMPLETE" and attempt >= 2:
            return name
        time.sleep(2)
    return "still processing"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="actually upload")
    parser.add_argument("--replace", action="store_true",
                        help="delete an existing screenshot and upload again")
    parser.add_argument("--only", help="limit to product ids containing this substring")
    parser.add_argument("--bundle-id")
    args = parser.parse_args()

    files = sorted(SHOTS_DIR.glob("*.png"))
    if not files:
        sys.exit(f"no screenshots in {SHOTS_DIR}")

    problems = [(f, why) for f in files if (why := check_image(f))]
    for path, why in problems:
        print(f"  INVALID {path.name} {why}")
    if problems:
        sys.exit(f"\n{len(problems)} file(s) would be rejected — fix before uploading")

    api = ASC()
    app_id = api.app_id(args.bundle_id)
    products = {p["attributes"]["productId"]: p["id"]
                for p in api.paged(f"/v1/apps/{app_id}/inAppPurchasesV2")}

    plan = []
    for path in files:
        product_id = product_id_for(path)
        if args.only and args.only not in product_id:
            continue
        iap_id = products.get(product_id)
        if not iap_id:
            print(f"  !!      {path.name} -> {product_id} not found in App Store Connect")
            continue
        found = api.get_soft(f"/v2/inAppPurchases/{iap_id}/appStoreReviewScreenshot")
        existing = (found or {}).get("data")
        if existing and not args.replace:
            print(f"  ok      {product_id} already has a screenshot "
                  f"(use --replace to overwrite)")
            continue
        plan.append((path, product_id, iap_id, existing))
        verb = "REPLACE" if existing else "UPLOAD "
        print(f"  {verb} {product_id}  <- {path.name} "
              f"({dimensions(path)}, {path.stat().st_size / 1e6:.2f} MB)")

    if not args.apply:
        print(f"\ndry run: {len(plan)} to upload. Re-run with --apply to write.")
        return
    if not plan:
        print("\nnothing to do")
        return

    for path, product_id, iap_id, existing in plan:
        if existing:
            api.delete(f"/v1/inAppPurchaseAppStoreReviewScreenshots/{existing['id']}")
        asset = reserve(api, iap_id, path)
        upload(asset["attributes"].get("uploadOperations") or [], path)
        commit(api, asset["id"], path)
        print(f"  uploaded {product_id}  {delivery_state(api, asset['id'])}")

    print(f"\ndone: {len(plan)} uploaded")


if __name__ == "__main__":
    main()
