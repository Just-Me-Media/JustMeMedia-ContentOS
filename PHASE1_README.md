# ContentOS Phase 1 implementation

This is the first runnable local application layer. It uses only Python's standard
library and binds to `127.0.0.1` (localhost only).

## Install

Copy the `app/server.py` file into the existing project's `app/` folder and copy
the scripts into the existing `scripts/` folder. Alternatively, extract this
package over the existing project, preserving existing files.

## Run on Windows

From the project root in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_windows.ps1
```

Or run directly:

```powershell
python .\app\server.py
```

## Run on macOS

From Terminal:

```bash
bash ./scripts/run_mac.sh
```

Or run directly:

```bash
python3 ./app/server.py
```

Then open http://127.0.0.1:8765 in a browser. Stop the server with Ctrl+C.

## Database locations

- Windows: `%LOCALAPPDATA%\JustMeMedia\ContentOS\contentos.db`
- macOS: `~/Library/Application Support/JustMeMedia/ContentOS/contentos.db`

These databases are intentionally outside the project folder and must not be
placed in OneDrive, iCloud Drive, Dropbox, Git, or a shared network folder.

## Current scope and limitations

- Create and list local content drafts.
- Export drafts as JSON from the browser.
- Check whether the local Ollama API responds and list installed model names.
- No publishing, scheduling, external network listener, cloud AI calls, or account
  access is implemented.
- This is a foundation build, not the completed ContentOS product.
