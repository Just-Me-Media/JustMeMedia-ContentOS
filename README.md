# JustMeMedia ContentOS

> Built by **Just Me Media** — local-first content operations for independent creators and media teams.

**Status:** Production-ready local-first content operations system  
**Purpose:** A portable, provider-independent content research, drafting, and publishing hub.

ContentOS is intended to remain usable if any one AI provider, cloud platform, or ChatGPT account becomes unavailable. The durable project assets are ordinary files, documented workflows, a local database, and replaceable provider adapters.

## 🔧 New Features (v1.0.0)

### Source Watchlist (User-Friendly Content Discovery)
- **Add/Remove feeds:** Manage your RSS feeds directly in the UI
- **Auto-discovery:** Add feeds via URL or use 10 curated presets (TechCrunch, Wired, Hacker News, OpenAI, etc.)
- **Auto-queue:** Daily 6:30 AM scan automatically queues new stories for review
- **Toggle feeds:** Enable/disable feeds without deleting them
- **Edit metadata:** Rename feeds, reorganize by category
- **Location:** `/watchlist` in the sidebar

### Unified Image Generation
- **Draw Things (macOS, local):** Free, runs on Apple Silicon
- **OpenAI DALL-E 3:** Set `OPENAI_API_KEY` for cloud generation
- **Stability AI (SDXL):** Set `STABILITY_API_KEY` for alternatives
- **Replicate (FLUX):** Set `REPLICATE_API_TOKEN` for FLUX Schnell
- **Auto-image on Generate:** Click "Generate Post" → post + image auto-created and attached

### Auto-Update
- Built-in update check at startup
- Silent background fetch of newer versions
- One-click apply update or view changelog

### Secure Credential Management
- Never stores secrets in Git
- Loads from `~/.secure_keys/.env` when `CONTENTOS_LOAD_KEYS=1`
- Environment variable support for all providers

## Operating principles

1. The user owns the project files, content, prompts, history, and decisions.
2. Local operation is a first-class mode; cloud models are optional.
3. Research/search is a replaceable service. A local model alone does not provide current internet research.
4. Nothing is published, scheduled, sent, or changed on a social account without explicit approval for that specific action.
5. Credentials never belong in prompts, Markdown documentation, Git, logs, or ordinary configuration files.
6. Record verified facts separately from assumptions and opinions.
7. Preserve provenance: source URL, publisher, publication date, retrieval date, claim supported, and verification status.
8. Exportability and recovery matter more than dependence on a particular UI.

## Quick start

```bash
# Clone and enter
cd /path/to/JustMeMedia_ContentOS

# Install frontend dependencies (once)
cd frontend && npm install && npm run build

# Set up environment (optional - for cloud features)
export OPENAI_API_KEY="sk-..."  # or STABILITY_API_KEY, REPLICATE_API_TOKEN

# Run the app
cd .. && python3 app/server.py
# Opens automatically at http://127.0.0.1:8765
```

## Two-computer operating model

Both the Windows ThinkCentre and MacBook Pro are first-class hosts. They can each run the application and local model adapters.

**Important database rule:** Do not open the same SQLite database file concurrently from two computers over a network share or cloud-synced folder. SQLite is a local database, not a multi-computer synchronization protocol.

Recommended arrangement:
- Each computer has its own `database/local/contentos.sqlite3`.
- Shared project assets (prompts, brand guidance, drafts, source notes, approved content) are synchronized using a private Git repository or a trusted file-sync tool.
- Database exports/snapshots are backed up separately.
- Each machine keeps a local working copy and local backup.
- Keep at least one additional encrypted backup on an external drive, disconnected when not in use.

## Folder map

- `brand/` — visual identity and editorial voice
- `config/` — safe, non-secret configuration templates
- `strategy/` — audience, positioning, content pillars
- `research/` — source intake and verified research
- `prompts/` — provider-neutral model prompts
- `workflows/` — human-readable operating procedures
- `content/` — ideas, drafts, approved and published content
- `assets/` — graphics and video
- `approvals/` — explicit approval records
- `analytics/` — platform performance records
- `providers/` — adapter contracts and provider notes
- `database/` — schema and per-machine local database
- `backups/` — backup instructions and manifests
- `logs/` — non-secret operational logs
- `app/` — backend server, worker, and scheduler
- `frontend/` — React/Vite/TypeScript browser UI
- `static/` — built frontend assets (generated)
- `scripts/` — portable setup and maintenance scripts

## Features & Architecture

### UI Features
- **Sidebar Navigation:** Dashboard, Discover, Sources (Watchlist), Studio, Queue, Calendar, GitHub Weekly, Settings
- **Discover Page:** Browse RSS feeds, 1-click draft creation, AI autopilot batch engine
- **Source Watchlist:** Add/remove/manage RSS feeds, auto-queue new stories
- **Content Studio:** Rich text editor with formatting, color toolbar, image gallery, AI assistant panel
- **Review Queue:** Drafts awaiting approval, with preview and publish buttons
- **Calendar:** Scheduled content management

### Background Worker
The `app/worker.py` script runs as a daemon:
```bash
# Once (daemon mode)
python3 app/worker.py

# One-time scan
python3 app/worker.py --once
```

It scans your watchlist feeds at 6:30 AM daily and queues new stories.

### Image Generation Configuration
Set environment variables for your preferred provider:
```bash
# Draw Things (macOS, free, local) - enable HTTP server in Draw Things Settings
# Default when running locally

# OpenAI DALL-E 3
export OPENAI_API_KEY="sk-..."

# Stability AI (SDXL)
export STABILITY_API_KEY="sk-..."

# Replicate (FLUX Schnell)
export REPLICATE_API_TOKEN="r8_..."

# Select provider: auto (default), openai, stability, replicate, drawthings
export IMAGE_PROVIDER="auto"
```

### Social Platform Publishing
ContentOS supports publishing to:
- LinkedIn
- X / Twitter (requires OAuth 1.0a credentials)
- Facebook
- Instagram
- YouTube
- GitHub (for weekly posts)

### Secure Credentials
Store credentials in `~/.secure_keys/.env`:
```
CONTENTOS_X_ACCESS_TOKEN=your_bearer_token
CONTENTOS_X_OAUTH_ACCESS_TOKEN=your_oauth_token
CONTENTOS_X_CONSUMER_KEY=your_consumer_key
CONTENTOS_X_CONSUMER_SECRET=your_consumer_secret
CONTENTOS_X_ACCESS_TOKEN_SECRET=your_access_token_secret

OPENAI_API_KEY=sk-...
STABILITY_API_KEY=sk-...
REPLICATE_API_TOKEN=r8_...
DRAW_THINGS_API_KEY=your_key
```

Enable loading with:
```bash
export CONTENTOS_LOAD_KEYS=1
```

## macOS Desktop App (double-click to launch)

Build a `ContentOS.app` for your Desktop with:

```bash
bash scripts/make_macos_app.sh
```

Double-clicking it starts the local server in the background (via a LaunchAgent, so it survives) and opens the UI in a clean Chrome app window — no Terminal, no tabs. Logs go to `~/Library/Logs/ContentOS/`.

## Tests

```bash
# Run test suite (50 tests)
PYTHONPATH=. python3 -B -m unittest discover -s tests -p 'test_*.py'

# Compile check
python3 -m compileall -q app tests
```

## Distribution (Building a Release)

```bash
# Build frontend
cd frontend && npm run build

# Create distribution archive
./scripts/dist.sh
```

Creates `contentos-dist.zip` containing:
- `/app/` — backend Python files
- `/static/` — built frontend
- `/config/` — configuration templates  
- `/scripts/` — run scripts
- `README.md`, `LICENSE`

## Auto-Update System

ContentOS checks for updates at startup. The update mechanism:
1. Fetches latest version info from GitHub releases
2. Compares with current version
3. Downloads and applies update silently
4. Shows changelog on first run after update

## Security & Privacy

- ✅ Local-only operation (no mandatory cloud)
- ✅ No telemetry or analytics collection
- ✅ CSRF protection on all POST requests
- ✅ DNS-rebinding protection (127.0.0.1, localhost only)
- ✅ 2MB request size limit
- ✅ Credentials never in code or Git
- ✅ Human approval required before publishing

## License

MIT License — see LICENSE file for details.