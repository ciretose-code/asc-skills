# App Store Connect API — endpoints and traps

Each trap below was found by running against the live API; the docs don't
mention them. Read this before writing a new script.

## Selecting what to edit

- `GET /v1/apps?filter[bundleId]=…` — re-check the exact bundle id; filters can be
  prefix-ish.
- Versions: `GET /v1/apps/{id}/appStoreVersions?filter[platform]=IOS`. A live app
  has several; pick by `appStoreState` in
  `PREPARE_FOR_SUBMISSION | DEVELOPER_REJECTED | REJECTED | METADATA_REJECTED | INVALID_BINARY`.
  Never `[0]`.
- App info likewise: `GET /v1/apps/{id}/appInfos`, pick the editable one.

## Listing copy

- `appInfoLocalizations` — name, subtitle, privacyPolicyUrl (app-level).
- `appStoreVersionLocalizations` — description, keywords, promotionalText,
  whatsNew, supportUrl, marketingUrl (version-level).
- Overlong fields come back as an opaque 409 — check limits locally.
- `whatsNew` is not accepted on an app's first version.

## Asset uploads (screenshots, review screenshots, achievement icons)

Three steps: **reserve** (POST fileName + fileSize → `uploadOperations`),
**upload** (perform each operation verbatim), **commit** (PATCH `uploaded: true`
+ `sourceFileChecksum` = MD5).

- Upload URLs are pre-signed object storage: send **only** the headers Apple
  returned. Adding the JWT `Authorization` header → bare `400 Invalid request`.
- An **alpha channel** is rejected with a message about the *size*.
- A reservation never committed leaves `AWAITING_UPLOAD`, which then reads as
  "already has one" — delete and redo (`--replace`).
- Mac images with a wrong aspect ratio fail *after* upload, as
  `assetDeliveryState` `IMAGE_BAD_ASPECT_RATIO`. Poll the state.
- Screenshot sets: `GET /v1/appStoreVersionLocalizations/{id}/appScreenshotSets`;
  create with `POST /v1/appScreenshotSets` (`screenshotDisplayType`) before
  reserving into it.

## In-app purchases

- `POST /v2/inAppPurchases` — `name` is the *reference* name.
- `POST /v1/inAppPurchaseLocalizations` — relationship is **`inAppPurchaseV2`**.
- Price points: `GET /v2/inAppPurchases/{id}/pricePoints?filter[territory]=USA`.
- Reading the current price: `GET /v2/inAppPurchases/{id}/iapPriceSchedule` →
  `GET /v1/inAppPurchasePriceSchedules/{id}/manualPrices?include=inAppPurchasePricePoint`.
  `iapPriceSchedule?include=manualPrices` returns empty relationships and a nested
  include is rejected — a naive readback finds nothing and posts a *second* schedule.
- `POST /v1/inAppPurchasePriceSchedules` uses JSON:API `included` with a
  `${price}` placeholder id.
- Review screenshot: `POST /v1/inAppPurchaseAppStoreReviewScreenshots`.
- `familySharable` can be turned on, never off.

## Subscriptions

- `POST /v1/subscriptions` relationship is **`group`** (the group *localization*
  uses `subscriptionGroup`).
- `subscriptionAvailabilities` must exist before any `subscriptionPrices`, else a
  409 blaming the price point.
- Price the USA point by `customerPrice`, then take every other territory from the
  point's `equalizations`.

## Capabilities

- `GET /v1/bundleIds?filter[identifier]=…` → `GET /v1/bundleIds/{id}/bundleIdCapabilities`
  **without** `limit` (it 400s). An absent row is a prompt to look, not proof.

## Releases (`version.py` — not yet exercised live)

- `POST /v1/appStoreVersions` (platform, versionString, relationship `app`).
- `PATCH /v1/appStoreVersions/{id}/relationships/build`.
- `GET /v1/builds?filter[app]=…&filter[preReleaseVersion.version]=…&filter[processingState]=VALID`.
- `PATCH /v1/builds/{id}` `usesNonExemptEncryption`.
- `appStoreReviewDetails` POST/PATCH.
- Submit: `POST /v1/reviewSubmissions` → `POST /v1/reviewSubmissionItems` →
  `PATCH /v1/reviewSubmissions/{id}` `submitted: true`.
