"""X / Twitter publishing via the Twitter API v2 (OAuth 2.0 Bearer Token / OAuth 1.0a).

Requires:
  - CONTENTOS_X_ACCESS_TOKEN (or X_ACCESS_TOKEN / TWITTER_ACCESS_TOKEN)
  - CONTENTOS_X_CONSUMER_KEY + CONTENTOS_X_CONSUMER_SECRET + CONTENTOS_X_ACCESS_TOKEN_SECRET
    for OAuth 1.0a (recommended for media uploads)

API docs: https://developer.twitter.com/en/docs/twitter-api
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from app.platforms import PublishResult

TWITTER_API = "https://api.twitter.com/2"
TWITTER_UPLOAD = "https://upload.twitter.com/1.1"


def _oauth2_client_credentials() -> tuple[str, str]:
    """Return (client_id, client_secret) for OAuth 2.0 Bearer Token auth."""
    return (
        os.environ.get("CONTENTOS_X_CLIENT_ID", "").strip(),
        os.environ.get("CONTENTOS_X_CLIENT_SECRET", "").strip(),
    )


def _get_bearer_token() -> str:
    """Get OAuth 2.0 Bearer Token using client credentials grant.
    
    Returns the bearer token or empty string if auth fails.
    """
    import base64
    client_id, client_secret = _oauth2_client_credentials()
    if not client_id or not client_secret:
        return ""
    
    # Encode client credentials as Basic auth
    creds = f"{client_id}:{client_secret}"
    encoded = base64.b64encode(creds.encode()).decode()
    
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "client_type": "public",
    }).encode()
    
    try:
        req = urllib.request.Request(
            "https://api.twitter.com/2/oauth2/token",
            data=data,
            headers={
                "Authorization": f"Basic {encoded}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
        token = result.get("access_token", "")
        if token:
            return token
    except urllib.error.HTTPError as exc:
        err = exc.read().decode()[:500]
        print(f"[X OAuth2] Token error: {err}")
    except Exception as exc:
        print(f"[X OAuth2] Error: {exc}")
    
    return ""


def _bearer() -> str:
    """Get the Bearer token. Prefers OAuth 2.0 client credentials grant,
    falls back to pre-generated access token if set."""
    # First try OAuth 2.0 client credentials
    token = _get_bearer_token()
    if token:
        return token
    
    # Fall back to pre-set access token
    return os.environ.get("CONTENTOS_X_ACCESS_TOKEN",
                          os.environ.get("X_ACCESS_TOKEN",
                          os.environ.get("TWITTER_ACCESS_TOKEN", ""))).strip()


def _oauth1_access_token() -> str:
    """Return the OAuth 1.0a access token (falls back to bearer token)."""
    return os.environ.get("CONTENTOS_X_OAUTH_ACCESS_TOKEN",
                         os.environ.get("CONTENTOS_X_ACCESS_TOKEN", "")).strip()


def _oauth1() -> tuple[str, str, str, str]:
    """Return (consumer_key, consumer_secret, access_token, access_token_secret) or empty strings."""
    return (
        os.environ.get("CONTENTOS_X_CONSUMER_KEY", "").strip(),
        os.environ.get("CONTENTOS_X_CONSUMER_SECRET", "").strip(),
        _oauth1_access_token(),
        os.environ.get("CONTENTOS_X_ACCESS_TOKEN_SECRET", "").strip(),
    )


def _oauth1_header(method: str, url: str, params: dict | None = None) -> str:
    """Build an OAuth 1.0a Authorization header for the given request."""
    import time
    import hashlib
    import hmac

    ck, cs, at, ats = _oauth1()
    if not at:
        at = _bearer()
    if not (ck and cs and at and ats):
        return ""

    all_params = {
        "oauth_consumer_key": ck,
        "oauth_token": at,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_nonce": base64.b64encode(os.urandom(16)).decode().rstrip("="),
        "oauth_version": "1.0",
    }
    if params:
        all_params.update(params)

    # Sort and encode
    sig_params = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(v), safe='')}"
        for k, v in sorted(all_params.items())
    )
    sig_base = f"{method.upper()}&{urllib.parse.quote(url, safe='')}&{urllib.parse.quote(sig_params, safe='')}"
    signing_key = f"{urllib.parse.quote(cs, safe='')}&{urllib.parse.quote(ats, safe='')}"
    sig = base64.b64encode(
        hmac.new(signing_key.encode(), sig_base.encode(), hashlib.sha1).digest()
    ).decode()

    auth_params = {**all_params, "oauth_signature": sig}
    return "OAuth " + ", ".join(
        f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
        for k, v in auth_params.items()
    )


def _upload_media(media_url: str) -> str:
    """Upload media to Twitter and return a media_id string."""
    if not media_url:
        return ""
    try:
        # Download the media
        with urllib.request.urlopen(media_url, timeout=30) as resp:
            media_data = resp.read()

        # Init upload
        init_params = urllib.parse.urlencode({
            "command": "INIT",
            "total_bytes": str(len(media_data)),
            "media_type": "image/jpeg",
        }).encode()
        auth = _oauth1_header("POST", f"{TWITTER_UPLOAD}/media/upload.json")
        init_req = urllib.request.Request(
            f"{TWITTER_UPLOAD}/media/upload.json",
            data=init_params,
            headers={
                "Authorization": auth,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with urllib.request.urlopen(init_req, timeout=30) as init_resp:
            init_data = json.loads(init_resp.read().decode())
        media_id = init_data.get("media_id_string", "")
        if not media_id:
            return ""

        # Append
        append_req = urllib.request.Request(
            f"{TWITTER_UPLOAD}/media/upload.json",
            data=urllib.parse.urlencode({
                "command": "APPEND",
                "media_id": media_id,
                "segment_index": "0",
            }).encode() + b"&media_data=" + base64.b64encode(media_data),
            headers={
                "Authorization": auth,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with urllib.request.urlopen(append_req, timeout=60):
            pass

        # Finalize
        final_req = urllib.request.Request(
            f"{TWITTER_UPLOAD}/media/upload.json",
            data=urllib.parse.urlencode({
                "command": "FINALIZE",
                "media_id": media_id,
            }).encode(),
            headers={
                "Authorization": auth,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with urllib.request.urlopen(final_req, timeout=30):
            pass

        return media_id
    except Exception:
        return ""


def publish(draft_id: int, title: str, body: str,
            image_url: str = "", media_url: str = "") -> PublishResult:
    """Publish a tweet to X / Twitter using OAuth 2.0 Bearer Token."""
    token = _bearer()
    ck, cs, at, ats = _oauth1()
    use_oauth1 = bool(ck and cs and at and ats)

    if not use_oauth1 and not token:
        return PublishResult(ok=False, platform="x",
                             error="X/Twitter credentials not configured. Set CONTENTOS_X_CLIENT_ID + "
                                   "CONTENTOS_X_CLIENT_SECRET (OAuth 2.0) or OAuth 1.0a keys.")

    # Use the SAME canonical formatter as /api/format-x and run_roundtable().
    # Previously this did tweet_text[:277] + "..." which ignored X's t.co URL
    # accounting (23 chars per link) and could cut a URL or hashtag mid-token.
    from app.server import format_for_x
    tweet_text = format_for_x(body if not title else f"{title}\n\n{body}", 280)
    if not tweet_text:
        return PublishResult(ok=False, platform="x",
                             error="Post is empty after formatting for X.")

    payload: dict = {"text": tweet_text}

    # Upload media if provided (requires OAuth 1.0a)
    if (media_url or image_url) and use_oauth1:
        mid = _upload_media(media_url or image_url)
        if mid:
            payload["media"] = {"media_ids": [mid]}

    data = json.dumps(payload).encode()
    if use_oauth1:
        auth = _oauth1_header("POST", f"{TWITTER_API}/tweets")
        headers = {
            "Authorization": auth,
            "Content-Type": "application/json",
        }
    else:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
    req = urllib.request.Request(
        f"{TWITTER_API}/tweets",
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
        tweet_id = result.get("data", {}).get("id", "")
        live_url = f"https://x.com/i/status/{tweet_id}" if tweet_id else ""
        return PublishResult(ok=True, platform="x",
                             post_id=tweet_id, live_url=live_url)
    except urllib.error.HTTPError as exc:
        err = exc.read().decode()[:500]
        return PublishResult(ok=False, platform="x",
                             error=f"Twitter API {exc.code}: {err}")
    except Exception as exc:
        return PublishResult(ok=False, platform="x", error=str(exc))