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

## Initial status

This is a documentation and data scaffold, not a finished application. No live social accounts, model endpoints, credentials, publishing integrations, or synchronization are connected yet.
