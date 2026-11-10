# JustMeMedia ContentOS — Complete User Manual
**Local-First Content Engine & Multimodal Publishing Studio**

---

## Table of Contents
1. [Overview & Philosophy](#1-overview--philosophy)
2. [Prerequisites & System Requirements](#2-prerequisites--system-requirements)
3. [Quick Start: Launching ContentOS](#3-quick-start-launching-contentos)
4. [Step-by-Step Walkthrough: From Discovery to Published Post](#4-step-by-step-walkthrough-from-discovery-to-published-post)
   - [Step 1: Content Discovery & Trend Intake](#step-1-content-discovery--trend-intake)
   - [Step 2: Choosing Your AI Model & Editorial Persona](#step-2-choosing-your-ai-model--editorial-persona)
   - [Step 3: Drafting & Content Engine](#step-3-drafting--content-engine)
   - [Step 4: Omni-Platform Repurposing (LinkedIn, X, YouTube)](#step-4-omni-platform-repurposing-linkedin-x-youtube)
   - [Step 5: Visual Carousel Preview & Thread Splitting](#step-5-visual-carousel-preview--thread-splitting)
   - [Step 6: Media Studio & Artwork Generation](#step-6-media-studio--artwork-generation)
   - [Step 7: Human Approval State Machine](#step-7-human-approval-state-machine)
   - [Step 8: Publishing to Your Social Platforms](#step-8-publishing-to-your-social-platforms)
   - [Step 9: Webhook Dispatch (Discord, Slack, n8n, Make)](#step-9-webhook-dispatch-discord-slack-n8n-make)
   - [Step 10: Markdown & JSON Backups / Exports](#step-10-markdown--json-backups--exports)
5. [Dual-Computer Operating Model (M1 Pro Mac + ThinkCentre)](#5-dual-computer-operating-model)
6. [Configuration & API Keys](#6-configuration--api-keys)
7. [Frequently Asked Questions (FAQ) & Troubleshooting](#7-frequently-asked-questions-faq--troubleshooting)

---

## 1. Overview & Philosophy

**JustMeMedia ContentOS** is a zero-dependency, local-first content operating system built for independent creators, media businesses, and software teams.

### Core Principles
- **User Ownership:** All drafts, sources, prompts, and database records remain on your local computer. Nothing is stored in third-party clouds or proprietary silos.
- **Zero Third-Party Pip Dependencies:** The entire backend runs purely on Python standard library modules (`sqlite3`, `http.server`, `urllib`, `json`, `re`, `xml.etree`). No broken virtual environments, dependency conflicts, or library bloat.
- **Provider Independence:** Switch seamlessly between zero-cost ultra-fast cloud models (Groq, Google Gemini) and 100% offline local models (Ollama, Draw Things). If any one service goes down, your system continues uninterrupted.
- **Human-in-the-Loop Safeguard:** ContentOS enforces an explicit approval state machine (`Draft` ➔ `Approved` ➔ `Published`). The software will **never** silently post to external social accounts without human confirmation.

---

## 2. Prerequisites & System Requirements

### Hardware
* **Primary Mac (M1 Pro / Apple Silicon):** Runs the interactive browser dashboard, multimodal editing studio, and local image generation.
* **Secondary PC (Windows ThinkCentre):** Runs the standalone 24/7 background worker daemon that continuously scans feeds and queues drafts.

### Software
* **Python 3.10 or newer** (Pre-installed on macOS; standard installer on Windows).
* **Modern Web Browser** (Google Chrome, Brave, Safari, Edge, Firefox).

### Optional AI Providers
ContentOS works in full manual mode with zero APIs. To enable automated AI drafting and visual creation, you can connect any of the following:

| Provider | Purpose | Cost | Where to Get |
|---|---|---|---|
| **Groq Cloud** | High-speed cloud text generation (300+ tokens/sec) | Free Tier available | [console.groq.com](https://console.groq.com) |
| **Google Gemini Flash** | Cloud multimodal reasoning | Free Tier available | [aistudio.google.com](https://aistudio.google.com) |
| **Ollama** | 100% offline local LLMs | Free / Open Source | [ollama.com](https://ollama.com) |
| **Draw Things** | 100% offline local FLUX/Stable Diffusion images on Mac | Free Mac App Store | [drawthings.ai](https://drawthings.ai) |

---

## 3. Quick Start: Launching ContentOS

### Launching on macOS (Interactive Studio)

1. Open your terminal and navigate to the project directory:
   ```bash
   cd ~/Desktop/JUST_ME_MEDIA_VAULT/02_ACTIVE_PROJECTS/JustMeMedia_ContentOS/JustMeMedia_ContentOS
   ```
2. Start the ContentOS server:
   ```bash
   python3 ./app/server.py
   ```
3. Open your browser and navigate to:
   ```text
   http://127.0.0.1:8765
   ```
4. You will see the dark-themed, 3-column ContentOS Studio interface.

### Launching on Windows (ThinkCentre 24/7 Background Daemon)

To run the autonomous ingest worker on your Windows machine:
```cmd
cd %USERPROFILE%\Desktop\JustMeMedia_ContentOS
python app\worker.py --daemon
```
The worker scans feeds periodically, performs duplicate checks against the local database, drafts candidates, and queues them for your review.

---

## 4. Step-by-Step Walkthrough: From Discovery to Published Post

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   1. DISCOVERY   │ ──> │   2. AI ENGINE   │ ──> │   3. STAGING     │ ──> │   4. PUBLISHING  │
│  RSS Feeds / URL │     │ 4-Agent Pipeline │     │  Human Approval  │     │ Webhooks / Social│
└──────────────────┘     └──────────────────┘     └──────────────────┘     └──────────────────┘
```

---

### Step 1: Content Discovery & Trend Intake (Or The 1-Click "Make Tea" Pipeline)

Column 1 (**Content Discovery**) surfaces live news, trends, and stories to spark high-signal posts.

#### ☕ The "Wake Up & Make Tea" 1-Click Pipeline (Fastest Workflow)
1. In the morning, open `http://127.0.0.1:8765`.
2. Browse the stories in Column 1 and find one that interests you.
3. Click the green **`✨ 1-Click Create & Stage`** button on that story.
4. **Walk away and make a cup of tea!** In the background, ContentOS will:
   - Scrape the full article text and strip navigation/ads.
   - Run the 4-Agent Roundtable (Drafter, Fact-Checker, Hook Optimizer, Anti-Slop Filter).
   - Generate local visual art via Draw Things (or fetch an aesthetic high-relevance GIF if Draw Things is offline).
   - Automatically assign the post to the next optimal publishing slot (`09:00`, `14:00`, or `18:30`).
   - Save to the local database, load it into your editor, and play a gentle completion chime.
5. Review the post in Column 3, make any tweaks if you wish, and click **`🚀 Copy & Launch LinkedIn ↗`** or **`🚀 Copy & Launch X ↗`**.

#### ⚡ Manual & Step-by-Step Discovery Options:
1. **Select a Curated Feed:**
   * **Hacker News Top Stories** (Engineering, startups, tech breakthroughs)
   * **NYT Technology News** (Mainstream industry news)
   * **Ars Technica Tech & AI** (In-depth analysis and computing)
2. **Or Add a Custom RSS Feed:**
   * Paste any RSS or Atom feed URL into the input box and click **Load**.
3. **Step-by-Step Deep-Read & Draft:**
   * Click **⚡ Deep-Read & Draft** on any card to load the story into Column 2 for manual editing before generating.
4. **Autonomous Batch Intake (Autopilot):**
   * Want 3 posts drafted simultaneously? Click **⚡ Draft Top 3 Stories** under Autopilot Batch.

---

### Step 2: Choosing Your AI Model & Editorial Persona

In Column 2 (**Content Engine & AI Studio**), configure how the content is written:

1. **Select Intelligence Provider:**
   * **⚡ Groq Cloud: GPT-OSS 120B** (Recommended — ultra-fast, frontier quality, generates in ~1.5s)
   * **⚡ Groq Cloud: Qwen 3.8 27B** (High speed)
   * **✨ Google Gemini Flash** (Cloud intelligence)
   * **🖥️ Local Ollama** (100% offline local model on your Mac)
2. **Select Target Platform:**
   * `LinkedIn` — Formatted with spacing, bullet points, CTA, and relevant hashtags.
   * `X (Twitter)` — Tight 280-character maximum hook or thread format.
   * `Instagram/Threads` — Narrative story format with visual pacing.
   * `YouTube Brief` — Video title concepts, opening hook, and 2-paragraph description.
   * `General` — Markdown structured document.
3. **Select Editorial Tone / Persona:**
   * **🎯 Thought Leadership:** Authoritative, strategic, data-informed industry insights.
   * **⚡ Viral & Punchy:** Narrative hook, strong pattern interrupt, punchy 1-line pacing.
   * **🛠️ Deep Technical:** Engineering rigor, architectural trade-offs, code-level precision.
   * **🔥 Contrarian / Hot Take:** Direct challenge to conventional wisdom with reasoned defense.

---

### Step 3: Drafting & Content Engine

ContentOS includes two generation modes:

#### Mode A: 🤖 Roundtable Consensus Mode (3-4 Agents)
Check the box for **Roundtable Mode (3 Agents)** and click **⚡ Generate Post**:
1. **Agent 1 (The Drafter):** Produces the initial post draft tailored to your chosen tone and platform.
2. **Agent 2 (The Fact-Checker):** Compares claims against the source facts, eliminates hallucinations, and flags unsupported numbers.
3. **Agent 3 (The Hook Optimizer):** Refines the opener for maximum attention, formats double line-breaks, and adds engaging discussion questions.
4. **Phase B Anti-Slop Filter:** Automatically cleans corporate AI clichés (*"delve"*, *"leverage"*, *"in today's fast-paced world"*, *"transformative"*, *"paradigm"*) and injects proven viral hook structures.

#### Mode B: Fast Single-Pass Generation
Uncheck Roundtable Mode for a direct, rapid 1-shot generation.

---

### Step 4: Omni-Platform Repurposing (LinkedIn, X, YouTube)

Never write for just one platform when you can write for all three at once:

1. Under the post editor, locate the purple **🚀 Omni-Platform Repurposing** box.
2. Click **Generate All Platforms**.
3. In a single parallel run, ContentOS generates:
   - A tailored **LinkedIn** thought-leadership post
   - An **X Thread** (numbered breakdown)
   - A **YouTube Brief** (title + video script/description)
4. Click between the tabs (**LinkedIn**, **X Thread**, **YouTube**) to inspect each variation.
5. Click **Load LinkedIn** or **Load X** to bring that version directly into the primary editor.
6. Or click **💾 Save All 3 Drafts** to immediately commit all 3 tailored versions into your approval queue with one click.

---

### Step 5: Visual Carousel Preview & Thread Splitting

#### For LinkedIn & Instagram (Carousels)
1. Write or generate your long-form post.
2. Click **📑 Split Carousel**.
3. ContentOS splits your post into numbered slides with headline and body cards.
4. The **📑 Carousel Slide Preview** renders in real-time right in your browser with dark obsidian background and emerald accents, allowing you to preview exactly how the slides will look before designing.

#### For X (Twitter Threads)
1. Click **🧵 Split X Thread**.
2. ContentOS calculates tweet character budgets and formats your post into numbered tweets (`1/N`, `2/N`, `3/N`).

---

### Step 6: Media Studio & Artwork Generation

Every great post needs compelling visuals. ContentOS gives you three ways to attach media:

#### 1. AI Artwork Prompt Brief
* Click **🎨 Suggest Image Prompt**.
* The AI Art Director creates a photorealistic prompt tailored for Midjourney, FLUX, Gemini, or Grok using JustMeMedia brand aesthetics (dark obsidian, emerald green accents, minimalist tech).
* Click **Copy Prompt** to paste into your image generator.

#### 2. Local Draw Things Generation (100% Offline AI Art)
* If you have the free **Draw Things** app installed on Mac:
* Make sure Draw Things has its API enabled (**Draw Things > Settings > API Server > Enable HTTP Server on port 7860**).
* ContentOS will display `🟢 Draw Things Online (127.0.0.1:7860)`.
* Click **🖼️ Draw Things (Local AI)**.
* Your M1 Pro chip renders a high-resolution PNG image directly into your local media vault (`~/.justmemedia/contentos/media/`).
* Click **📎 Attach to Draft** to bind the image to your post.

#### 3. Multimodal GIF Search
* Type keywords into the **Media Studio & GIF Search** bar (e.g. `coding`, `mind blown`, `cyberpunk`, `tech`).
* Click **Find**.
* Click any GIF to instantly attach its high-resolution URL to your draft.

---

### Step 7: Human Approval State Machine

Once your post, media, and visual prompts are ready:

1. Click **💾 Save Draft**.
2. The draft is assigned a unique ID, stamped with a timestamp, and stored in the local SQLite database.
3. The post appears in Column 3 (**Approval & Publishing Hub**).
4. Review the draft card:
   * **Status Pill:** Defaults to `DRAFT` (grey).
   * **Action Buttons:**
     * **📋 Copy Post:** Copies formatted text to your clipboard.
     * **📥 Export .MD:** Downloads a standalone `.md` file with YAML frontmatter.
     * **✅ Approve:** Promotes status from `Draft` to `APPROVED` (green) and records an audit log entry in the `approvals` table.
     * **Delete:** Permanently deletes the draft.

---

### Step 8: Publishing to Your Social Platforms

Once approved, publishing is seamless and human-supervised:

#### Manual Browser Publishing (One-Click Launchers)
1. Click **📋 Copy Post** on the approved draft card.
2. Click **Open LinkedIn ↗** or **Open X Composer ↗**.
3. ContentOS opens your native social feed composer in a new tab.
4. Paste (`Cmd+V` or `Ctrl+V`), attach your saved image/GIF, and hit Publish!
5. Back in ContentOS, click **🚀 Mark Published** to move the status pill to `PUBLISHED` (blue).

---

### Step 9: Webhook Dispatch (Discord, Slack, n8n, Make)

If your workflow uses team channels or automated publishing pipelines:

1. In Column 3, click **⚙️ Webhooks**.
2. Enter your webhook URLs:
   * **Discord Webhook:** Posts rich embedded cards with titles, platform tags, full body text, and artwork briefs into your Discord content channels.
   * **Slack Webhook:** Posts formatted Slack Block Kit messages.
   * **Custom Webhook:** Sends complete JSON payloads to **n8n**, **Make**, or **Zapier** workflows.
3. Click **Save Webhook URLs**.
4. Test delivery by clicking **Test**.
5. To dispatch any draft, click **🔔 Notify** on its card and select your target. The draft is delivered in under 1 second.

---

### Step 10: Markdown & JSON Backups / Exports

To protect against platform lock-in or backup your content vault:

* **Export Single Draft:** Click **📥 Export .MD** on any draft card to download:
  ```markdown
  ---
  title: "Why Local-First Software is the Future"
  platform: "LinkedIn"
  status: "Approved"
  created_at: "2026-11-10T05:00:00"
  ---

  # Why Local-First Software is the Future
  [Full Post Content]

  ---
  ### Visual Prompt Brief
  Photorealistic minimal tech art representing local software...
  ```
* **Export All Drafts (Markdown):** Click **Export All Markdown** in the top navigation bar to download your entire library in a single consolidated Markdown file.
* **Export All Drafts (JSON):** Click **Export JSON** in the top navigation bar to download full structured records with claim IDs, source URLs, media attachments, and approval metadata.

---

## 5. Dual-Computer Operating Model

ContentOS is engineered for dual-host operation across your MacBook Pro and Windows ThinkCentre:

```
┌─────────────────────────────────┐         ┌─────────────────────────────────┐
│       M1 PRO MACBOOK PRO        │         │      WINDOWS THINKCENTRE        │
│    Interactive Studio Server    │         │      24/7 Intake Daemon         │
│  - Web UI (127.0.0.1:8765)      │         │  - python app/worker.py         │
│  - Human Review & Editing       │         │  - Continuous RSS Scanning      │
│  - One-Click Social Launchers   │         │  - Auto-Draft Queueing          │
│  - Draw Things Local AI Art     │         │  - Headless Background Work     │
└─────────────────────────────────┘         └─────────────────────────────────┘
                 │                                           │
                 └─────────────── [ Git Repo ] ──────────────┘
                           (Code & Workflows Sync)
```

### Safety Rules:
1. **Never share the same SQLite database file over a network folder or Dropbox.** SQLite is an embedded single-machine database. Each computer keeps its own local database.
2. **Synchronize Code & Workflows via Git:** Use `git pull` and `git push origin main` to synchronize scripts, prompts, brand guidelines, and features between both computers.
3. **Database Portability:** Use **Export JSON** or **Export All Markdown** to move content libraries between machines safely.

---

## 6. Configuration & API Keys

All configuration is local-first. Credentials are auto-loaded from your shell environment and **never committed to Git**.

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `GROQ_API_KEY` | Groq Cloud API Key (`gsk_...`) | Loaded from `~/.zshrc` or system env |
| `GEMINI_API_KEY` | Google Gemini API Key | Loaded from `~/.zshrc` or system env |
| `CONTENTOS_PORT` | HTTP Server Port | `8765` |
| `DRAW_THINGS_URL` | Local Draw Things API endpoint | `http://127.0.0.1:7860` |
| `OLLAMA_BASE_URL` | Local Ollama API endpoint | `http://127.0.0.1:11434` |

### Setting Environment Variables

#### On macOS (`~/.zshrc`):
```bash
export GROQ_API_KEY="gsk_your_groq_key_here"
export GEMINI_API_KEY="your_gemini_key_here"
```
Reload with: `source ~/.zshrc`.

#### On Windows (PowerShell):
```powershell
[System.Environment]::SetEnvironmentVariable('GROQ_API_KEY', 'gsk_your_groq_key_here', 'User')
```

---

## 7. Frequently Asked Questions (FAQ) & Troubleshooting

### Q1: Can I use ContentOS 100% offline without any internet connection?
**Yes.** ContentOS has zero external pip dependencies and can run completely disconnected. When offline:
* Text generation can use **Local Ollama** (`127.0.0.1:11434`).
* Image generation can use **Draw Things** (`127.0.0.1:7860`).
* If external RSS feeds are unreachable, the intake engine automatically loads built-in offline seed stories so drafting never stops.
* The local SQLite database continues saving and serving drafts normally.

### Q2: What is Draw Things and do I have to use it?
**Draw Things is an optional local companion app.** It is a free, high-performance Mac application that runs Stable Diffusion and FLUX models directly on Apple Silicon GPUs/Neural Engines without cloud subscriptions.  
* If you do not use Draw Things, ContentOS still provides photorealistic text prompts you can copy into Midjourney or web generators, as well as full GIF search.
* To enable Draw Things: open the Draw Things app, go to **Settings > API Server**, and toggle on **Enable HTTP Server**. The badge in ContentOS will instantly turn `🟢 Draw Things Online`.

### Q3: Why did Groq return "Error 403: error code: 1010"?
Cloudflare protects Groq's API and blocks generic automated clients (like default Python `urllib` signatures). ContentOS includes an authentic browser User-Agent header and auto-rate-limit retry mechanism that resolves this issue permanently.

### Q4: Why did local Ollama generation time out?
Some local models (specifically models labeled "thinking" or models with parameter counts above 14B) take multiple minutes to produce reasoning traces before writing text. For rapid batch generation:
* Select **⚡ Groq Cloud: GPT-OSS 120B** for near-instant (1–2s) generation.
* If using Ollama, select lightweight non-thinking models (e.g. `llama3.2:latest`, `mistral:7b`, or `phi3:mini`). ContentOS automatically strips `<think>` tokens if a reasoning model is used.

### Q5: Does ContentOS post directly to my Twitter/LinkedIn accounts automatically?
**No.** By architectural design, ContentOS does not possess direct OAuth publishing tokens for social platforms. This prevents automated spam, unauthorized account actions, or accidental broadcasts. You retain final editorial control via the **One-Click Social Launchers** or your own **Webhook Dispatcher**.

### Q6: Where are my drafts and data stored on disk?
* **Database:** `~/.justmemedia/contentos/contentos.db` (or OS Application Support directory).
* **Media Assets:** `~/.justmemedia/contentos/media/`
* **Webhooks:** `~/.justmemedia/contentos/webhooks.json`

### Q7: How do I run the automated verification test suite?
Run the built-in test suite at any time from the project root:
```bash
PYTHONPATH=. python3 -B -m unittest -v tests/test_server.py
```
All **20/20 unit tests** will execute and verify database schema, security headers, anti-slop filters, viral hooks, thread formatters, carousel generators, and webhook builders.

---

*Manual maintained by JustMeMedia. For technical questions or codebase updates, refer to `README.md` and `SECURITY.md`.*

