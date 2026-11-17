# Changelog

All notable changes to JustMeMedia ContentOS will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.2] - 2026-11-17

### Fixed
- **X formatting unified:** a single weighted-length counter (URLs = 23 chars, emoji = 2) now drives `format_for_x`, `format_as_thread` and the X publish adapter. No more naive `[:277]` truncation that could cut a URL or hashtag mid-token.
- **Dead schema removed:** `content_items` / `content_versions` / `claims` tables and their unused API endpoints were removed (nothing wrote to them; `drafts` + `draft_versions` + `sources` are the real model), along with the unreferenced legacy `server.windows.py` / `server.head.py` snapshots that duplicated them.
- **Carousel CTA configurable:** `format_as_carousel()` accepts a `handle` (env `CONTENTOS_BRAND_HANDLE`), replacing the hardcoded `@JustMeMedia`.

## [1.0.1] - 2026-11-17

### Fixed
- GitHub Weekly: offline sample data is now visibly labeled in the UI and cannot generate a post until live data is fetched; the `sample` flag persists through storage and the generated bundle.
- Auto-update: 404 ("no releases published") is no longer reported as a failed check.
- Timezone: GitHub snapshots and weekly lookups share one local-date clock.
- Frontend: restored Studio / Calendar / GitHub Weekly / Sources routes; cache headers prevent stale UI after updates.

## [1.0.0] - 2026-11-13

### Added

#### Source Watchlist (User-Friendly Content Discovery)
- New `/watchlist` page for managing RSS feed sources
- Add/remove feeds via URL or curated presets (TechCrunch, Wired, Hacker News, OpenAI, etc.)
- Auto-queue new stories from watchlist feeds at daily 6:30 AM scan
- Toggle feeds on/off without deleting
- Edit feed metadata (label, category)
- Search and filter watchlist items
- Backend: `source_watchlist` table with CRUD operations
- API endpoints: `/api/watchlist`, `/api/watchlist/add`, `/api/watchlist/update`, `/api/watchlist/remove`, `/api/watchlist/check`, `/api/watchlist/scan`
- Worker now uses watchlist feeds as primary source

#### Unified Image Generation
- Local Draw Things integration (macOS, Apple Silicon)
- OpenAI DALL-E 3 support (`OPENAI_API_KEY`)
- Stability AI (SDXL) support (`STABILITY_API_KEY`)
- Replicate FLUX support (`REPLICATE_API_TOKEN`)
- Provider selection via `IMAGE_PROVIDER` env var: auto, drawthings, openai, stability, replicate
- Auto-image generation on post creation (`/api/generate` with `auto_image: true`)
- Cloud fallbacks when Draw Things unavailable

#### Auto-Update System
- `check_for_update()` function using GitHub Releases API
- `/api/update` endpoint for frontend polling
- Settings page now shows update status with changelog
- Silent background update checks at startup

#### Secure Credential Management
- Added X/Twitter OAuth 1.0a credentials support
- `CONTENTOS_X_OAUTH_ACCESS_TOKEN` environment variable
- Updated `_oauth1()` to return 4-tuple: (consumer_key, consumer_secret, access_token, access_token_secret)
- Updated `_oauth1_header()` to use OAuth 1.0a when full credentials available
- Added X credentials to `_ENV_KEY_FALLBACK` for secure loading

#### Frontend Improvements
- New `Watchlist` view (`/src/views/Watchlist.tsx`)
- Updated `Settings` view with update checking
- API client: `getWatchlist`, `addWatchlistItem`, `updateWatchlistItem`, `removeWatchlistItem`, `checkWatchlist`, `scanWatchlist`, `checkUpdate`
- Types: Added `WatchlistItem` interface

#### Distribution & Packaging
- `scripts/dist.sh` - macOS/Windows distribution builder
- `scripts/dist-windows.ps1` - Windows PowerShell distribution script
- `SIGN.md` - Code signing documentation for enterprise distribution
- Frontend builds to `static/` directory

#### Backend Infrastructure
- `CONTENTOS_VERSION` constant for version tracking
- `GITHUB_REPO` constant for update checks
- Image provider status: `/api/image-providers` endpoint
- Watchlist table with migration support

### Security
- X/Twitter credentials no longer exposed in chat
- All credentials loaded from secure keys file or environment variables
- DNS-rebinding protection maintained (127.0.0.1, localhost only)
- CSRF protection on all POST requests
- 2MB request size limit enforced

### Fixed
- Rich text editor formatting now applies to highlighted text
- Version snapshots include `body_html` for proper revert
- Publish flow shows spinner and success/error toasts
- Mark as published button works without API credentials

## [0.9.0] - Previous Release

See commit history for previous changes.