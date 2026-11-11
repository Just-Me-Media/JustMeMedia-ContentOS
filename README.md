# JustMeMedia ContentOS

**Status:** Initial local-first scaffold
**Purpose:** A portable, provider-independent content operations system for JustMeMedia.

ContentOS is intended to remain usable if any one AI provider, cloud platform, or ChatGPT account becomes unavailable. The durable project assets are ordinary files, documented workflows, a local database, and replaceable provider adapters.

## Operating principles

1. The user owns the project files, content, prompts, history, and decisions.
2. Local operation is a first-class mode; cloud models are optional.
3. Research/search is a replaceable service. A local model alone does not provide current internet research.
4. Nothing is published, scheduled, sent, or changed on a social account without explicit approval for that specific action.
5. Credentials never belong in prompts, Markdown documentation, Git, logs, or ordinary configuration files.
6. Record verified facts separately from assumptions and opinions.
7. Preserve provenance: source URL, publisher, publication date, retrieval date, claim supported, and verification status.
8. Exportability and recovery matter more than dependence on a particular UI.

## Two-computer operating model

Both the Windows ThinkCentre and MacBook Pro are first-class hosts. They can each run the application and local model adapters.

**Important database rule:** Do not open the same SQLite database file concurrently from two computers over a network share or cloud-synced folder. SQLite is a local database, not a multi-computer synchronization protocol.

Recommended arrangement:
- Each computer has its own `database/local/contentos.sqlite3`.
- Shared project assets (prompts, brand guidance, drafts, source notes, approved content) are synchronized using a private Git repository or a trusted file-sync tool.
- Database exports/snapshots are backed up separately. A future sync/import mechanism can merge selected records safely.
- Each machine keeps a local working copy and local backup.
- Keep at least one additional encrypted backup on an external drive, disconnected when not in use.

Do not enable synchronization until the chosen method and conflict rules have been tested. Never synchronize provider secrets.

## Quick start

1. Copy this folder to the intended location on each computer.
2. Read `workflows/IMPLEMENTATION_PLAN.md`.
3. Review `brand/BRAND_GUIDE.md` and `strategy/CONTENT_STRATEGY.md`.
4. Configure providers using `config/providers.example.json`; keep real secrets in environment variables or an OS credential store.
5. Use `prompts/` and `workflows/` manually before automating.
6. Do not connect publishing accounts until the approval and audit trail are implemented and tested.

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
- `backups/` — backup instructions and manifests; not a substitute for an external backup
- `logs/` — non-secret operational logs
- `app/` — future local dashboard
- `scripts/` — portable setup and maintenance scripts

## Features & Architecture

JustMeMedia ContentOS is a zero-dependency, local-first content operations system running on Python standard library only.

### Dual-Host Support
- **M1 Pro Mac:** Interactive 3-column AI Studio & Visual Publishing Hub at `http://127.0.0.1:8765`
- **ThinkCentre (Windows):** Background worker daemon (`app/worker.py`) scanning RSS, validating claims, queueing drafts 24/7 without cloud lock-in.

### Multimodal Engine Capabilities
- **Phase A — Omni-Platform Repurposing & Funnel Engine:** 1 article / headline instantly generates tailored content across 4 platforms: **LinkedIn** (executive thought leadership with automatic markdown asterisk cleanup), **X Thread** (punchy hook + numbered thread), **YouTube Hub** (full comprehensive script/brief up to 5,000 chars with verified resource library), and **Facebook Guide** (long-form narrative).
- **Phase B — Anti-Slop & Viral Hook Library:** Automatically detects and strips AI corporate buzzwords (delve, leverage, synergize, holistic, etc.) and injects high-performing viral hook structures.
- **Phase C — Local Image Studio (macOS) / GIF fallback (Windows):** On macOS, direct integration with Draw Things (`http://127.0.0.1:7860`) generates photorealistic AI artwork on Apple Silicon GPUs into local media storage (`~/Desktop/ContentOS Media`) with 1-click Finder reveal. On Windows, Draw Things is disabled by default (`IMAGE_BACKEND=none`) and the pipeline attaches a relevant GIF instead. Windows GPU users can set `IMAGE_BACKEND=a1111` to use Forge / AUTOMATIC1111 / SD.Next.
- **Phase D — Visual Carousel Slide Preview:** Splits long-form articles into structured carousel slides with real-time dark/green aesthetic slide previews.
- **Phase E — Webhook Dispatcher & Scheduled Reminders:** One-click instant dispatch of approved drafts to Discord, Slack, or custom automation endpoints. Includes background daemon monitoring scheduled publication slots with native macOS desktop notifications.
- **Agent 0 — Deep Research & Link Extraction:** Automatically navigates source URLs, follows sub-documentation, guides, and application pages, assembling a verified resource link library right inside your drafts.
- **1-Click Live Progress Modal:** Real-time visual pipeline showing exact step-by-step progress (`[1/4] Scraping...`, `[2/4] Drafting...`, `[3/4] Media...`, `[4/4] Scheduling...`) with direct one-click copy & launch into LinkedIn or X.

### Quick Start
```bash
# Start server
cd app && python3 server.py

# Run test suite (25/25 passing)
PYTHONPATH=. python3 -B -m unittest -v tests/test_server.py
```
