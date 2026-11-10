#!/usr/bin/env python3
"""
game_center_achievements.py — idempotent sync of achievements.json -> Game Center
achievements in App Store Connect, including localizations and 512x512 icons.

Dry run by default, like the rest of the toolkit; pass --apply to write.

  game_center_achievements.py                       # dry run
  game_center_achievements.py --apply               # write metadata, localizations, icons
  game_center_achievements.py --apply --skip-images
  game_center_achievements.py --apply --only-failed-images

Paths come from asc.json: `paths.achievements` (default
marketing/game-center/achievements.json) and `paths.achievementIcons`
(default marketing/game-center/icons, `<id>.png`). Failed icon uploads are
logged beside achievements.json in image_upload_failures.json (gitignore it).

Each entry: {"id", "referenceName", "title", "points", "showBeforeEarned",
"repeatable", "preEarnedDescription", "earnedDescription",
optional "localizations": {"ja": {"title", "preEarnedDescription", "earnedDescription"}}}.
Credentials and bundle id are the toolkit's usual ones (asc_client.py).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

try:
    import jwt
    import requests
    from dotenv import load_dotenv
except ImportError:
    sys.exit("Install dependencies first:  pip install -r requirements.txt")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asc_client  # noqa: E402  (loads credentials from the usual .env files)

BUNDLE_ID_DEFAULT = asc_client.BUNDLE_ID
BASE_URL = "https://api.appstoreconnect.apple.com/v1"
BASE_URL_V2 = "https://api.appstoreconnect.apple.com/v2"
DEFAULT_LOCALE = asc_client.PRIMARY_LOCALE
ACHIEVEMENTS_JSON = asc_client.project_path("achievements")
DEFAULT_ICONS_DIR = asc_client.project_path("achievementIcons")
DEFAULT_FAILURE_LOG = ACHIEVEMENTS_JSON.parent / "image_upload_failures.json"
UPLOAD_TIMEOUT = 120
FILE_FIELDS = "referenceName,vendorIdentifier,points,showBeforeEarned,repeatable"


# ── JWT ───────────────────────────────────────────────────────────────────────

def make_token(key_id: str, issuer_id: str, key_path: str) -> str:
    private_key = Path(key_path).expanduser().read_text()
    now = int(time.time())
    payload = {
        "iss": issuer_id,
        "iat": now,
        "exp": now + 1200,
        "aud": "appstoreconnect-v1",
    }
    return jwt.encode(
        payload, private_key, algorithm="ES256", headers={"kid": key_id}
    )


# ── API client ────────────────────────────────────────────────────────────────

TOKEN_LIFETIME = 1200        # seconds ASC tokens are valid
TOKEN_REFRESH_AFTER = 900   # refresh after 15 minutes to keep a buffer


class ASCClient:
    def __init__(self, token: str, dry_run: bool = False,
                 key_id: str = "", issuer_id: str = "", key_path: str = "") -> None:
        self.dry_run = dry_run
        self._key_id = key_id
        self._issuer_id = issuer_id
        self._key_path = key_path
        self._token_age = int(time.time())
        self._s = requests.Session()
        self._s.headers["Authorization"] = f"Bearer {token}"
        self._s.headers["Content-Type"] = "application/json"

    def _refresh_if_needed(self) -> None:
        if self._key_id and int(time.time()) - self._token_age >= TOKEN_REFRESH_AFTER:
            token = make_token(self._key_id, self._issuer_id, self._key_path)
            self._s.headers["Authorization"] = f"Bearer {token}"
            self._token_age = int(time.time())
            print("  [token refreshed]")

    def get(self, path: str, params: Optional[dict] = None) -> dict:
        self._refresh_if_needed()
        url = _to_url(path)
        response = self._s.get(url, params=params, timeout=UPLOAD_TIMEOUT)
        _raise(response)
        return response.json()

    def get_optional(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        self._refresh_if_needed()
        url = _to_url(path)
        response = self._s.get(url, params=params, timeout=UPLOAD_TIMEOUT)
        if response.status_code == 404:
            return None
        _raise(response)
        return response.json()

    def get_all(self, path: str, params: Optional[dict] = None) -> list:
        self._refresh_if_needed()
        params = {**(params or {}), "limit": 200}
        results = []
        url: Optional[str] = _to_url(path)
        while url:
            response = self._s.get(url, params=params, timeout=UPLOAD_TIMEOUT)
            _raise(response)
            body = response.json()
            results.extend(body.get("data", []))
            url = body.get("links", {}).get("next")
            params = {}
        return results

    def post(self, path: str, body: dict) -> dict:
        self._refresh_if_needed()
        if self.dry_run:
            print(f"    [dry-run] POST {path}")
            return {"data": {"id": "DRY_RUN", "attributes": {}}}
        response = self._s.post(_to_url(path), json=body, timeout=UPLOAD_TIMEOUT)
        _raise(response)
        return response.json()

    def patch(self, path: str, body: dict) -> dict:
        self._refresh_if_needed()
        if self.dry_run:
            resource_id = path.rsplit("/", 1)[-1]
            print(f"    [dry-run] PATCH {path}")
            return {"data": {"id": resource_id, "attributes": {}}}
        response = self._s.patch(_to_url(path), json=body, timeout=UPLOAD_TIMEOUT)
        _raise(response)
        return response.json()

    def delete(self, path: str) -> None:
        if self.dry_run:
            print(f"    [dry-run] DELETE {path}")
            return
        response = self._s.delete(_to_url(path), timeout=UPLOAD_TIMEOUT)
        _raise(response)


def _to_url(path: str) -> str:
    if path.startswith("https://"):
        return path
    if path.startswith("/v2/"):
        return f"{BASE_URL_V2}{path[3:]}"
    return f"{BASE_URL}{path}"


def _raise(response: "requests.Response") -> None:
    if not response.ok:
        try:
            detail = json.dumps(response.json(), indent=2)
        except Exception:
            detail = response.text
        print(
            f"\nAPI error {response.status_code} {response.request.method} "
            f"{response.request.url}:\n{detail}",
            file=sys.stderr,
        )
        response.raise_for_status()


# ── attribute helpers ─────────────────────────────────────────────────────────

def _ach_attrs(achievement: dict) -> dict:
    return {
        "referenceName": achievement["referenceName"],
        "vendorIdentifier": achievement["id"],
        "points": achievement["points"],
        "showBeforeEarned": not achievement["hidden"],
        "repeatable": False,
    }


def _loc_attrs(achievement: dict, locale: str = DEFAULT_LOCALE) -> dict:
    if locale == DEFAULT_LOCALE:
        title = achievement["title"]
        description = achievement["description"]
    else:
        loc = achievement.get("localizations", {}).get(locale, {})
        title = loc.get("title", achievement["title"])
        description = loc.get("description", achievement["description"])
    return {
        "locale": locale,
        "name": title,
        "beforeEarnedDescription": description,
        "afterEarnedDescription": description,
    }


def _target_locales(achievement: dict) -> list[str]:
    # Extra locales come from each achievement's own `localizations` map.
    extra = list(achievement.get("localizations", {}).keys())
    return [DEFAULT_LOCALE] + extra


def timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_failure_state(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "failures": {}}

    try:
        payload = json.loads(path.read_text())
    except Exception as exc:
        print(
            f"Warning: could not parse {path.name} ({exc}); starting with an empty failure log.",
            file=sys.stderr,
        )
        return {"version": 1, "failures": {}}

    failures = payload.get("failures", {})
    if not isinstance(failures, dict):
        print(
            f"Warning: {path.name} did not contain a valid failures map; starting fresh.",
            file=sys.stderr,
        )
        failures = {}

    return {
        "version": 1,
        "failures": failures,
    }


def save_failure_state(path: Path, state: dict) -> None:
    failures = state.get("failures", {})
    if not failures:
        if path.exists():
            path.unlink()
        return

    payload = {
        "version": 1,
        "updatedAt": timestamp(),
        "failures": failures,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def prune_failure_state(state: dict, valid_ids: set[str]) -> None:
    failures = state.setdefault("failures", {})
    for vendor_id in list(failures.keys()):
        if vendor_id not in valid_ids:
            failures.pop(vendor_id, None)


def record_image_failure(state: dict, achievement: dict, image_path: Path, exc: Exception) -> None:
    failures = state.setdefault("failures", {})
    existing = failures.get(achievement["id"], {})
    failures[achievement["id"]] = {
        "referenceName": achievement["referenceName"],
        "title": achievement["title"],
        "imagePath": display_path(image_path),
        "lastError": str(exc),
        "failedAt": timestamp(),
        "attempts": int(existing.get("attempts", 0)) + 1,
    }


def clear_image_failure(state: dict, vendor_id: str) -> None:
    state.setdefault("failures", {}).pop(vendor_id, None)


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(asc_client.REPO))
    except ValueError:
        return str(path)


# ── API helpers ───────────────────────────────────────────────────────────────

def find_app_id(client: ASCClient, bundle_id: str) -> str:
    data = client.get("/apps", {"filter[bundleId]": bundle_id})
    items = data.get("data", [])
    if not items:
        sys.exit(
            f"No app found for bundle ID '{bundle_id}'.\n"
            "Make sure the app exists in App Store Connect."
        )
    return items[0]["id"]


def find_gcd_id(client: ASCClient, app_id: str) -> str:
    data = client.get(f"/apps/{app_id}/gameCenterDetail")
    game_center_detail = data.get("data")
    if not game_center_detail:
        sys.exit(
            "No Game Center Detail found for this app.\n"
            "Enable Game Center in the app's Features tab in App Store Connect first."
        )
    return game_center_detail["id"]


def list_existing(client: ASCClient, gcd_id: str) -> dict:
    items = client.get_all(
        f"/gameCenterDetails/{gcd_id}/gameCenterAchievements",
        {"fields[gameCenterAchievements]": FILE_FIELDS},
    )
    return {item["attributes"]["vendorIdentifier"]: item for item in items}


def get_localizations_map(client: ASCClient, achievement_id: str) -> dict:
    items = client.get_all(f"/gameCenterAchievements/{achievement_id}/localizations")
    return {item["attributes"]["locale"]: item for item in items}


def create_achievement(client: ASCClient, achievement: dict, gcd_id: str) -> str:
    body = {
        "data": {
            "type": "gameCenterAchievements",
            "attributes": _ach_attrs(achievement),
            "relationships": {
                "gameCenterDetail": {
                    "data": {"type": "gameCenterDetails", "id": gcd_id}
                }
            },
        }
    }
    result = client.post("/gameCenterAchievements", body)
    return result["data"]["id"]


def update_achievement(client: ASCClient, achievement_id: str, achievement: dict) -> None:
    attrs = {key: value for key, value in _ach_attrs(achievement).items() if key != "vendorIdentifier"}
    client.patch(
        f"/gameCenterAchievements/{achievement_id}",
        {"data": {"type": "gameCenterAchievements", "id": achievement_id, "attributes": attrs}},
    )


def create_localization(client: ASCClient, achievement_id: str, achievement: dict, locale: str = DEFAULT_LOCALE) -> str:
    result = client.post(
        "/gameCenterAchievementLocalizations",
        {
            "data": {
                "type": "gameCenterAchievementLocalizations",
                "attributes": _loc_attrs(achievement, locale),
                "relationships": {
                    "gameCenterAchievement": {
                        "data": {"type": "gameCenterAchievements", "id": achievement_id}
                    }
                },
            }
        },
    )
    return result["data"]["id"]


def update_localization(client: ASCClient, localization_id: str, achievement: dict, locale: str = DEFAULT_LOCALE) -> None:
    attrs = {key: value for key, value in _loc_attrs(achievement, locale).items() if key != "locale"}
    client.patch(
        f"/gameCenterAchievementLocalizations/{localization_id}",
        {
            "data": {
                "type": "gameCenterAchievementLocalizations",
                "id": localization_id,
                "attributes": attrs,
            }
        },
    )


def get_image_for_localization(client: ASCClient, localization_id: str) -> Optional[dict]:
    response = client.get_optional(
        f"/v2/gameCenterAchievementLocalizations/{localization_id}/image",
        {
            "fields[gameCenterAchievementImages]": "fileName,fileSize,imageAsset,assetDeliveryState"
        },
    )
    if not response:
        return None
    return response.get("data")


def create_image_reservation(client: ASCClient, localization_id: str, image_path: Path) -> dict:
    body = {
        "data": {
            "type": "gameCenterAchievementImages",
            "attributes": {
                "fileName": image_path.name,
                "fileSize": image_path.stat().st_size,
            },
            "relationships": {
                "localization": {
                    "data": {
                        "type": "gameCenterAchievementLocalizations",
                        "id": localization_id,
                    }
                }
            },
        }
    }
    return client.post("/v2/gameCenterAchievementImages", body)


def delete_image(client: ASCClient, image_id: str) -> None:
    client.delete(f"/v2/gameCenterAchievementImages/{image_id}")


def mark_image_uploaded(client: ASCClient, image_id: str) -> None:
    client.patch(
        f"/v2/gameCenterAchievementImages/{image_id}",
        {
            "data": {
                "type": "gameCenterAchievementImages",
                "id": image_id,
                "attributes": {"uploaded": True},
            }
        },
    )


def upload_reserved_asset(reservation: dict, image_path: Path, dry_run: bool) -> None:
    operations = (
        reservation.get("data", {})
        .get("attributes", {})
        .get("uploadOperations", [])
    )
    if not operations:
        raise RuntimeError(f"No upload operations returned for {image_path.name}")

    if dry_run:
        print(f"    [dry-run] UPLOAD {image_path.name}")
        return

    payload = image_path.read_bytes()
    for operation in operations:
        method = (operation.get("method") or "PUT").upper()
        url = operation.get("url")
        if not url:
            raise RuntimeError(f"Upload operation for {image_path.name} is missing a URL")

        offset = int(operation.get("offset") or 0)
        length = int(operation.get("length") or (len(payload) - offset))
        chunk = payload[offset:offset + length]
        headers = {
            header["name"]: header["value"]
            for header in operation.get("requestHeaders", [])
            if header.get("name") and header.get("value") is not None
        }

        response = requests.request(
            method,
            url,
            headers=headers,
            data=chunk,
            timeout=UPLOAD_TIMEOUT,
        )
        _raise(response)


def resolve_image_path(achievement: dict, icons_dir: Path) -> Path:
    image_asset = achievement.get("imageAsset")
    if image_asset:
        path = Path(image_asset)
        return path if path.is_absolute() else asc_client.REPO / path
    return icons_dir / f"{achievement['id']}.png"


def asset_state(image_record: Optional[dict]) -> str:
    if not image_record:
        return ""
    state = (image_record.get("attributes") or {}).get("assetDeliveryState") or {}
    if isinstance(state, dict):
        value = state.get("state")
        if isinstance(value, str):
            return value.upper()
    return ""


def sync_image(
    client: ASCClient,
    localization_id: str,
    achievement: dict,
    icons_dir: Path,
) -> str:
    image_path = resolve_image_path(achievement, icons_dir)
    if not image_path.exists():
        raise FileNotFoundError(f"Missing icon: {image_path}")

    local_size = image_path.stat().st_size
    remote_image = None if localization_id == "DRY_RUN" else get_image_for_localization(client, localization_id)
    remote_attrs = (remote_image or {}).get("attributes") or {}
    remote_state = asset_state(remote_image)

    same_file = (
        remote_attrs.get("fileName") == image_path.name
        and remote_attrs.get("fileSize") == local_size
        and remote_state not in {"FAILED", "INVALID"}
    )
    if same_file:
        return "unchanged"

    action = "replace" if remote_image else "upload"
    if client.dry_run:
        print(f"    [dry-run] {action.upper()} image {image_path.name}")
        return action

    if remote_image:
        delete_image(client, remote_image["id"])

    reservation = create_image_reservation(client, localization_id, image_path)
    image_id = reservation["data"]["id"]
    upload_reserved_asset(reservation, image_path, dry_run=False)
    mark_image_uploaded(client, image_id)
    return action


# ── sync ──────────────────────────────────────────────────────────────────────

def sync(
    client: ASCClient,
    bundle_id: str,
    sync_images: bool,
    icons_dir: Path,
    failure_log: Path,
    only_failed_images: bool,
) -> int:
    if not ACHIEVEMENTS_JSON.exists():
        sys.exit(f"no achievements file at {ACHIEVEMENTS_JSON} (asc.json paths.achievements)")
    local: list = json.loads(ACHIEVEMENTS_JSON.read_text())
    failure_state = load_failure_state(failure_log)
    prune_failure_state(failure_state, {achievement["id"] for achievement in local})

    if only_failed_images:
        failed_ids = set(failure_state.get("failures", {}).keys())
        local = [achievement for achievement in local if achievement["id"] in failed_ids]
        if not local:
            print(f"No tracked failed image uploads in {failure_log.name}.")
            return 0
        print(f"Retrying {len(local)} tracked failed image uploads from {failure_log.name}")

    print(f"Loaded {len(local)} achievements from {ACHIEVEMENTS_JSON.name}")

    print(f"\nFetching app '{bundle_id}'...")
    app_id = find_app_id(client, bundle_id)
    print(f"  App ID: {app_id}")

    print("Fetching Game Center detail...")
    gcd_id = find_gcd_id(client, app_id)
    print(f"  GCD ID: {gcd_id}")

    print("Fetching existing achievements...")
    existing = list_existing(client, gcd_id)
    print(f"  Found {len(existing)} existing in ASC\n")

    created = updated = unchanged = errors = 0

    for achievement in local:
        vendor_id = achievement["id"]
        reference_name = achievement["referenceName"]

        try:
            metadata_status, all_loc_ids = sync_metadata(client, achievement, gcd_id, existing)
            image_status = "skipped"
            if sync_images:
                try:
                    statuses = [sync_image(client, loc_id, achievement, icons_dir) for loc_id in all_loc_ids]
                    image_status = statuses[0] if len(set(statuses)) == 1 else f"{statuses.count('upload')}up/{statuses.count('unchanged')}ok"
                except Exception as exc:
                    if not client.dry_run:
                        image_path = resolve_image_path(achievement, icons_dir)
                        record_image_failure(failure_state, achievement, image_path, exc)
                    raise
                if not client.dry_run:
                    clear_image_failure(failure_state, vendor_id)

            if metadata_status == "created":
                created += 1
            elif metadata_status == "updated":
                updated += 1
            else:
                unchanged += 1

            print(f"{metadata_status:9} image={image_status:9} {reference_name}")
        except Exception as exc:
            errors += 1
            print(f"error     image=error     {reference_name} — {exc}", file=sys.stderr)

    if sync_images and not client.dry_run:
        save_failure_state(failure_log, failure_state)

    tracked_failures = len(failure_state.get("failures", {}))
    print(
        f"\nDone. created={created} updated={updated} unchanged={unchanged} errors={errors}"
    )
    if sync_images and not client.dry_run:
        if tracked_failures:
            print(
                f"Tracked failed image uploads: {tracked_failures} "
                f"({failure_log.name}; retry with --only-failed-images)"
            )
        else:
            print("Tracked failed image uploads: 0")
    if client.dry_run:
        print("(dry-run — no changes were written to ASC)")
    return 1 if errors else 0


def sync_metadata(client: ASCClient, achievement: dict, gcd_id: str, existing: dict) -> tuple[str, list[str]]:
    vendor_id = achievement["id"]
    target_locales = _target_locales(achievement)

    if vendor_id not in existing:
        achievement_id = create_achievement(client, achievement, gcd_id)
        all_loc_ids = [create_localization(client, achievement_id, achievement, DEFAULT_LOCALE)]
        for locale in target_locales[1:]:
            all_loc_ids.append(create_localization(client, achievement_id, achievement, locale))
        return "created", all_loc_ids

    record = existing[vendor_id]
    achievement_id = record["id"]
    remote_attrs = record["attributes"]

    desired = _ach_attrs(achievement)
    achievement_changed = any(
        remote_attrs.get(key) != value
        for key, value in desired.items()
        if key != "vendorIdentifier"
    )
    if achievement_changed:
        update_achievement(client, achievement_id, achievement)

    loc_map = get_localizations_map(client, achievement_id)
    any_loc_changed = False
    all_loc_ids = []

    for locale in target_locales:
        desired_loc = _loc_attrs(achievement, locale)
        remote_rec = loc_map.get(locale)
        if remote_rec is None:
            loc_id = create_localization(client, achievement_id, achievement, locale)
            any_loc_changed = True
        else:
            loc_id = remote_rec["id"]
            remote_loc = remote_rec["attributes"]
            loc_changed = any(
                remote_loc.get(key) != value
                for key, value in desired_loc.items()
                if key != "locale"
            )
            if loc_changed:
                update_localization(client, loc_id, achievement, locale)
                any_loc_changed = True
        all_loc_ids.append(loc_id)

    if achievement_changed or any_loc_changed:
        return "updated", all_loc_ids
    return "unchanged", all_loc_ids


# ── entry point ───────────────────────────────────────────────────────────────

def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"Missing required env var: {name}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write to App Store Connect (default: dry run)",
    )
    parser.add_argument(
        "--skip-images",
        action="store_true",
        help="Only sync metadata/localizations; skip icon upload work",
    )
    parser.add_argument(
        "--only-failed-images",
        action="store_true",
        help="Retry only the image uploads recorded in the failure log",
    )
    parser.add_argument(
        "--bundle-id",
        default=None,
        metavar="ID",
        help="Override bundle ID",
    )
    parser.add_argument(
        "--icons-dir",
        default=str(DEFAULT_ICONS_DIR),
        metavar="PATH",
        help="Directory containing 512x512 achievement PNGs",
    )
    parser.add_argument(
        "--failure-log",
        default=str(DEFAULT_FAILURE_LOG),
        metavar="PATH",
        help="JSON file used to track failed image uploads",
    )
    args = parser.parse_args()

    if args.skip_images and args.only_failed_images:
        parser.error("--only-failed-images cannot be combined with --skip-images")

    key_id = require_env("ASC_KEY_ID")
    issuer_id = require_env("ASC_ISSUER_ID")
    key_path = require_env("ASC_KEY_PATH")
    if not Path(key_path).expanduser().is_absolute():
        key_path = str(asc_client.REPO / key_path)
    bundle_id = args.bundle_id or os.environ.get("ASC_BUNDLE_ID", "").strip() or asc_client.require_bundle_id(None)
    icons_dir = Path(args.icons_dir).expanduser().resolve()
    failure_log = Path(args.failure_log).expanduser().resolve()

    dry_run = not args.apply
    if dry_run:
        print("─── DRY RUN — no changes will be written (pass --apply) ───\n")

    token = make_token(key_id, issuer_id, key_path)
    client = ASCClient(token, dry_run=dry_run,
                       key_id=key_id, issuer_id=issuer_id, key_path=key_path)
    exit_code = sync(
        client,
        bundle_id,
        sync_images=not args.skip_images,
        icons_dir=icons_dir,
        failure_log=failure_log,
        only_failed_images=args.only_failed_images,
    )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
