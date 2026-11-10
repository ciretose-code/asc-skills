#!/usr/bin/env python3
"""Create the app's subscriptions — groups, subscriptions, copy, prices and
availability — in App Store Connect.

    subscription_setup.py            # dry run: prints a plan
    subscription_setup.py --apply    # writes

Everything customer-facing is read from **the app's `.storekit` file** (its
`subscriptionGroups`), as `iap_setup.py` does for the one-time purchase, so the app's
own StoreKit test config and the store cannot drift. The App Review note is read from
`<paths.iapReview>/<suffix>.txt`.

Steps, in the order each depends on the last:

  1. the group                     POST /v1/subscriptionGroups
  2. its en-US localization        POST /v1/subscriptionGroupLocalizations
  3. the subscription              POST /v1/subscriptions
  4. its en-US localization        POST /v1/subscriptionLocalizations
  5. availability                  POST /v1/subscriptionAvailabilities
  6. a price in every territory    POST /v1/subscriptionPrices  (one per territory)

Re-running is safe: each step reads current state first and skips what already
matches. The **App Review screenshot** is not here; it is
`subscription_review_screenshots.py`, since it needs a rendered image.

Why so many steps for a price: a subscription is priced per territory, unlike the
one-time purchase, whose price schedule takes a base territory and equalises the rest
itself. The USA price point is matched on `customerPrice`, and Apple's *equalizations*
endpoint then supplies the equivalent point in every other territory, so one number in
the StoreKit file prices the whole world the way the web UI would.

Limits are checked before the network, as everywhere here: subscription display name
30, description 45, group display name 30.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asc_client import ASC, product_prefix, project_path, storekit  # noqa: E402  (shared auth)

REVIEW_DIR = project_path("iapReview")
PRODUCT_PREFIX = product_prefix()

# StoreKit spells the period as ISO 8601; the API has its own enum.
PERIODS = {"P1W": "ONE_WEEK", "P1M": "ONE_MONTH", "P2M": "TWO_MONTHS",
           "P3M": "THREE_MONTHS", "P6M": "SIX_MONTHS", "P1Y": "ONE_YEAR"}

NAME_LIMIT, DESCRIPTION_LIMIT = 30, 45


def locale_of(loc: dict) -> str:
    """StoreKit says `en_US`; the API says `en-US`."""
    return loc["locale"].replace("_", "-")


def check_limits(what: str, name: str, description: str | None = None) -> None:
    if len(name) > NAME_LIMIT:
        sys.exit(f"{what}: display name is {len(name)} characters, limit {NAME_LIMIT}: {name!r}")
    if description is not None and len(description) > DESCRIPTION_LIMIT:
        sys.exit(f"{what}: description is {len(description)} characters, "
                 f"limit {DESCRIPTION_LIMIT}: {description!r}")


def review_note(product_id: str) -> str | None:
    path = REVIEW_DIR / f"{product_id.removeprefix(PRODUCT_PREFIX)}.txt"
    return path.read_text().strip() if path.exists() else None


class Plan:
    """Prints what would change and, with `--apply`, does it."""

    def __init__(self, api: ASC, apply: bool) -> None:
        self.api, self.apply, self.changes = api, apply, 0

    def say(self, mark: str, text: str) -> None:
        print(f"    {mark:<7} {text}")

    def ok(self, text: str) -> None:
        self.say("ok", text)

    def would(self, text: str) -> bool:
        """Note a change; return whether to perform it."""
        self.changes += 1
        self.say("CREATE" if self.apply else "create", text)
        return self.apply


def find_group(api: ASC, app_id: str, name: str) -> dict | None:
    for group in api.paged(f"/v1/apps/{app_id}/subscriptionGroups"):
        if group["attributes"].get("referenceName") == name:
            return group
    return None


def ensure_group(plan: Plan, app_id: str, group: dict) -> str | None:
    api, name = plan.api, group["name"]
    existing = find_group(api, app_id, name)
    if existing:
        plan.ok(f"group {name!r}")
        group_id = existing["id"]
    elif plan.would(f"group {name!r}"):
        group_id = api.post("/v1/subscriptionGroups", {"data": {
            "type": "subscriptionGroups",
            "attributes": {"referenceName": name},
            "relationships": {"app": {"data": {"type": "apps", "id": app_id}}},
        }})["data"]["id"]
    else:
        return None

    have = {}
    for loc in api.paged(f"/v1/subscriptionGroups/{group_id}/subscriptionGroupLocalizations"):
        have[loc["attributes"]["locale"]] = loc
    for loc in group["localizations"]:
        locale, display = locale_of(loc), loc["displayName"]
        check_limits(f"group {name!r}", display)
        current = have.get(locale)
        if current and current["attributes"].get("name") == display:
            plan.ok(f"group localization {locale}: {display!r}")
        elif current:
            if plan.would(f"update group localization {locale}: {display!r}"):
                api.patch(f"/v1/subscriptionGroupLocalizations/{current['id']}", {"data": {
                    "type": "subscriptionGroupLocalizations", "id": current["id"],
                    "attributes": {"name": display}}})
        elif plan.would(f"group localization {locale}: {display!r}"):
            api.post("/v1/subscriptionGroupLocalizations", {"data": {
                "type": "subscriptionGroupLocalizations",
                "attributes": {"locale": locale, "name": display},
                "relationships": {"subscriptionGroup": {
                    "data": {"type": "subscriptionGroups", "id": group_id}}},
            }})
    return group_id


def ensure_subscription(plan: Plan, group_id: str | None, sub: dict) -> str | None:
    api, product_id = plan.api, sub["productID"]
    period = PERIODS.get(sub["recurringSubscriptionPeriod"])
    if not period:
        sys.exit(f"{product_id}: unsupported period {sub['recurringSubscriptionPeriod']!r}")
    note = review_note(product_id)

    existing = None
    if group_id:
        for row in api.paged(f"/v1/subscriptionGroups/{group_id}/subscriptions"):
            if row["attributes"].get("productId") == product_id:
                existing = row
    if existing:
        plan.ok(f"subscription {product_id}  [{existing['attributes'].get('state')}]")
        sub_id = existing["id"]
    elif plan.would(f"subscription {product_id}  ({period}, "
                    f"family sharable: {sub.get('familyShareable', False)})"):
        attributes = {
            "name": sub["referenceName"], "productId": product_id,
            "subscriptionPeriod": period, "groupLevel": sub.get("groupNumber", 1),
            "familySharable": bool(sub.get("familyShareable", False)),
        }
        if note:
            attributes["reviewNote"] = note
        sub_id = api.post("/v1/subscriptions", {"data": {
            "type": "subscriptions", "attributes": attributes,
            # `group`, not `subscriptionGroup` — the localization resource below uses the
            # longer name, and this one 409s with "unknown relationship" if it does too.
            "relationships": {"group": {
                "data": {"type": "subscriptionGroups", "id": group_id}}},
        }})["data"]["id"]
    else:
        return None

    if existing and note is not None and existing["attributes"].get("reviewNote") != note:
        if plan.would(f"update review note ({len(note)} chars)"):
            api.patch(f"/v1/subscriptions/{sub_id}", {"data": {
                "type": "subscriptions", "id": sub_id,
                "attributes": {"reviewNote": note}}})

    have = {loc["attributes"]["locale"]: loc
            for loc in api.paged(f"/v1/subscriptions/{sub_id}/subscriptionLocalizations")}
    for loc in sub["localizations"]:
        locale, display, description = locale_of(loc), loc["displayName"], loc["description"]
        check_limits(product_id, display, description)
        current = have.get(locale)
        if current and (current["attributes"].get("name"), current["attributes"].get("description")) \
                == (display, description):
            plan.ok(f"localization {locale}: {display!r} — {description!r}")
        elif current:
            if plan.would(f"update localization {locale}: {display!r} — {description!r}"):
                api.patch(f"/v1/subscriptionLocalizations/{current['id']}", {"data": {
                    "type": "subscriptionLocalizations", "id": current["id"],
                    "attributes": {"name": display, "description": description}}})
        elif plan.would(f"localization {locale}: {display!r} — {description!r}"):
            api.post("/v1/subscriptionLocalizations", {"data": {
                "type": "subscriptionLocalizations",
                "attributes": {"locale": locale, "name": display, "description": description},
                "relationships": {"subscription": {
                    "data": {"type": "subscriptions", "id": sub_id}}},
            }})
    return sub_id


def usa_price_point(api: ASC, sub_id: str, price: str) -> dict:
    """The USA price point whose customer price is `price`, or exit listing the
    neighbours — never the closest, which would quietly charge a different amount."""
    points = api.paged(f"/v1/subscriptions/{sub_id}/pricePoints",
                       **{"filter[territory]": "USA"})
    for point in points:
        if float(point["attributes"]["customerPrice"]) == float(price):
            return point
    near = sorted({float(p["attributes"]["customerPrice"]) for p in points},
                  key=lambda v: abs(v - float(price)))[:6]
    sys.exit(f"no USA price point at {price}; nearest: {', '.join(f'{v:.2f}' for v in sorted(near))}")


def territory_of(point: dict) -> str | None:
    data = point.get("relationships", {}).get("territory", {}).get("data")
    return data["id"] if data else None


def ensure_prices(plan: Plan, sub_id: str | None, sub: dict) -> None:
    api, price = plan.api, sub["displayPrice"]
    if not sub_id:
        plan.would(f"price {price} USD, equalised to every territory (after the subscription exists)")
        return

    base = usa_price_point(api, sub_id, price)
    # Equalizations are the same price expressed in each other territory's tier.
    points = [base] + api.paged(f"/v1/subscriptionPricePoints/{base['id']}/equalizations",
                                include="territory")
    wanted: dict[str, str] = {}
    for point in points:
        territory = territory_of(point) or ("USA" if point["id"] == base["id"] else None)
        if territory:
            wanted[territory] = point["id"]

    priced = set()
    for row in api.paged(f"/v1/subscriptions/{sub_id}/prices",
                         include="territory,subscriptionPricePoint"):
        data = row.get("relationships", {}).get("territory", {}).get("data")
        if data:
            priced.add(data["id"])

    missing = sorted(set(wanted) - priced)
    if not missing:
        plan.ok(f"price {price} USD in all {len(wanted)} territories")
        return
    if not plan.would(f"price {price} USD in {len(missing)} of {len(wanted)} territories "
                      f"({len(priced)} already set)"):
        return
    for n, territory in enumerate(missing, 1):
        api.post("/v1/subscriptionPrices", {"data": {
            "type": "subscriptionPrices",
            "attributes": {"preserveCurrentPrice": False},
            "relationships": {
                "subscription": {"data": {"type": "subscriptions", "id": sub_id}},
                "subscriptionPricePoint": {
                    "data": {"type": "subscriptionPricePoints", "id": wanted[territory]}},
                "territory": {"data": {"type": "territories", "id": territory}},
            },
        }})
        if n % 25 == 0:
            print(f"      … {n}/{len(missing)}")


def ensure_availability(plan: Plan, sub_id: str | None) -> None:
    api = plan.api
    territories = [t["id"] for t in api.paged("/v1/territories")]
    if sub_id:
        current = api.get_soft(f"/v1/subscriptions/{sub_id}/subscriptionAvailability")
        if current and current.get("data"):
            plan.ok("availability set")
            return
    if plan.would(f"available in all {len(territories)} territories, and new ones as they open") \
            and sub_id:
        api.post("/v1/subscriptionAvailabilities", {"data": {
            "type": "subscriptionAvailabilities",
            "attributes": {"availableInNewTerritories": True},
            "relationships": {
                "subscription": {"data": {"type": "subscriptions", "id": sub_id}},
                "availableTerritories": {
                    "data": [{"type": "territories", "id": t} for t in territories]},
            },
        }})


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="actually write; without it this only prints the plan")
    parser.add_argument("--bundle-id")
    args = parser.parse_args()

    groups = storekit().get("subscriptionGroups", [])
    if not groups:
        sys.exit("the .storekit file has no subscriptionGroups")

    api = ASC()
    app_id = api.app_id(args.bundle_id)
    print(f"app {args.bundle_id} -> {app_id}\n")
    plan = Plan(api, args.apply)

    for group in groups:
        print(f"  {group['name']}")
        group_id = ensure_group(plan, app_id, group)
        for sub in group["subscriptions"]:
            print(f"\n  {sub['productID']}")
            sub_id = ensure_subscription(plan, group_id, sub)
            # Availability before prices: a price POST against a subscription with no
            # availability 409s with "an error occurred while processing the pricing
            # information", pointing at the price point, which sends you looking at the
            # wrong thing. The web UI hides the order by asking in the same screen.
            ensure_availability(plan, sub_id)
            ensure_prices(plan, sub_id, sub)

    if plan.changes and not args.apply:
        print(f"\ndry run: {plan.changes} change(s) to make. Re-run with --apply to write.")
    elif plan.changes:
        print(f"\ndone: {plan.changes} change(s) made")
    else:
        print("\nnothing to do")


if __name__ == "__main__":
    main()
