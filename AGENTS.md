# Agent handoff and repository working rules

This file is the shared project handoff for OpenCode, Antigravity, and other coding agents working in this repository. Read it before making changes.

## Project snapshot

JustMeMedia ContentOS is a private, local-first content operations app. The backend is currently a Python standard-library application in `app/server.py`, with a background worker in `app/worker.py`, a SQLite data layer, and a browser UI served locally. The product goal is provider-independent content research and drafting, with human approval required before external publishing or other consequential actions.

The repository is actively evolving. Treat the current code and tests as the source of truth; older scaffold language in docs may not reflect the implemented app. If you notice a documentation/code mismatch, report it and propose a focused fix rather than silently making a broad rewrite.

## Before you change anything

1. Inspect the current branch, working tree, recent history, and relevant files. Do not assume another agent has not made changes since your last turn.
2. Read `README.md`, `SECURITY.md`, and the relevant code/tests before editing.
3. Keep the task focused. Avoid unrelated refactors, generated files, or wholesale rewrites of `app/server.py`.
4. Check for existing changes before staging or committing. Never overwrite or discard a human's or another agent's uncommitted work.

## Branch and collaboration rules

- Work on a clearly named feature/fix branch and open a pull request targeting `main`; do not commit directly to `main` unless the repository owner explicitly asks.
- Do not force-push, amend shared commits, reset branches, or delete branches unless explicitly authorized.
- Avoid overlapping edits with another agent. Coordinate ownership of files and communicate the files changed, decisions made, and checks run when handing work off.
- Keep commits small and descriptive. Prefer one focused change per PR.
- The GitHub Actions workflow at `.github/workflows/ci.yml` runs on PRs and pushes to `main`. Confirm it passes before asking for review or merge.

## Validation

- Run the full test suite from the repository root:

  ```bash
  PYTHONPATH=. python -B -m unittest discover -s tests -p 'test_*.py' -v
  ```

- Compile-check application and test code:

  ```bash
  python -m compileall -q app tests
  ```

- Add or update tests for behavior changes, especially API validation, persistence, approval flows, URL handling, and platform-specific behavior.
- Do not claim tests passed unless you actually ran them. If a check cannot run, say why and provide the exact command.

## Security and safety boundaries

- Never add real API keys, passwords, OAuth tokens, cookies, webhook URLs, private keys, or personal/customer data to Git, prompts, examples, logs, or test fixtures. Use placeholders in examples.
- Keep `.env`, local databases, generated media, backups, and credential files out of commits. Check `git status` and staged diffs before committing.
- Preserve localhost-only binding and request protections. Do not expose the app to a LAN or public network, weaken host/origin/CSRF checks, or add authentication bypasses.
- Treat user-supplied URLs, feed URLs, webhook destinations, and scraped page content as untrusted. Avoid introducing SSRF, unsafe HTML rendering, path traversal, or shell injection risks.
- AI output is untrusted input. Keep human approval as a mandatory gate for publishing, scheduling, sending messages, account changes, or spending. Do not implement silent auto-publishing.
- Do not run destructive commands, migrations against user data, account actions, or external publishing actions without explicit approval for that exact action.

## Handoff format

When handing work to the owner or another agent, include:

- Goal and summary of changes
- Files changed
- Tests/checks run and their outcomes
- Known limitations or follow-up work
- Any decisions or assumptions the next agent should know

## Current first priority

Use the CI checks as a safety net while working on the app. A green CI run verifies syntax and the existing unit suite, but it does not replace code review, security review, or testing on the target Mac/Windows hosts. Branch protection is not configured by this file; the repository owner should enable it in GitHub settings and require the CI check before merging if desired.
