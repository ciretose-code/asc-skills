#!/usr/bin/env python3
"""Create the app's in-app purchases in App Store Connect, and set their copy and price.

Everything is read from **the app's `.storekit` file** (asc.json `storekit`) — the same file the app's StoreKit
testing loads — rather than retyped here. That is the point: the product id, the
display name, the description, the family-sharing flag and the price all have to
match what the app renders, or App Review rejects the submission, and one source
of truth is the only way to keep them matching.

    iap_setup.py                         # dry run: prints a plan, writes nothing
    iap_setup.py --apply                 # writes
    iap_setup.py --apply --replace-price # move an existing price
    iap_setup.py --skip-price            # product + copy only (e.g. just fix localizations)

The App Review note for each product is `<paths.iapReview>/<suffix>.txt`, the
suffix being the product id minus the prefix (`<bundleId>.`), beside its
screenshot `<suffix>.png`.

Dry run is the default. The script reads current state first and reports, per
product, whether it would create, update or skip — so re-running is safe and a
second run after a successful one should print nothing but `ok`.

Three things happen, in order, because each depends on the last:

  1. the product itself       POST /v2/inAppPurchases
  2. its en-US localization   POST/PATCH /v1/inAppPurchaseLocalizations
  3. its price schedule       POST /v1/inAppPurchasePriceSchedules

A product with no localization cannot be submitted, and one with no price
schedule cannot be sold, so all three are needed before the first review.

**The price step is the one to watch.** An existing schedule is left alone
unless `--replace-price`, because overwriting a live price is not something a
convenience script should do quietly.
"""
from __future__ import annotations

import argparse
import sys

from asc_client import (ASC, product_prefix, project_path, require_bundle_id,
                        storekit, storekit_path)

# App Store Connect's documented limits. Checking locally names the offending
# product instead of returning a 409 that doesn't say which one.
NAME_LIMIT, DESC_LIMIT = 30, 45
REFERENCE_NAME_LIMIT = 64
REVIEW_NOTE_LIMIT = 4000

# StoreKit's spelling on the left, the API's on the right.
TYPES = {
    "NonConsumable": "NON_CONSUMABLE",
    "Consumable": "CONSUMABLE",
    "NonRenewingSubscription": "NON_RENEWING_SUBSCRIPTION",
}


def wanted_products(locale: str) -> list[dict]:
    """Everything the store needs, pulled out of the StoreKit config."""
    config = storekit()
    out = []
    for product in config.get("products", []):
        product_id = product.get("productID")
        kind = TYPES.get(product.get("type", ""))
        if not product_id or not kind:
            sys.exit(f"{storekit_path()}: unsupported or missing type for "
                     f"{product_id or '<no productID>'}: {product.get('type')!r}")
        loc = next((l for l in product.get("localizations", [])
                    if l.get("locale", "").replace("_", "-") == locale), None)
        if loc is None:
            sys.exit(f"{product_id}: no {locale} localization in {storekit_path().name}")
        name = loc.get("displayName", "")
        desc = loc.get("description", "")
        reference = product.get("referenceName") or name
        for label, value, limit in (("display name", name, NAME_LIMIT),
                                    ("description", desc, DESC_LIMIT),
                                    ("reference name", reference,
                                     REFERENCE_NAME_LIMIT)):
            if not value:
                sys.exit(f"{product_id}: empty {label} in {storekit_path().name}")
            if len(value) > limit:
                sys.exit(f"{product_id}: {label} is {len(value)} characters, "
                         f"limit is {limit}")
        # The review note lives beside the review screenshot, named the same way,
        # so both are version-controlled prose rather than something retyped into
        # a web form. A reviewer who cannot find the purchase rejects it.
        note_path = project_path("iapReview") / f"{product_id.removeprefix(product_prefix())}.txt"
        note = note_path.read_text().strip() if note_path.exists() else ""
        if len(note) > REVIEW_NOTE_LIMIT:
            sys.exit(f"{product_id}: review note is {len(note)} characters, "
                     f"limit is {REVIEW_NOTE_LIMIT} ({note_path})")

        out.append({
            "reviewNote": note,
            "productID": product_id,
            "type": kind,
            "name": name,
            "description": desc,
            "referenceName": reference,
            "familySharable": bool(product.get("familyShareable", False)),
            "price": str(product.get("displayPrice", "")).strip(),
        })
    if not out:
        sys.exit(f"no products found in {storekit_path()}")
    return out


def current_price(api, iap_id: str) -> str | None:
    """The customer price currently scheduled, or None if there is no schedule.

    Reading this back is fiddlier than it looks, and getting it wrong is not a
    cosmetic bug: a price that fails to read reports as `CREATE`, and a second
    `--apply` would then POST a *second* price schedule.

    Two dead ends, both confirmed against the live API. The price objects
    included from `iapPriceSchedule?include=manualPrices` come back with an
    empty `relationships` object, so there is nothing to follow to a price
    point — their `customerPrice` simply isn't reachable that way. And the
    schedule rejects a nested `include=manualPrices.inAppPurchasePricePoint`
    outright. The price point is only reachable by walking the schedule's
    `manualPrices` relationship as its own request, where `include` works.
    """
    schedule = api.get_soft(f"/v2/inAppPurchases/{iap_id}/iapPriceSchedule")
    if not schedule or not schedule.get("data"):
        return None
    prices = api.get_soft(
        f"/v1/inAppPurchasePriceSchedules/{schedule['data']['id']}/manualPrices",
        **{"include": "inAppPurchasePricePoint"})
    for inc in (prices or {}).get("included", []):
        if inc.get("type") == "inAppPurchasePricePoints":
            price = (inc.get("attributes") or {}).get("customerPrice")
            if price:
                return str(price)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="actually write; without it this only prints the plan")
    parser.add_argument("--locale", default="en-US")
    parser.add_argument("--territory", default="USA",
                        help="base territory for the price schedule")
    parser.add_argument("--bundle-id")
    parser.add_argument("--replace-price", action="store_true",
                        help="move the price even if a schedule already exists")
    parser.add_argument("--skip-price", action="store_true",
                        help="create the product and copy, leave pricing for the UI")
    args = parser.parse_args()

    wanted = wanted_products(args.locale)
    api = ASC()
    app_id = api.app_id(args.bundle_id)
    print(f"app {require_bundle_id(args.bundle_id)} -> {app_id}")

    existing = api.paged(f"/v1/apps/{app_id}/inAppPurchasesV2")
    by_product_id = {p["attributes"]["productId"]: p for p in existing}
    print(f"{len(existing)} in-app purchase(s) already in App Store Connect\n")

    plan = []
    for product in wanted:
        found = by_product_id.get(product["productID"])
        entry = {"product": product, "iap": found, "steps": []}
        if found is None:
            entry["steps"].append(("CREATE", "product",
                                   f"{product['referenceName']} "
                                   f"({product['type']}, family "
                                   f"{'on' if product['familySharable'] else 'off'})"))
        else:
            # Family sharing is a customer-facing promise, and it is one-way:
            # it can be turned on later but NEVER off again. So off -> on is a
            # plannable update, while on -> off is reported and never sent —
            # the fix for that drift is the .storekit file, not the store.
            actual = found["attributes"].get("familySharable")
            if actual is not None and bool(actual) != product["familySharable"]:
                if actual and not product["familySharable"]:
                    print(f"  !!      {product['productID']}: Family Sharing is ON in App Store "
                          "Connect but off in the .storekit file. It cannot be turned off; "
                          "set familyShareable true in the .storekit file to match.")
                else:
                    entry["steps"].append(
                        ("UPDATE", "familySharable",
                         f"{actual} -> {product['familySharable']}"))
            actualName = (found["attributes"].get("name") or "").strip()
            if actualName and actualName != product["referenceName"]:
                entry["steps"].append(
                    ("UPDATE", "referenceName",
                     f"{actualName!r} -> {product['referenceName']!r}"))
            if product["reviewNote"]:
                live_note = (found["attributes"].get("reviewNote") or "").strip()
                if live_note != product["reviewNote"]:
                    verb = "UPDATE" if live_note else "CREATE"
                    first = product["reviewNote"].splitlines()[0]
                    entry["steps"].append(
                        ("SET" if verb == "CREATE" else "UPDATE", "reviewNote",
                         f"{len(product['reviewNote'])} chars — {first[:52]}…"))
        plan.append(entry)

    # Localization and price can only be resolved for products that already
    # exist; for the rest they are implied by the create and reported as such.
    for entry in plan:
        product, found = entry["product"], entry["iap"]
        if found is None:
            entry["steps"].append(("CREATE", "localization",
                                   f"{product['name']} — {product['description']}"))
            if not args.skip_price and product["price"]:
                entry["steps"].append(("CREATE", "price",
                                       f"{product['price']} ({args.territory})"))
            continue

        iap_id = found["id"]
        locs = api.paged(f"/v2/inAppPurchases/{iap_id}/inAppPurchaseLocalizations")
        current = next((l for l in locs
                        if l["attributes"].get("locale") == args.locale), None)
        if current is None:
            entry["steps"].append(("CREATE", "localization",
                                   f"{product['name']} — {product['description']}"))
        elif (current["attributes"].get("name") != product["name"]
              or current["attributes"].get("description") != product["description"]):
            entry["loc_id"] = current["id"]
            entry["steps"].append(("UPDATE", "localization",
                                   f"{product['name']} — {product['description']}"))
        else:
            entry["steps"].append(("ok", "localization", "already matches"))

        if args.skip_price or not product["price"]:
            continue
        live = current_price(api, iap_id)
        if live is None:
            entry["steps"].append(("CREATE", "price",
                                   f"{product['price']} ({args.territory})"))
        elif str(live) != product["price"]:
            verb = "UPDATE" if args.replace_price else "!!"
            detail = f"{live} -> {product['price']}" if args.replace_price else (
                f"App Store Connect says {live}, {storekit_path().name} says "
                f"{product['price']} — pass --replace-price to move it")
            entry["steps"].append((verb, "price", detail))
        else:
            entry["steps"].append(("ok", "price", f"already {live}"))

    for entry in plan:
        print(f"  {entry['product']['productID']}")
        for verb, what, detail in entry["steps"]:
            print(f"    {verb:<7} {what:<13} {detail}")

    writes = [(e, s) for e in plan for s in e["steps"]
              if s[0] in ("CREATE", "UPDATE", "SET")]
    blocked = [s for e in plan for s in e["steps"] if s[0] == "!!"]
    if not args.apply:
        print(f"\ndry run: {len(writes)} change(s) to make"
              + (f", {len(blocked)} blocked" if blocked else "")
              + ". Re-run with --apply to write.")
        return
    if blocked:
        sys.exit("\nrefusing to apply while a price disagrees; "
                 "re-run with --replace-price if that is intended")
    if not writes:
        print("\nnothing to do")
        return

    for entry in plan:
        product = entry["product"]
        iap = entry["iap"]
        steps = {what: (verb, detail) for verb, what, detail in entry["steps"]}

        if "product" in steps and steps["product"][0] == "CREATE":
            created = api.post("/v2/inAppPurchases", {
                "data": {
                    "type": "inAppPurchases",
                    "attributes": {
                        "name": product["referenceName"],
                        "productId": product["productID"],
                        "inAppPurchaseType": product["type"],
                        "familySharable": product["familySharable"],
                        **({"reviewNote": product["reviewNote"]}
                           if product["reviewNote"] else {}),
                    },
                    "relationships": {
                        "app": {"data": {"type": "apps", "id": app_id}}
                    },
                }
            })
            iap = created["data"]
            print(f"  created product {product['productID']} -> {iap['id']}")
        else:
            attrs = {}
            if "familySharable" in steps:
                attrs["familySharable"] = product["familySharable"]
            if "reviewNote" in steps:
                attrs["reviewNote"] = product["reviewNote"]
            if "referenceName" in steps:
                attrs["name"] = product["referenceName"]
            if attrs:
                api.patch(f"/v2/inAppPurchases/{iap['id']}", {
                    "data": {"type": "inAppPurchases", "id": iap["id"],
                             "attributes": attrs}
                })
                print(f"  updated {', '.join(attrs)} on {product['productID']}")

        iap_id = iap["id"]

        verb, _ = steps.get("localization", ("ok", ""))
        if verb == "CREATE":
            api.post("/v1/inAppPurchaseLocalizations", {
                "data": {
                    "type": "inAppPurchaseLocalizations",
                    "attributes": {"locale": args.locale, "name": product["name"],
                                   "description": product["description"]},
                    # The relationship member is `inAppPurchaseV2`, not
                    # `inAppPurchase`. Apple's rendered docs make this hard to
                    # read; getting it wrong returns an unhelpful 409.
                    "relationships": {
                        "inAppPurchaseV2": {
                            "data": {"type": "inAppPurchases", "id": iap_id}}
                    },
                }
            })
            print(f"  created localization for {product['productID']}")
        elif verb == "UPDATE":
            api.patch(f"/v1/inAppPurchaseLocalizations/{entry['loc_id']}", {
                "data": {"type": "inAppPurchaseLocalizations", "id": entry["loc_id"],
                         "attributes": {"name": product["name"],
                                        "description": product["description"]}}
            })
            print(f"  updated localization for {product['productID']}")

        verb, _ = steps.get("price", ("ok", ""))
        if verb in ("CREATE", "UPDATE"):
            points = entry.get("points")
            if points is None:
                points = {p["id"]: p["attributes"].get("customerPrice")
                          for p in api.paged(
                              f"/v2/inAppPurchases/{iap_id}/pricePoints",
                              **{"filter[territory]": args.territory})}
            match = next((pid for pid, price in points.items()
                          if str(price) == product["price"]), None)
            if match is None:
                offered = sorted({str(p) for p in points.values() if p})
                sys.exit(f"\n{product['productID']}: no {args.territory} price point "
                         f"at {product['price']}.\n  Apple's tiers nearby: "
                         + ", ".join(offered[:12]))
            api.post("/v1/inAppPurchasePriceSchedules", {
                "data": {
                    "type": "inAppPurchasePriceSchedules",
                    "relationships": {
                        "inAppPurchase": {
                            "data": {"type": "inAppPurchases", "id": iap_id}},
                        "baseTerritory": {
                            "data": {"type": "territories", "id": args.territory}},
                        "manualPrices": {
                            "data": [{"type": "inAppPurchasePrices",
                                      "id": "${price}"}]},
                    },
                },
                # A price with no start date takes effect immediately and runs
                # until replaced, which is what a one-time unlock wants.
                "included": [{
                    "type": "inAppPurchasePrices",
                    "id": "${price}",
                    "attributes": {"startDate": None, "endDate": None},
                    "relationships": {
                        "inAppPurchasePricePoint": {
                            "data": {"type": "inAppPurchasePricePoints",
                                     "id": match}}
                    },
                }],
            })
            print(f"  set price {product['price']} on {product['productID']}")

    print("\ndone")


if __name__ == "__main__":
    main()
