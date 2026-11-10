#!/usr/bin/env python3
"""Shared App Store Connect API client for every script in this toolkit.

One copy, used by every app. Nothing here names an app: the project is found
from the working directory, by walking up to the nearest **`asc.json`** (or
from `$ASC_CONFIG`), and everything app-specific — bundle id, platforms,
locales, where the copy and images live — is read from that file. See
`asc.example.json`.

Credentials are looked up in this order, first hit wins per value:

  1. the environment (`ASC_ISSUER_ID`, `ASC_KEY_ID`, `ASC_KEY_PATH`)
  2. `<project>/.env`, then the legacy `<project>/Scripts/asc/.env`
  3. `~/.config/asc/.env` — the recommended home, because one key with the
     **App Manager** role works for every app on the team

`ASC_KEY_PATH` may be a path to the `.p8` or the PEM pasted inline.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

try:
    import jwt  # PyJWT
    import requests
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency hint
    sys.exit("needs PyJWT, cryptography, requests and python-dotenv:\n  "
             "python3 -m pip install -r "
             f"{Path(__file__).resolve().parent / 'requirements.txt'}")

TOOLKIT = Path(__file__).resolve().parent
API = "https://api.appstoreconnect.apple.com"
PLATFORMS = ("IOS", "MAC_OS", "TV_OS", "VISION_OS")

# The states in which a version (or app info) can still be edited. An app with a
# live release has more than one of each — the one on sale and the one being
# prepared — and the API returns them in no guaranteed order, so taking `[0]`
# edits whichever happens to come first.
EDITABLE = ("PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED",
            "METADATA_REJECTED", "INVALID_BINARY")

# Default layout, relative to the project root. Override any of these under
# "paths" in asc.json; existing projects keep their own folders that way.
DEFAULT_PATHS = {
    "listing": "marketing/listing",                 # <locale>.txt [+ <locale>.<PLATFORM>.txt]
    "screenshots": "marketing/screenshots/upload",  # [<locale>/]<family>/NN-name.png
    "iapReview": "marketing/iap-review",            # <product suffix>.png / .txt
    "review": "marketing/review",                   # contact.txt, notes.txt for App Review
    "achievements": "marketing/game-center/achievements.json",
    "achievementIcons": "marketing/game-center/icons",
}


# -- Project config ------------------------------------------------------------

def find_config() -> Path | None:
    explicit = os.environ.get("ASC_CONFIG")
    if explicit:
        path = Path(explicit).expanduser().resolve()
        return path if path.exists() else None
    here = Path.cwd().resolve()
    for folder in (here, *here.parents):
        candidate = folder / "asc.json"
        if candidate.exists():
            return candidate
    return None


CONFIG_PATH = find_config()
CONFIG: dict = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH else {}
REPO = CONFIG_PATH.parent if CONFIG_PATH else Path.cwd().resolve()

BUNDLE_ID: str | None = CONFIG.get("bundleId")
APP_PLATFORMS: tuple = tuple(CONFIG.get("platforms") or ("IOS",))
LOCALES: tuple = tuple(CONFIG.get("locales") or ("en-US",))
PRIMARY_LOCALE: str = LOCALES[0]


def project_path(key: str) -> Path:
    """A project folder or file named in asc.json `paths`, or its default."""
    value = (CONFIG.get("paths") or {}).get(key) or DEFAULT_PATHS[key]
    return (REPO / value).resolve()


def product_prefix() -> str:
    """Product ids are `<prefix><suffix>`; the prefix defaults to `<bundleId>.`."""
    return CONFIG.get("productPrefix") or (f"{BUNDLE_ID}." if BUNDLE_ID else "")


def require_bundle_id(given: str | None) -> str:
    bundle = given or BUNDLE_ID
    if not bundle:
        where = CONFIG_PATH or "no asc.json found above the current directory"
        sys.exit(f"no bundle id: set \"bundleId\" in asc.json ({where}) or pass --bundle-id")
    return bundle


def storekit_path() -> Path:
    name = CONFIG.get("storekit")
    if name:
        return (REPO / name).resolve()
    found = sorted(REPO.glob("*.storekit"))
    if len(found) != 1:
        sys.exit("set \"storekit\" in asc.json to the app's .storekit file "
                 f"(found {len(found)} at the project root)")
    return found[0]


def storekit() -> dict:
    """The app's own StoreKit config — the source of truth for product copy.

    Reading it rather than retyping the values is the point: if it renders in
    the app, it is what reaches the store, and there is nothing to drift.
    """
    path = storekit_path()
    if not path.exists():
        sys.exit(f"not found: {path}")
    return json.loads(path.read_text())


def project_version() -> str | None:
    """The version the project builds: the highest MARKETING_VERSION in the pbxproj.

    Highest, not most common: an app target and a test target each contribute
    two build configurations, so a count is a tie.
    """
    import re
    proj = CONFIG.get("xcodeproj")
    candidates = [REPO / proj] if proj else sorted(REPO.glob("*.xcodeproj"))
    versions: set = set()
    for c in candidates:
        pbx = c / "project.pbxproj"
        if pbx.exists():
            versions |= set(re.findall(r"MARKETING_VERSION = \"?([0-9.]+)\"?;", pbx.read_text()))
    if not versions:
        return None
    return max(versions, key=lambda v: tuple(int(p) for p in v.split(".")))


# -- Credentials ---------------------------------------------------------------

for env_file in (REPO / ".env", REPO / "Scripts" / "asc" / ".env",
                 Path("~/.config/asc/.env").expanduser()):
    if env_file.exists():
        load_dotenv(env_file, override=False)  # earlier files and the environment win


def _env(*names: str) -> str | None:
    """First non-empty of `names`, quotes stripped. The bare `KEY_ID` spelling is
    accepted because `.env` files get copied between projects."""
    for name in names:
        value = (os.environ.get(name) or "").strip().strip('"').strip("'")
        if value:
            return value
    return None


def token() -> str:
    """A 20-minute ES256 JWT. Apple rejects any lifetime longer than that."""
    issuer = _env("ASC_ISSUER_ID", "ISSUER_ID")
    key_id = _env("ASC_KEY_ID", "KEY_ID")
    key = _env("ASC_KEY_PATH", "ASC_KEY", "KEY_PATH", "KEY")
    missing = [n for n, v in (("ASC_ISSUER_ID", issuer), ("ASC_KEY_ID", key_id),
                              ("ASC_KEY_PATH", key)) if not v]
    if missing:
        sys.exit("missing App Store Connect credentials: " + ", ".join(missing) +
                 "\n  put them in ~/.config/asc/.env (template: "
                 f"{TOOLKIT / '.env.example'}) or the environment")
    if "BEGIN" in key:
        private_key = key.replace("\\n", "\n")
    else:
        path = Path(key).expanduser()
        if not path.is_absolute():
            path = (REPO / path).resolve()
        if not path.exists():
            sys.exit(f"private key not found: {path}")
        private_key = path.read_text()
    now = int(time.time())
    return jwt.encode(
        {"iss": issuer, "iat": now, "exp": now + 20 * 60, "aud": "appstoreconnect-v1"},
        private_key, algorithm="ES256", headers={"kid": key_id, "typ": "JWT"},
    )


# -- Client --------------------------------------------------------------------

class ASC:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token()}"

    def _check(self, response, context: str):
        if response.status_code >= 400:
            # Apple's errors carry the useful detail in the body, not the status.
            try:
                errors = response.json().get("errors", [])
                detail = "\n  ".join(f"{e.get('title')}: {e.get('detail')}" for e in errors)
            except ValueError:
                detail = response.text[:400]
            sys.exit(f"\n{context} failed [{response.status_code}]\n  {detail}")
        return response.json() if response.content else {}

    def get(self, path: str, **params):
        return self._check(self.session.get(f"{API}{path}", params=params), f"GET {path}")

    def get_soft(self, path: str, **params):
        """GET that returns None instead of exiting on a 4xx — for relationships
        that legitimately may not exist yet."""
        response = self.session.get(f"{API}{path}", params=params)
        if 400 <= response.status_code < 500:
            return None
        return self._check(response, f"GET {path}")

    def post(self, path: str, body: dict):
        return self._check(self.session.post(f"{API}{path}", json=body), f"POST {path}")

    def patch(self, path: str, body: dict):
        return self._check(self.session.patch(f"{API}{path}", json=body), f"PATCH {path}")

    def delete(self, path: str):
        return self._check(self.session.delete(f"{API}{path}"), f"DELETE {path}")

    def paged(self, path: str, **params):
        """Follow `links.next`. Price points in particular run to many pages.
        (A few relationships, e.g. bundleIdCapabilities, 400 on `limit` — use
        `get` for those.)"""
        params.setdefault("limit", 200)
        url, out = f"{API}{path}", []
        while url:
            payload = self._check(self.session.get(url, params=params), f"GET {url}")
            out.extend(payload.get("data", []))
            url, params = payload.get("links", {}).get("next"), {}
        return out

    def app_id(self, bundle_id: str | None = None) -> str:
        bundle = require_bundle_id(bundle_id)
        apps = self.get("/v1/apps", **{"filter[bundleId]": bundle}).get("data", [])
        exact = [a for a in apps if a["attributes"].get("bundleId") == bundle]
        if not exact:
            sys.exit(f"no app found in App Store Connect for bundle id {bundle}")
        return exact[0]["id"]

    def versions(self, app: str, platform: str = "IOS") -> list:
        return self.paged(f"/v1/apps/{app}/appStoreVersions", **{"filter[platform]": platform})

    def store_version(self, app: str, version: str | None = None,
                      platform: str = "IOS") -> dict:
        """The version to edit on `platform`: `version` if named, else the editable one."""
        if platform not in PLATFORMS:
            sys.exit(f"unknown platform {platform!r} (expected one of {', '.join(PLATFORMS)})")
        versions = self.versions(app, platform)
        listing = ", ".join(
            f"{v['attributes'].get('versionString')} [{v['attributes'].get('appStoreState')}]"
            for v in versions) or "none"
        if version:
            for v in versions:
                if v["attributes"].get("versionString") == version:
                    return v
            sys.exit(f"no {platform} version {version} on this app (found: {listing})")
        editable = [v for v in versions if v["attributes"].get("appStoreState") in EDITABLE]
        if not editable:
            sys.exit(f"no editable {platform} version. Create it first:\n  "
                     f"python3 {TOOLKIT / 'version.py'} --create <x.y> --apply\n"
                     f"Found: {listing}")
        return editable[0]

    def editable_app_info(self, app: str) -> dict:
        """The app info that can be edited: not the one currently on sale."""
        infos = self.paged(f"/v1/apps/{app}/appInfos")
        if not infos:
            sys.exit("no app info on this app")
        for info in infos:
            if info["attributes"].get("appStoreState") in EDITABLE:
                return info
        return infos[0]

    def version_localization(self, version_id: str, locale: str) -> dict | None:
        return next((l for l in self.paged(
            f"/v1/appStoreVersions/{version_id}/appStoreVersionLocalizations")
            if l["attributes"].get("locale") == locale), None)


# -- Asset uploads (screenshots, review images, icons) -------------------------

def md5(path: Path) -> str:
    import hashlib
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def upload(operations: list, path: Path) -> None:
    """Perform Apple's `uploadOperations` verbatim.

    Deliberately *not* the authenticated session: these are pre-signed Apple
    object-storage URLs, and sending `Authorization: Bearer <JWT>` alongside the
    signature returns a bare `400 Invalid request` that reads like a bad file.
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


def delivery_state(api: ASC, resource_path: str, tries: int = 12) -> str:
    """Poll an asset's `assetDeliveryState` until it settles."""
    for attempt in range(tries):
        data = api.get(resource_path)["data"]
        state = data["attributes"].get("assetDeliveryState") or {}
        name, errors = state.get("state"), state.get("errors")
        if errors:
            return f"FAILED: {errors}"
        if name and name not in ("UPLOAD_COMPLETE", "PROCESSING"):
            return name
        if name == "UPLOAD_COMPLETE" and attempt >= 2:
            return name
        time.sleep(2)
    return "still processing"


def alpha_problem(path: Path) -> str | None:
    """The one image fault worth failing on locally: App Store Connect refuses an
    RGBA file while complaining about its *size*, which sends you chasing the wrong
    thing. `simctl io screenshot` writes RGBA. Fix with `images.py flatten`."""
    try:
        from PIL import Image
    except ImportError:
        return None
    with Image.open(path) as im:
        if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info:
            return f"has an alpha channel ({im.mode}) — run images.py flatten"
    return None


def dimensions(path: Path):
    try:
        from PIL import Image
    except ImportError:
        return None
    with Image.open(path) as im:
        return im.size
