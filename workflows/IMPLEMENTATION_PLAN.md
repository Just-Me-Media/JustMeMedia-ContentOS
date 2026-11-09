# ContentOS implementation plan

## Phase 0 — Foundation (current)
- [x] Create portable folder structure.
- [x] Document brand, strategy and operating rules.
- [x] Create provider-neutral prompt templates.
- [x] Define dual-host/local-database approach.
- [ ] Confirm the actual local installation path on both machines.
- [ ] Choose and test private synchronization method.
- [ ] Choose external encrypted backup destination and retention policy.

## Phase 1 — Local data layer
- [ ] Implement SQLite schema and migrations.
- [ ] Create content, research source, claim, approval, provider-run and analytics records.
- [ ] Add import/export to JSON and Markdown.
- [ ] Add backup/restore verification.
- Acceptance: create a content item offline, close the app, reopen it, export it, restore it into a test database.

## Phase 2 — Provider adapters
- [ ] Implement Ollama adapter for ThinkCentre.
- [ ] Implement Ollama adapter for Mac.
- [ ] Add provider health/capability discovery.
- [ ] Add optional cloud API adapters.
- [ ] Keep credentials outside project files and logs.
- Acceptance: switch models without changing workflow prompts or losing job history; demonstrate offline operation.

## Phase 3 — Research pipeline
- [ ] Define research-provider interface.
- [ ] Add web search/source retrieval adapter(s).
- [ ] Store source metadata and claim-to-source links.
- [ ] Add freshness and citation checks.
- Acceptance: every factual post claim can be traced to a stored source; unavailable web access is clearly reported.

## Phase 4 — Production workflow and Roundtable
- [ ] Research brief generation.
- [ ] Draft generation and platform adaptation.
- [ ] Independent review/challenge/synthesis.
- [ ] Asset brief and image prompt generation.
- [ ] Version history and editorial status.
- Acceptance: generate one weekly package from stored sources and preserve every model's contribution.

## Phase 5 — Local dashboard
- [ ] Content calendar and editorial queue.
- [ ] Research/source browser.
- [ ] Draft editor and comparison view.
- [ ] Approval/rejection controls.
- [ ] Provider selector and run history.
- [ ] Backup and export status.
- Acceptance: all essential operations work without a cloud model or ChatGPT.

## Phase 6 — Publishing and analytics
- [ ] Audit official APIs/connectors for each platform.
- [ ] Implement platform adapters only where permitted and stable.
- [ ] Require specific post/account/action approval.
- [ ] Add duplicate prevention, retry handling and audit log.
- [ ] Import performance metrics and report trends.
- Acceptance: no external action occurs without explicit approval; failures are visible and recoverable.

## Phase 7 — Resilience and handoff
- [ ] Install and test on both Windows and macOS.
- [ ] Test one machine unavailable while the other continues.
- [ ] Test provider outage and no-internet mode.
- [ ] Test encrypted backup restore on a clean location.
- [ ] Document startup, shutdown, upgrade and recovery.
- Acceptance: user can operate the system without ChatGPT and recover from a machine failure.

## Recommended build order
Build Phase 1 before the dashboard. Build the provider interface before adding multiple models. Build approvals before publishing. Do not add complexity until each phase has a testable acceptance result.
