"""Platform adapter dispatcher — routes a draft to the correct platform publisher."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# Credential loader (env vars only — no secrets in code)
# ─────────────────────────────────────────────────────────────────────────────

_PLATFORM_ENV_KEYS = {
    "linkedin": ["CONTENTOS_LINKEDIN_ACCESS_TOKEN", "LINKEDIN_ACCESS_TOKEN"],
    "x":        ["CONTENTOS_X_ACCESS_TOKEN", "X_ACCESS_TOKEN", "TWITTER_ACCESS_TOKEN"],
    "youtube":  ["CONTENTOS_YOUTUBE_API_KEY", "YOUTUBE_API_KEY", "GOOGLE_API_KEY"],
    "facebook": ["CONTENTOS_FACEBOOK_PAGE_ACCESS_TOKEN", "FACEBOOK_PAGE_ACCESS_TOKEN"],
    "instagram":["CONTENTOS_INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_ACCESS_TOKEN"],
    "github":   ["CONTENTOS_GITHUB_TOKEN", "GITHUB_TOKEN"],
}


def load_platform_credential(platform: str) -> Optional[str]:
    """Return the first available credential env var for a platform, or None."""
    for key in _PLATFORM_ENV_KEYS.get(platform.lower(), []):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    return None


def is_platform_configured(platform: str) -> bool:
    """True if at least one credential env var is set for the platform."""
    return load_platform_credential(platform) is not None


# ─────────────────────────────────────────────────────────────────────────────
# Result type
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PublishResult:
    ok: bool
    platform: str
    post_id: str = ""
    live_url: str = ""
    error: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Lazy adapter imports (avoid requiring optional deps at startup)
# ─────────────────────────────────────────────────────────────────────────────

_adapter_cache: dict[str, object] = {}


def _get_adapter(platform: str):
    """Import and cache the adapter for a platform."""
    if platform in _adapter_cache:
        return _adapter_cache[platform]

    mod = __import__(
        f"app.platforms.{platform.lower()}",
        fromlist=["publish"],
    )
    _adapter_cache[platform] = mod
    return mod


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def publish(draft_id: int, title: str, body: str, platform: str,
            image_url: str = "", media_url: str = "") -> PublishResult:
    """Publish a draft to the given platform using the real platform API.

    Returns a PublishResult with ok/post_id/live_url or error.
    """
    platform_key = platform.lower().strip()
    if platform_key not in _PLATFORM_ENV_KEYS:
        return PublishResult(ok=False, platform=platform,
                             error=f"Unknown platform: {platform}")

    if not is_platform_configured(platform_key):
        return PublishResult(ok=False, platform=platform,
                             error=f"No credentials configured for {platform}. "
                                   f"Set one of: {', '.join(_PLATFORM_ENV_KEYS[platform_key])}")

    try:
        adapter = _get_adapter(platform_key)
        return adapter.publish(
            draft_id=draft_id,
            title=title[:200],
            body=body,
            image_url=image_url,
            media_url=media_url,
        )
    except Exception as exc:  # noqa: BLE001 — surface any adapter failure
        return PublishResult(ok=False, platform=platform, error=str(exc))
