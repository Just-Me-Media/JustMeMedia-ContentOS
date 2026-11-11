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


#### 🔍 Instant Topic Chips & Live Keyword Filtering
Right above your story list in Column 1, you have:
* **One-Click Topic Chips:** `🌐 All`, `🤖 AI`, `🍎 Apple`, `🔵 Google`, `OpenAI`, `Anthropic`, `DeepSeek`, `xAI/Grok`, `💻 Dev`. Click any chip to instantly isolate those stories.
* **Instant Keyword Filter Bar:** Type any term (e.g., `Siri`, `Vision`, `agent`) to filter stories in real-time as you type.

#### 📱 Free Mobile Push Notifications (ntfy.sh)
Want your phone to buzz the second your post finishes drafting or when its posting slot arrives?
1. Download the free **ntfy** app from the iOS App Store or Google Play Store (zero login/account required).
2. Choose a topic name (e.g. `justme-contentos-alerts`) and subscribe in the app.
3. In ContentOS, open the **Webhooks & Notifications** drawer in Column 3.
4. Type your topic name into the **Phone Push Notification** box and click **Test Alert**.
5. Your phone will instantly receive notifications with priority badges and action previews!

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

**🍎 Apple (Official)**
- `Apple Developer News` — Direct from Apple Developer Relations (your source!)
- `Apple Newsroom` — Apple's official press releases and announcements

**🔵 Google (Official)**
- `Google AI Blog` — Official Google AI research & product updates
- `Google The Keyword` — Google's official company news blog

**🤖 AI Labs**
- `OpenAI News` — Official OpenAI announcements & research
- `Anthropic` — via TechCrunch tag feed (Claude, Constitutional AI, safety)
- `DeepSeek` — via TechCrunch tag feed
- `xAI / Grok` — via TechCrunch tag feed (Elon Musk's AI lab)
- `Meta AI` — via TechCrunch tag feed (Llama, Horizon)
- `Microsoft AI` — via TechCrunch tag feed (Copilot, Azure OpenAI)

**📰 Tech & AI News**
- `Hacker News Top Stories` / `Hacker News Frontpage`
- `Ars Technica Tech & AI`
- `MIT Technology Review AI`
- `TechCrunch AI`
- `NYT Technology News`

> [!TIP] ContentOS defaults to **Apple Developer News** on launch. Switch to any source with one click from the dropdown, or paste any custom RSS/Atom URL and hit **Load**.

1. **Select a Verified Feed** from the grouped dropdown.
2. **Or Add a Custom RSS Feed:** Paste any RSS or Atom feed URL into the custom input and click **Load**.
3. **Step-by-Step Deep-Read & Draft:** Click **⚡ Deep-Read & Draft** on any card to load the story into Column 2 for manual editing before generating.
4. **Autonomous Batch Intake (Autopilot):** Want 3 posts drafted simultaneously? Click **⚡ Draft Top 3 Stories** under Autopilot Batch.

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

### Step 4: Omni-Platform Repurposing & Funnel Engine (LinkedIn, X, YouTube, Facebook)

Never write for just one platform when you can orchestrate an entire omni-channel funnel at once:

1. Under the post editor, locate the purple **🚀 Omni-Platform Repurposing** box.
2. Click **Generate All Platforms**.
3. In a single parallel run, ContentOS generates:
   - **LinkedIn:** Executive thought-leadership post with automatic markdown formatting (clean headers, zero raw asterisks, verified links, strategic CTA).
   - **X Thread:** Punchy 280-char maximum hook or numbered thread (`1/N`) driving curiosity back to your main hubs.
   - **YouTube Hub:** Full comprehensive video script & description (up to 5,000 characters) featuring video title variations, 15-second opening hook, detailed chapter breakdown, and full verified resource library.
   - **Facebook Guide:** Long-form conversational narrative post with headers, complete link library, and community discussion question.
4. Click between the tabs (**LinkedIn**, **X Thread**, **YouTube Hub**, **Facebook Guide**) to inspect each variation.
5. Click **Load LinkedIn** or **Load X** to bring that version directly into the primary editor.
6. Or click **💾 Save All 4 Drafts** to immediately commit all 4 tailored versions into your approval queue with optimal scheduled slots across your week.

---

### Step 5: Agent 0 Deep Research & Verified Link Extraction

ContentOS features a built-in **Agent 0: Deep Research Engine**:
- When extracting news (e.g. Apple Developer, OpenAI, Google AI), Agent 0 doesn't just read the surface headline; it parses out all secondary links inside the source article (application portals, GitHub starter repos, API documentation, registration hubs).
- It performs a shallow scrape on top linked resources to understand prerequisite dates, eligibility criteria, and technical submission guidelines.
- It synthesizes a complete **360° Research Dossier** with live verified links embedded directly into the draft, so your readers get actionable links to learn more or apply immediately.

---

### Step 6: Visual Carousel Preview & Thread Splitting

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
* Click **🖼️ Draw Things (Local AI)** or use the 1-Click pipeline.
* Your Mac GPU renders a high-resolution 1024x576 PNG image directly into your local media vault (`~/Library/Application Support/JustMeMedia/ContentOS/media/`).
* **Desktop Access:** ContentOS creates an alias directly on your Mac desktop: `~/Desktop/ContentOS Media`. You can drag-and-drop generated images directly from your desktop into LinkedIn or X.
* **Finder Reveal Button:** Every draft card with an image has a **📂 Reveal Image in Finder** button. Click it to immediately highlight the exact `.png` file in macOS Finder!

#### 3. Multimodal GIF Search
* Type keywords into the **Media Studio & GIF Search** bar (e.g. `coding`, `mind blown`, `cyberpunk`, `tech`).
* Click **Find**.
* Click any GIF to instantly attach its high-resolution URL to your draft.

---

### Step 8: Human Approval State Machine & Optimal Scheduling

Once your post, media, and visual prompts are ready:

1. Click **💾 Save Draft** (or let 1-Click Pipeline stage it automatically).
2. The draft is assigned a unique ID, stamped with a timestamp, assigned to the next optimal social slot (`09:00`, `14:00`, or `18:30`), and stored in the local SQLite database.
3. The post appears in Column 3 (**Approval & Publishing Hub**).
4. Review the draft card:
   * **⚡ READY TO PUBLISH Launch Bar:** Located right at the top of every card. One click on `🚀 Launch to LinkedIn ↗` or `🚀 Launch to X ↗` automatically copies the post to your clipboard and opens the platform composer in a new tab!
   * **Automatic LinkedIn Markdown Formatting:** For LinkedIn posts, ContentOS automatically cleans away raw markdown `**bold**` asterisks and transforms headers into clean, native text titles (`Key Dates:` instead of `**Key Dates**`) so your post looks 100% human-crafted and professional.
   * **Status Pill:** Defaults to `DRAFT` (grey), changes to `APPROVED` (green) or `PUBLISHED` (blue).
   * **Action Buttons:**
     * **📋 Copy Text:** Copies formatted text to your clipboard.
     * **📥 Export .MD:** Downloads a standalone `.md` file with YAML frontmatter.
     * **✅ Approve:** Promotes status from `Draft` to `APPROVED` (green) and records an audit log entry in the `approvals` table.
     * **🔔 Notify:** Sends post to Discord or Slack webhooks.
     * **Delete:** Permanently deletes the draft.

---

### Step 9: Publishing to Your Social Platforms (Desktop-to-Browser Drag & Drop)

Once approved, publishing takes under 5 seconds:
1. On the draft card, click `🚀 Launch to LinkedIn ↗` or `🚀 Launch to X ↗`.
2. ContentOS automatically cleans formatting, copies the post text to your clipboard, marks the post published in the database, and opens the social feed in a new browser tab.
3. In LinkedIn or X, click the composer box and paste (`Cmd+V`).
4. To add your visual: open the `ContentOS Media` folder on your desktop, and drag the `.png` right into the composer window for full-bleed high-resolution media!
5. Hit **Post**!

---

### Step 10: Background Scheduled Reminder Daemon

ContentOS includes an autonomous background scheduler daemon:
* Checks drafts every 30 seconds against current time.
* When a draft's scheduled slot arrives, ContentOS sends a **native macOS Desktop notification banner** with sound: `⏰ Time to publish '<Title>' on LinkedIn! Open ContentOS to publish!`.
* If configured, it also fires webhook alerts to Discord/Slack so your whole team knows when content is ready to post.

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
All **37/37 unit tests** will execute and verify database schema, security headers, anti-slop filters, viral hooks, thread formatters, carousel generators, webhook builders, Deep Research dossiers, and LinkedIn markdown formatters.

---

*Manual maintained by JustMeMedia. For technical questions or codebase updates, refer to `README.md` and `SECURITY.md`.*

