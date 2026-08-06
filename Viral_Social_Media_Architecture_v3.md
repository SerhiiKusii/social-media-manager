# Automated Social Media Viral Monitoring & Video Generation Service Architecture

**Target OS:** Ubuntu Linux  
**AI Core:** Claude Subscription (utilizing `claude` CLI)  
**Execution Environment:** Local Systemd Service + Cloud APIs  

---

## Executive Summary

This document outlines the complete technical architecture and implementation guide for building an automated viral social media monitoring and content creation service on an Ubuntu Linux system. The system ingests top-performing viral content from Instagram and TikTok, extracts winning structural hooks using Claude via the CLI, synthesizes custom scripts for your product, renders videos locally using **Remotion**, and publishes them via automated APIs or direct Python scripts.

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
│ 2. Intelligence Layer (Claude CLI)      │
│    • Executed via local `claude` CLI    │
│    • Extract Hook / Viral Pattern       │
│    • Synthesize scripts & captions      │
└───────────────────┬─────────────────────┘
                    │ Generated Script JSON & Asset Map
                    ▼
┌─────────────────────────────────────────┐
│ 3. Local Video Rendering (Remotion Node) │
│    • Local FFmpeg + Remotion SSR        │
│    • Stitch video background, audio & text│
└───────────────────┬─────────────────────┘
                    │ Rendered .MP4 Output
                    ▼
┌─────────────────────────────────────────┐
│ 4. Distribution (Direct APIs / Python)  │
│    • POST via Meta Graph & TikTok APIs  │
│    • Log metrics to local SQLite DB     │
└───────────────────┬─────────────────────┘
```

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

### 3.4 Direct Distribution & Persistence (Native Python + SQLite)
Handles post scheduling, direct API publishing, and local audit logging without third-party SaaS fees.
* **Direct Python API Publishing:** Posts generated `.mp4` files, captions, and hashtags directly using custom Python modules interacting with Meta Graph API (Instagram Reels) and TikTok API.
* **State & Audit Logging:** Records posted video IDs, original source URLs, and execution timestamps into a local SQLite database to prevent duplicate posting.
* **Analytics Tracking:** Periodically queries post performance to feed engagement feedback back into the ingestion system.

### 3.5 Task Scheduler (Systemd Timers / Cron)
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
| **Publishing** | Native Python (`requests` / Meta & TikTok APIs) | 100% Free automated direct social posting |
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
            
        print("\n[+] Success! Ready for Remotion video rendering.")
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

## 8. Ubuntu Automation via Systemd

To run the pipeline continuously in the background without manually opening terminal windows, setup a background systemd timer.

### 1. Create Systemd Service File
```bash
sudo nano /etc/systemd/system/viral-monitor.service
```

Add the following configuration:
```ini
[Unit]
Description=Viral Social Media Ingestion & Generation Task
After=network.target

[Service]
Type=oneshot
User=YOUR_UBUNTU_USERNAME
WorkingDirectory=/home/YOUR_UBUNTU_USERNAME/viral_automation
ExecStart=/usr/bin/python3 /home/YOUR_UBUNTU_USERNAME/viral_automation/pipeline.py

[Install]
WantedBy=multi-user.target
```

### 2. Create Systemd Timer File (Runs every 6 hours)
```bash
sudo nano /etc/systemd/system/viral-monitor.timer
```

Add the following configuration:
```ini
[Unit]
Description=Run Viral Monitor every 6 hours

[Timer]
OnCalendar=*-*-* 00,06,12,18:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

### 3. Enable and Start Systemd Timer
```bash
# Reload daemon and enable timer
sudo systemctl daemon-reload
sudo systemctl enable --now viral-monitor.timer

# Check status of the timer
sudo systemctl status viral-monitor.timer
```

---

## 9. Hardware & Resource Analysis

* **Local Workstation vs Cloud VPS:** A standard laptop running Ubuntu is 100% sufficient for running this entire system.
* **CPU/GPU Usage:** Since AI reasoning (Claude CLI) and trend scraping (Apify) are offloaded over HTTP, local computing is only utilized briefly during Remotion FFmpeg rendering.
* **Storage Requirement:** Minimum 20 GB free disk space for Node modules, video assets, and temporary MP4 render files.
