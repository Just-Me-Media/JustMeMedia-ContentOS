"""Instagram publishing via the Instagram Graph API (requires a Facebook Page).

Instagram publishing requires:
  - A Facebook Page connected to an Instagram Business/Creator account
  - CONTENTOS_FACEBOOK_PAGE_ACCESS_TOKEN (same token as Facebook)
  - CONTENTOS_FACEBOOK_PAGE_ID (the Facebook Page ID, not Instagram ID)

API docs: https://developers.facebook.com/docs/instagram-api

Flow:
  1. Upload container with image + caption
  2. Publish the container
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from app.platforms import PublishResult

FB_API = "https://graph.facebook.com/v19.0"


def _token() -> str:
    return os.environ.get("CONTENTOS_FACEBOOK_PAGE_ACCESS_TOKEN",
                          os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN", "")).strip()


def _page_id() -> str:
    return os.environ.get("CONTENTOS_FACEBOOK_PAGE_ID", "").strip()


def _ig_user_id(token: str, page_id: str) -> str:
    """Get the Instagram Business Account ID linked to the Facebook Page."""
    try:
        req = urllib.request.Request(
            f"{FB_API}/{page_id}?fields=instagram_business_account{id}&access_token={token}",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        return data.get("instagram_business_account", {}).get("id", "")
    except Exception:
        return ""


def _upload_container(ig_user: str, token: str, caption: str,
                      image_url: str) -> str:
    """Create a media container on Instagram. Returns container ID."""
    params = urllib.parse.urlencode({
        "access_token": token,
        "caption": caption,
        "image_url": image_url,
    })
    req = urllib.request.Request(
        f"{FB_API}/{ig_user}/media?{params}",
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        return data.get("id", "")
    except Exception:
        return ""


def _publish_container(ig_user: str, token: str, container_id: str) -> str:
    """Publish a media container. Returns the post ID."""
    params = urllib.parse.urlencode({
        "access_token": token,
        "creation_id": container_id,
    })
    req = urllib.request.Request(
        f"{FB_API}/{ig_user}/media_publish?{params}",
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        return data.get("id", "")
    except Exception:
        return ""


def publish(draft_id: int, title: str, body: str,
            image_url: str = "", media_url: str = "") -> PublishResult:
    """Publish a post to Instagram via the Graph API."""
    token = _token()
    if not token:
        return PublishResult(ok=False, platform="instagram",
                             error="Facebook Page Access Token not configured (Instagram uses the same token)")

    page_id = _page_id()
    if not page_id:
        return PublishResult(ok=False, platform="instagram",
                             error="CONTENTOS_FACEBOOK_PAGE_ID not set")

    ig_user = _ig_user_id(token, page_id)
    if not ig_user:
        return PublishResult(ok=False, platform="instagram",
                             error="No Instagram Business Account linked to this Facebook Page")

    caption = body
    if title:
        caption = f"{title}\n\n{body}"
    # Instagram caption limit is 2200 chars
    caption = caption[:2200]

    img = image_url or media_url
    if not img:
        return PublishResult(ok=False, platform="instagram",
                             error="Instagram requires an image — none provided")

    container_id = _upload_container(ig_user, token, caption, img)
    if not container_id:
        return PublishResult(ok=False, platform="instagram",
                             error="Failed to create Instagram media container")

    post_id = _publish_container(ig_user, token, container_id)
    if not post_id:
        return PublishResult(ok=False, platform="instagram",
                             error="Failed to publish Instagram container")

    live_url = f"https://www.instagram.com/p/{post_id}/"
    return PublishResult(ok=True, platform="instagram",
                         post_id=post_id, live_url=live_url)