"""Facebook Page publishing via the Facebook Graph API.

Requires:
  - CONTENTOS_FACEBOOK_PAGE_ACCESS_TOKEN (or FACEBOOK_PAGE_ACCESS_TOKEN)
  - CONTENTOS_FACEBOOK_PAGE_ID (optional; defaults to "me")

API docs: https://developers.facebook.com/docs/graph-api/reference/pg/posts
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from app.platforms import PublishResult

FB_API = "https://graph.facebook.com/v19.0"


def _token() -> str:
    return os.environ.get("CONTENTOS_FACEBOOK_PAGE_ACCESS_TOKEN",
                          os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN", "")).strip()


def _page_id() -> str:
    return os.environ.get("CONTENTOS_FACEBOOK_PAGE_ID", "me").strip()


def _upload_photo(token: str, image_url: str) -> str:
    """Upload a photo to Facebook and return its ID."""
    if not image_url:
        return ""
    try:
        with urllib.request.urlopen(image_url, timeout=30) as resp:
            img_data = resp.read()
        req = urllib.request.Request(
            f"{FB_API}/me/photos",
            data=img_data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        return data.get("id", "")
    except Exception:
        return ""


def publish(draft_id: int, title: str, body: str,
            image_url: str = "", media_url: str = "") -> PublishResult:
    """Publish a post to a Facebook Page."""
    token = _token()
    if not token:
        return PublishResult(ok=False, platform="facebook",
                             error="Facebook Page Access Token not configured")

    page = _page_id()
    message = body
    if title:
        message = f"{title}\n\n{body}"

    # Upload photo first if we have one
    photo_id = _upload_photo(token, image_url or media_url)

    post_data: dict = {"message": message}
    if photo_id:
        post_data["attached_media"] = json.dumps([{"type": "photo", "media": {"id": photo_id}}])

    data = urllib.parse.urlencode(post_data).encode()
    req = urllib.request.Request(
        f"{FB_API}/{page}/feed",
        data=data,
        headers={"Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
        post_id = result.get("id", "")
        live_url = f"https://www.facebook.com/{post_id}" if post_id else ""
        return PublishResult(ok=True, platform="facebook",
                             post_id=post_id, live_url=live_url)
    except urllib.error.HTTPError as exc:
        err = exc.read().decode()[:500]
        return PublishResult(ok=False, platform="facebook",
                             error=f"Facebook API {exc.code}: {err}")
    except Exception as exc:
        return PublishResult(ok=False, platform="facebook", error=str(exc))