---
name: in-app-purchases
description: Use when adding, pricing, localizing or fixing in-app purchases or auto-renewable subscriptions in App Store Connect — products stuck in "Missing Metadata", display names/prices drifting from the app, review notes, or reconciling App Store Connect with the app's .storekit file.
---

# In-app purchases and subscriptions

## Overview

The app's **`.storekit` file is the source of truth** — the same file StoreKit
testing loads. Product ids, display names, descriptions, family sharing and price
are read from it, never retyped, so the store matches what the app renders.
`$T` = `<this skill's base directory>/../../toolkit`. Requires asc:setup.

## Per product, App Store Connect needs

1. the product (type, reference name, family sharing)
2. a localization — display name **≤30**, description **≤45**
3. a price (schedule for IAPs; per-territory prices + availability for subs)
4. an App Review screenshot of the purchase UI
5. a review note — `<paths.iapReview>/<suffix>.txt`, saying exactly where the
   purchase appears ("tap a locked pack on the Places screen")

Missing any → **Missing Metadata**. `suffix` = product id minus `<bundleId>.`.

## Workflow

```sh
python3 $T/iap_setup.py --help          # flags for every IAP/subscription script
python3 $T/iap_setup.py                 # dry run: CREATE / UPDATE / ok / !! per product
python3 $T/iap_setup.py --apply
python3 $T/iap_setup.py --skip-price    # copy + notes only
python3 $T/subscription_setup.py        # groups, subs, copy, availability, all-territory prices
python3 $T/iap_review_screenshots.py    # <suffix>.png per product (see asc:screenshots)
python3 $T/subscription_review_screenshots.py
```

Always show the dry run to the user before `--apply`. Re-run after: a clean
state prints only `ok`. Then submit new products **with** the next app version
(asc:release).

## Rules the scripts enforce — don't work around them

- **Family Sharing is one-way.** It can be turned on, never off. On→off drift is
  reported as `!!` and never sent; fix the `.storekit` file instead. Create new
  subscriptions with it off unless the user decides otherwise.
- **An existing price is never moved** without `--replace-price`. Moving a live
  price is the user's decision — ask first.
- Prices must hit an Apple price point exactly; the script lists nearby tiers
  instead of guessing.
- Subscription availability must exist before any price (else a misleading 409).

## Common mistakes

| Symptom | Cause |
|---|---|
| 409 on localization create | Relationship must be `inAppPurchaseV2` |
| 409 "unknown relationship" on subscription | It's `group`, not `subscriptionGroup` |
| Price readback says CREATE when one exists | Read via `iapPriceSchedule` → `manualPrices?include=inAppPurchasePricePoint`; never post a second schedule |
| Review rejects: display name differs from the app | Edit the `.storekit` file, then push — never the web form |
| Overlong description | Rewrite to ≤45 chars in the `.storekit` file |
