# Automated Social Media Viral Monitoring & Video Generation Service Architecture

**Target OS:** Ubuntu Linux  
**AI Core:** Claude Subscription (utilizing `claude` CLI)  
**Execution Environment:** Local Systemd Service + Cloud APIs  

---

## Executive Summary

This document outlines the complete technical architecture and implementation guide for building an automated viral social media monitoring and content creation service on an Ubuntu Linux system. The system ingests top-performing viral content from Instagram and TikTok, extracts winning structural hooks using Claude via the CLI, synthesizes custom scripts for your product, renders videos locally using **Remotion**, routes each rendered item through a **mandatory human review gate** (approve, reject, or request changes via a local dashboard), and publishes only approved content via automated APIs or direct Python scripts.

---

## 1. System Architecture Diagram

```
[ Cron / Systemd Timer ]
          │
          ▼
┌─────────────────────────────────────────┐
│ 1. Trend Ingestion (Ubuntu / Python)    │
│    • Apify Scraper SDK                  │
│    • Filter viral threshold (>100k views) │
└───────────────────┬─────────────────────┘
                    │ Scraped JSON (video transcripts & engagement stats)
                    ▼
┌─────────────────────────────────────────┐
│ 2. Intelligence Layer (Claude CLI)      │◄──────────────┐
│    • Executed via local `claude` CLI    │                │
│    • Extract Hook / Viral Pattern       │                │ "Request Changes"
│    • Synthesize scripts & captions      │                │ feedback text
└───────────────────┬─────────────────────┘                │
                    │ Generated Script JSON & Asset Map     │
                    ▼                                       │
┌─────────────────────────────────────────┐                │
│ 3. Local Video Rendering (Remotion Node) │                │
│    • Local FFmpeg + Remotion SSR        │                │
│    • Stitch video background, audio & text│              │
└───────────────────┬─────────────────────┘                │
                    │ Rendered .MP4 + status='pending_review'│
                    ▼                                       │
┌─────────────────────────────────────────┐                │
│ 4. Human Review & Approval Gate         │────────────────┘
│    • Local Flask dashboard (localhost)  │
│    • Approve / Reject / Request Changes │
│    • Updates status in SQLite DB        │
└───────────────────┬─────────────────────┘
                    │ Only status='approved' items
                    ▼
┌─────────────────────────────────────────┐
│ 5. Distribution (Direct APIs / Python)  │
│    • POST via Meta Graph & TikTok APIs  │
│    • Log metrics to local SQLite DB     │
└───────────────────┬─────────────────────┘
```

**Note on automation:** Steps 1–3 (ingestion, script synthesis, rendering) can still run unattended on a systemd timer. Step 4 is a human checkpoint — nothing crosses into Step 5 without an explicit "Approve" from the dashboard, so a separate, decoupled publish timer polls the DB for approved items instead of publishing immediately after render. See [Section 8](#8-ubuntu-automation-via-systemd) for the split-timer setup.

---

## 2. Cost Analysis & Pricing Breakdown

To keep operational expenses minimal, external SaaS management platforms (like Ayrshare) have been replaced with direct, free Python integrations using official platform developer APIs.

| Component / Tool | License & Cost Type | Pricing / Monthly Cost | Notes & Optimization |
| :--- | :--- | :--- | :--- |
| **Ubuntu Linux OS** | Open-Source | **$0.00** | Native OS hosting (laptop or server). |
| **Claude AI (`claude` CLI)** | Subscription | **Included in Claude Pro/Team** (~$20/mo) | Uses your existing Claude subscription via local CLI; **no pay-as-you-go API costs**. |
| **Apify Scraper SDK** | Freemium SaaS | **$0.00 – $39.00 / month** | Includes **$5/month in free platform credits**. Light usage fits within free tier; high-volume daily scraping requires Starter tier ($39/mo). |
| **Remotion Node Engine** | Open-Source / Dual | **$0.00** | 100% Free for individuals, non-profits, and businesses with **up to 3 employees**. |
| **Social Publishing (Meta & TikTok APIs)** | Official APIs | **$0.00** | **Replaced Ayrshare with native Python scripts**. Meta Graph API and TikTok Content Posting API are completely free. |
| **Task Scheduling (Systemd/Cron)** | Native System Tool | **$0.00** | Built into Ubuntu OS. |
| **Database (SQLite)** | Open-Source | **$0.00** | Zero cost local embedded storage. |
| **Review Dashboard (Flask)** | Open-Source | **$0.00** | Local-only web UI (`localhost`), no hosting cost. |

**Total Estimated Running Cost:** **$0.00 to $39.00 / month** (depending on scraping volume).

---

## 3. Component Detailed Breakdown

### 3.1 Trend Ingestion (Apify / Scraper SDK)
Acts as the discovery engine by constantly monitoring external social platforms for high-performing content.
* **Target Scraping:** Periodically fetches top videos under targeted audio IDs, competitor handles, and niche hashtags across TikTok and Instagram.
* **Metric Filtering:** Evaluates metrics (views, likes, shares) against a dynamic virality threshold (e.g., videos exceeding 100k views or a top 5% view-to-follower ratio).
* **Asset Extraction:** Downloads audio tracks, extracts video transcripts via speech-to-text, and scrapes associated captions for processing.

### 3.2 Intelligence Layer (Claude CLI / AI Processing)
Acts as the central brain of the system, converting unstructured social data into structured video creative plans.
* **Hook & Structure Deconstruction:** Analyzes viral transcripts to isolate the 3-second psychological hook (e.g., contrarian statements, curiosity gaps) and structural pacing.
* **Script & Copy Synthesis:** Adapts the extracted viral format to match your product brief, generating a 15–30 second voiceover script, text overlays, and captions.
* **JSON Output Formatting:** Structures all creative decisions (voiceover lines, on-screen text timings, scene cut rules) into standardized JSON for downstream automation.

### 3.3 Local Video Rendering (Remotion Node)
Acts as the assembly engine, programmatically building production-ready `.mp4` video files from code.
* **Template Parameterization:** Feeds the structured JSON data into React templates defining layout, typography, and visual assets.
* **Asset Composition & Styling:** Layers background videos/images, renders animated text overlays with CSS, and syncs voiceover audio tracks.
* **Frame-by-Frame Stitching:** Uses a local FFmpeg pipeline to evaluate React components frame-by-frame (e.g., 30 FPS) and compile the final high-definition MP4.

### 3.4 Human Review & Approval Gate (Flask Dashboard)
Acts as the mandatory checkpoint between rendering and publishing — nothing is posted without explicit sign-off.
* **Pending Queue:** After rendering, each item (script JSON, caption, hashtags, and the rendered `.mp4`) is written to SQLite with `status = 'pending_review'` instead of being sent straight to distribution.
* **Local Review UI:** A lightweight Flask app running on `localhost` lists pending items, plays the rendered video inline, and shows the generated hook/script/caption text.
* **Three Actions:** For each item you can **Approve** (flips status to `approved`, eligible for the next publish cycle), **Reject** (flips to `rejected`, archived and excluded from publishing), or **Request Changes** (you type free-text feedback, e.g. "make the hook punchier" or "shorter caption" — this is stored and fed back into the Intelligence Layer, which regenerates the script using the original transcript/product brief *plus* your feedback, then re-renders automatically and lands back in the queue as `pending_review`).
* **No Bypass:** The publish step (3.5) only ever queries for `status = 'approved'`, so unattended cron/timer runs cannot post anything that hasn't been manually approved.

### 3.5 Direct Distribution & Persistence (Native Python + SQLite)
Handles post scheduling, direct API publishing, and local audit logging without third-party SaaS fees.
* **Direct Python API Publishing:** Posts generated `.mp4` files, captions, and hashtags directly using custom Python modules interacting with Meta Graph API (Instagram Reels) and TikTok API. Only queries rows where `status = 'approved'`.
* **State & Audit Logging:** Records posted video IDs, original source URLs, review decisions, and execution timestamps into a local SQLite database to prevent duplicate posting.
* **Analytics Tracking:** Periodically queries post performance to feed engagement feedback back into the ingestion system.

### 3.6 Task Scheduler (Systemd Timers / Cron)
Serves as the background orchestrator on Ubuntu.
* **Automated Intervals:** Triggers the Python pipeline script on a set cron schedule (e.g., every 6 hours).
* **Resource Control:** Manages execution environment variables, logging output streams, and system resource limits during rendering.

---

## 4. Recommended Tool Stack Summary

| Component | Tool / Technology | Purpose |
| :--- | :--- | :--- |
| **Operating System** | Ubuntu 22.04 LTS or 24.04 LTS | Core automation server host |
| **Trend Scraping** | Apify (TikTok / Instagram Scrapers) | Ingest trending videos, view counts, audio IDs, transcripts |
| **AI Processing** | Claude Subscription CLI (`claude code`) | Hook breakdown, script adaptation, and caption writing |
| **Video Rendering** | Remotion (React + Node.js + FFmpeg) | Code-driven local video generation and subtitle burn-in |
| **Human Review** | Flask (local web dashboard) | Approve / Reject / Request Changes before anything posts |
| **Publishing** | Native Python (`requests` / Meta & TikTok APIs) | 100% Free automated direct social posting — approved items only |
| **Task Scheduler** | Systemd Timers / Cron | Automated background execution every 6 hours |
| **Database** | SQLite | Track posted content, scraped IDs, and performance analytics |

---

## 5. Ubuntu Environment Setup

Run the following commands in your Ubuntu terminal (`Ctrl+Alt+T`) to install all system dependencies, Node.js, Python libraries, and the official Claude CLI tool:

```bash
# 1. Update system packages and install basic build utilities
sudo apt update && sudo apt install -y python3-pip python3-venv ffmpeg sqlite3 curl build-essential

# 2. Install Node.js LTS (v20+) required for Remotion and Claude Code
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# 3. Install Claude Code CLI tool (Utilizes your Claude.ai Subscription)
curl -fsSL https://claude.ai/install.sh | bash

# 4. Authenticate Claude CLI with your Claude.ai account
claude auth login
```

---

## 6. Pipeline Execution Code (`pipeline.py`)

Create a main directory for your project:
```bash
mkdir -p ~/viral_automation && cd ~/viral_automation
```

Save the following Python script as `~/viral_automation/pipeline.py`:

```python
#!/usr/bin/env python3
import subprocess
import json
import os
import sqlite3
import requests

def run_claude_cli(prompt_text):
    # Executes Claude via your local subscription CLI without paying for API tokens.
    cmd = ["claude", "-p", prompt_text]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"[-] Error calling Claude CLI: {e.stderr}")
        return None

def synthesize_viral_post(transcript, target_product):
    # Uses Claude to extract the viral structure and generate a new video script.
    prompt = f\"\"\"
    You are an expert viral social media strategist.
    
    ANALYSIS TARGET:
    Viral Transcript: "{transcript}"
    
    OUR PRODUCT AD BRIEF:
    "{target_product}"
    
    TASK:
    1. Identify the exact pattern, hook strategy (first 3s), and visual structure used in the viral transcript.
    2. Write a 15-second viral Reel/TikTok script promoting OUR PRODUCT using the exact same structural pattern.
    3. Output JSON format ONLY with the following keys:
       - "hook_analysis": "brief description of why the original post went viral"
       - "on_screen_hook": "first 3 seconds bold text header"
       - "spoken_script": "full 15-second voiceover transcript"
       - "caption": "Instagram/TikTok post caption"
       - "hashtags": ["tag1", "tag2", "tag3"]
    
    Return raw valid JSON only. Do not add markdown backticks.
    \"\"\"
    
    response = run_claude_cli(prompt)
    return response

def publish_to_instagram_direct(video_path, caption, access_token, ig_user_id):
    # Native Python post implementation replacing paid SaaS providers
    print("[+] Publishing directly via Meta Graph API...")
    # Step 1: Container creation -> Step 2: Media Publish
    # (Implementation using standard `requests` module)

def init_db(db_path="content_queue.db"):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS content_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_transcript TEXT,
            script_json TEXT,
            video_path TEXT,
            status TEXT DEFAULT 'pending_review',   -- pending_review | approved | rejected | changes_requested
            review_feedback TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reviewed_at TIMESTAMP
        )
    """)
    conn.commit()
    return conn

def queue_for_review(conn, transcript, script_json, video_path):
    # Rendered content lands here instead of going straight to publish_to_instagram_direct().
    # A human must flip the status via the Flask dashboard (Section 8) before Distribution (3.5) will touch it.
    conn.execute(
        "INSERT INTO content_queue (source_transcript, script_json, video_path, status) VALUES (?, ?, ?, 'pending_review')",
        (transcript, script_json, video_path),
    )
    conn.commit()

if __name__ == "__main__":
    print("[+] Starting Viral Monitoring Pipeline...")

    # Simulated input from Apify Scraper API
    mock_viral_transcript = "Stop using basic text editors for your code! Here are 3 extensions that saved me 20 hours this week."
    product_info = "My SaaS tool that automates social media video generation for marketers."

    print("[+] Analyzing trend & drafting script via Claude CLI...")
    llm_output = synthesize_viral_post(mock_viral_transcript, product_info)
    
    if llm_output:
        print("\n=== GENERATED CONTENT PLAN ===")
        print(llm_output)
        
        with open("latest_content.json", "w") as f:
            f.write(llm_output)

        # After Remotion renders output.mp4 (Section 7), queue it for human review
        # instead of publishing immediately:
        conn = init_db()
        queue_for_review(conn, mock_viral_transcript, llm_output, video_path="output.mp4")

        print("\n[+] Success! Video rendered and queued for review at http://localhost:5000")
```

---

## 7. Local Video Assembly Setup (Remotion)

Set up a local Remotion React project inside your workspace to handle programmatic video compilation:

```bash
cd ~/viral_automation
npx create-video@latest video-renderer --template=helloworld
cd video-renderer
```

To render dynamic videos on your machine:
```bash
npx remotion render src/index.ts MainComposition output.mp4 \
  --props='{"titleText": "Stop Doing Social Media Manually!", "bgVideo": "assets/bg.mp4"}'
```

---

## 8. Human Review Dashboard (Flask)

Before anything reaches Meta/TikTok, every rendered item must be manually approved. This is a small local-only Flask app that reads/writes the same `content_queue.db` SQLite database the pipeline uses.

```bash
cd ~/viral_automation
pip install flask
```

Save as `~/viral_automation/review_dashboard.py`:

```python
#!/usr/bin/env python3
import sqlite3
from flask import Flask, render_template_string, request, redirect, send_from_directory

app = Flask(__name__)
DB_PATH = "content_queue.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

LIST_TEMPLATE = """
<h1>Pending Review ({{ items|length }})</h1>
{% for item in items %}
  <hr>
  <h3>#{{ item['id'] }}</h3>
  <video width="360" controls src="/video/{{ item['id'] }}"></video>
  <pre>{{ item['script_json'] }}</pre>
  <form method="post" action="/review/{{ item['id'] }}">
    <button name="action" value="approve">Approve</button>
    <button name="action" value="reject">Reject</button>
    <br><textarea name="feedback" placeholder="What should change?"></textarea>
    <button name="action" value="changes_requested">Request Changes</button>
  </form>
{% endfor %}
"""

@app.route("/")
def index():
    conn = get_db()
    items = conn.execute(
        "SELECT * FROM content_queue WHERE status = 'pending_review' ORDER BY created_at DESC"
    ).fetchall()
    return render_template_string(LIST_TEMPLATE, items=items)

@app.route("/video/<int:item_id>")
def video(item_id):
    row = get_db().execute("SELECT video_path FROM content_queue WHERE id = ?", (item_id,)).fetchone()
    return send_from_directory(".", row["video_path"])

@app.route("/review/<int:item_id>", methods=["POST"])
def review(item_id):
    action = request.form["action"]  # approve | reject | changes_requested
    feedback = request.form.get("feedback", "")
    conn = get_db()
    conn.execute(
        "UPDATE content_queue SET status = ?, review_feedback = ?, reviewed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (action if action != "approve" else "approved", feedback, item_id),
    )
    conn.commit()
    # 'changes_requested' rows are picked up by a small watcher (or the next
    # pipeline run) that re-calls synthesize_viral_post() with the original
    # transcript/product brief + this feedback appended, then re-renders and
    # re-queues the result as 'pending_review'.
    return redirect("/")

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
```

Run it whenever you want to review the queue:
```bash
cd ~/viral_automation && python3 review_dashboard.py
```
Then open `http://localhost:5000` in a browser. Nothing here is exposed outside `localhost` — no auth layer is needed since the dashboard never leaves the machine.

---

## 9. Ubuntu Automation via Systemd

Because Step 4 (human review) is a manual checkpoint, generation and publishing are now split into two independent, decoupled systemd timers instead of one end-to-end job. This keeps ingestion/rendering fully unattended while guaranteeing nothing posts without approval.

### 1. Create the Generation Service (Ingest → Synthesize → Render → Queue for review)
```bash
sudo nano /etc/systemd/system/viral-generate.service
```

```ini
[Unit]
Description=Viral Social Media Ingestion, Generation & Rendering Task
After=network.target

[Service]
Type=oneshot
User=YOUR_UBUNTU_USERNAME
WorkingDirectory=/home/YOUR_UBUNTU_USERNAME/viral_automation
ExecStart=/usr/bin/python3 /home/YOUR_UBUNTU_USERNAME/viral_automation/pipeline.py

[Install]
WantedBy=multi-user.target
```

### 2. Create the Generation Timer (Runs every 6 hours)
```bash
sudo nano /etc/systemd/system/viral-generate.timer
```

```ini
[Unit]
Description=Run Viral Generation every 6 hours

[Timer]
OnCalendar=*-*-* 00,06,12,18:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

### 3. Create the Publish Service (Posts only status='approved' rows)
```bash
sudo nano /etc/systemd/system/viral-publish.service
```

```ini
[Unit]
Description=Publish Approved Viral Content
After=network.target

[Service]
Type=oneshot
User=YOUR_UBUNTU_USERNAME
WorkingDirectory=/home/YOUR_UBUNTU_USERNAME/viral_automation
ExecStart=/usr/bin/python3 /home/YOUR_UBUNTU_USERNAME/viral_automation/publish.py

[Install]
WantedBy=multi-user.target
```

### 4. Create the Publish Timer (Checks for approvals every 30 minutes)
```bash
sudo nano /etc/systemd/system/viral-publish.timer
```

```ini
[Unit]
Description=Check for approved content every 30 minutes

[Timer]
OnCalendar=*:0/30
Persistent=true

[Install]
WantedBy=timers.target
```

### 5. Enable and Start Both Timers
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now viral-generate.timer
sudo systemctl enable --now viral-publish.timer

# Check status
sudo systemctl status viral-generate.timer viral-publish.timer
```

The Flask review dashboard (Section 8) is run on demand, not on a timer — you open it when you want to clear the review queue. Optionally, run it as a standing (non-timer) systemd service with `Type=simple` and `Restart=on-failure` if you want it always reachable at `http://localhost:5000`.

---

## 10. Hardware & Resource Analysis

* **Local Workstation vs Cloud VPS:** A standard laptop running Ubuntu is 100% sufficient for running this entire system.
* **CPU/GPU Usage:** Since AI reasoning (Claude CLI) and trend scraping (Apify) are offloaded over HTTP, local computing is only utilized briefly during Remotion FFmpeg rendering.
* **Storage Requirement:** Minimum 20 GB free disk space for Node modules, video assets, and temporary MP4 render files.
