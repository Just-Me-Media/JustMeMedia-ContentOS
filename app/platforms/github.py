"""GitHub publishing via the GitHub REST API.

Creates a gist (default) or a repository issue with the draft content.

Requires:
  - CONTENTOS_GITHUB_TOKEN (or GITHUB_TOKEN) — a GitHub Personal Access Token
  - CONTENTOS_GITHUB_USERNAME (optional, for gist attribution)

API docs: https://docs.github.com/en/rest
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from app.platforms import PublishResult

GITHUB_API = "https://api.github.com"


def _token() -> str:
    return os.environ.get("CONTENTOS_GITHUB_TOKEN",
                          os.environ.get("GITHUB_TOKEN", "")).strip()


def _username() -> str:
    return os.environ.get("CONTENTOS_GITHUB_USERNAME", "").strip()


def _auth_headers() -> dict:
    tok = _token()
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "User-Agent": "ContentOS/1.0",
    }
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    return headers


def publish(draft_id: int, title: str, body: str,
            image_url: str = "", media_url: str = "") -> PublishResult:
    """Publish a draft as a GitHub Gist."""
    token = _token()
    if not token:
        return PublishResult(ok=False, platform="github",
                             error="GitHub token not configured")

    # Build a markdown file for the gist
    filename = f"draft_{draft_id}.md"
    content = f"# {title}\n\n{body}\n"
    if image_url:
        content += f"\n![Image]({image_url})\n"

    gist_body = json.dumps({
        "description": title,
        "public": False,
        "files": {
            filename: {"content": content},
        },
    }).encode()

    req = urllib.request.Request(
        f"{GITHUB_API}/gists",
        data=gist_body,
        headers=_auth_headers(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
        gist_id = result.get("id", "")
        html_url = result.get("html_url", "")
        return PublishResult(ok=True, platform="github",
                             post_id=gist_id, live_url=html_url)
    except urllib.error.HTTPError as exc:
        err = exc.read().decode()[:500]
        return PublishResult(ok=False, platform="github",
                             error=f"GitHub API {exc.code}: {err}")
    except Exception as exc:
        return PublishResult(ok=False, platform="github", error=str(exc))