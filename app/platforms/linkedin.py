"""LinkedIn publishing via the official LinkedIn UGC Posts API (v2).

Requires:
  - CONTENTOS_LINKEDIN_ACCESS_TOKEN (or LINKEDIN_ACCESS_TOKEN) — a LinkedIn OAuth2 token
  - CONTENTOS_LINKEDIN_ORGANIZATION_URN — e.g. "urn:li:organization:123456789"
    (optional; falls back to user-only posts)

API docs: https://learn.microsoft.com/linkedin/shared/api-guide/ugc-posts
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from app.platforms import PublishResult

LINKEDIN_API = "https://api.linkedin.com/v2"
LINKEDIN_OG_API = "https://api.linkedin.com/v2/ugcPosts"


def _token() -> str:
    return os.environ.get("CONTENTOS_LINKEDIN_ACCESS_TOKEN",
                          os.environ.get("LINKEDIN_ACCESS_TOKEN", "")).strip()


def _org_urn() -> str:
    return os.environ.get("CONTENTOS_LINKEDIN_ORGANIZATION_URN", "").strip()


def _author_urn() -> str:
    """Return the author URN from the access token's profile."""
    tok = _token()
    if not tok:
        return ""
    try:
        req = urllib.request.Request(
            f"{LINKEDIN_API}/userinfo",
            headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        sub = data.get("sub", "")
        return f"urn:li:person:{sub}" if sub else ""
    except Exception:
        return ""


def _upload_image(token: str, image_url: str) -> str:
    """Upload an image to LinkedIn and return the media URN."""
    if not image_url:
        return ""
    try:
        # Step 1: Register upload
        register_body = json.dumps({
            "registerUploadRequest": {
                "owner": _author_urn(),
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "serviceProvider": "urn:li:contentMedia:feedshare-image",
                "name": "ContentOS upload",
            }
        }).encode()
        reg_req = urllib.request.Request(
            f"{LINKEDIN_API}/dmp/registries/upload",
            data=register_body,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(reg_req, timeout=15) as reg_resp:
            reg_data = json.loads(reg_resp.read().decode())
        upload_urn = reg_data.get("value", {}).get("uploadMechanism", {}).get(
            "uploadUrl", "")
        if not upload_urn:
            return ""

        # Step 2: Upload binary
        with urllib.request.urlopen(image_url, timeout=30) as img_resp:
            img_data = img_resp.read()
        up_req = urllib.request.Request(
            upload_urn,
            data=img_data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
            },
            method="POST",
        )
        with urllib.request.urlopen(up_req, timeout=30):
            pass

        return reg_data.get("value", {}).get("asset", "")
    except Exception:
        return ""


def publish(draft_id: int, title: str, body: str,
            image_url: str = "", media_url: str = "") -> PublishResult:
    """Publish a post to LinkedIn via the UGC Posts API."""
    token = _token()
    if not token:
        return PublishResult(ok=False, platform="linkedin",
                             error="LinkedIn access token not configured")

    author = _org_urn() or _author_urn()
    if not author:
        return PublishResult(ok=False, platform="linkedin",
                             error="Could not resolve LinkedIn author URN")

    # Upload image if provided
    image_urn = _upload_image(token, image_url) if image_url else ""

    # Build the UGC post payload
    share_text = body
    if title:
        share_text = f"{title}\n\n{body}"

    post_body: dict = {
        "author": author,
        "commentary": share_text,
        "visibility": "CONTRIBUTORS" if author.startswith("urn:li:organization") else "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED"},
    }
    if image_urn:
        post_body["media"] = {
            "media": image_urn,
            "description": title,
            "title": title,
        }

    data = json.dumps(post_body).encode()
    req = urllib.request.Request(
        f"{LINKEDIN_OG_API}/posts",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
        post_id = result.get("id", "")
        live_url = f"https://www.linkedin.com/feed/update/{post_id}/" if post_id else ""
        return PublishResult(ok=True, platform="linkedin",
                             post_id=post_id, live_url=live_url)
    except urllib.error.HTTPError as exc:
        err = exc.read().decode()[:500]
        return PublishResult(ok=False, platform="linkedin",
                             error=f"LinkedIn API {exc.code}: {err}")
    except Exception as exc:
        return PublishResult(ok=False, platform="linkedin", error=str(exc))