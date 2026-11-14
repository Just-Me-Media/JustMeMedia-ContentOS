"""YouTube publishing via the YouTube Data API v3.

Requires:
  - CONTENTOS_YOUTUBE_API_KEY (or YOUTUBE_API_KEY / GOOGLE_API_KEY)
  - CONTENTOS_YOUTUBE_CHANNEL_ID (optional; defaults to "mine")

API docs: https://developers.google.com/youtube/v3/docs/videos
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional

from app.platforms import PublishResult

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"


def _api_key() -> str:
    return os.environ.get("CONTENTOS_YOUTUBE_API_KEY",
                          os.environ.get("YOUTUBE_API_KEY",
                          os.environ.get("GOOGLE_API_KEY", ""))).strip()


def _channel_id() -> str:
    return os.environ.get("CONTENTOS_YOUTUBE_CHANNEL_ID", "mine").strip()


def _upload_thumbnail(video_id: str, image_url: str, api_key: str) -> bool:
    """Upload a thumbnail for a video. Returns True on success."""
    if not image_url:
        return False
    try:
        with urllib.request.urlopen(image_url, timeout=30) as resp:
            thumb_data = resp.read()
        req = urllib.request.Request(
            f"{YOUTUBE_API}/thumbnails/set?videoId={video_id}&key={api_key}",
            data=thumb_data,
            headers={"Content-Type": "image/jpeg"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30):
            return True
    except Exception:
        return False


def publish(draft_id: int, title: str, body: str,
            image_url: str = "", media_url: str = "") -> PublishResult:
    """Publish a video to YouTube.

    Since we don't have a local video file, this creates a YouTube Short
    or community post with the draft text and thumbnail.
    """
    api_key = _api_key()
    if not api_key:
        return PublishResult(ok=False, platform="youtube",
                             error="YouTube API key not configured")

    # Build a YouTube video resource (Shorts are <= 60s)
    video_body = {
        "snippet": {
            "title": title[:100],
            "description": body[:5000],
            "categoryId": "22",  # People & Blogs
            "tags": ["ContentOS", "AutoPost"],
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
        "contentDetails": {
            "definition": "sd",
            "caption": "false",
        },
    }

    data = json.dumps(video_body).encode()
    req = urllib.request.Request(
        f"{YOUTUBE_API}/videos?part=snippet,status,contentDetails&key={api_key}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())
        video_id = result.get("id", "")
        if not video_id:
            err = result.get("error", {}).get("message", "Unknown error")
            return PublishResult(ok=False, platform="youtube", error=err)

        # Upload thumbnail if we have an image
        if image_url:
            _upload_thumbnail(video_id, image_url, api_key)

        live_url = f"https://www.youtube.com/shorts/{video_id}" if video_id else ""
        return PublishResult(ok=True, platform="youtube",
                             post_id=video_id, live_url=live_url)
    except urllib.error.HTTPError as exc:
        err = exc.read().decode()[:500]
        return PublishResult(ok=False, platform="youtube",
                             error=f"YouTube API {exc.code}: {err}")
    except Exception as exc:
        return PublishResult(ok=False, platform="youtube", error=str(exc))