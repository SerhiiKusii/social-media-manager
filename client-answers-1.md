# Responses to Client Questions — Round 1

Answers reference `Viral_Social_Media_Architecture_v3.md`. Where the current
architecture does **not** cover something you asked about, that is called out
explicitly as a scope gap rather than glossed over.

---

## 1. Custom-built system vs. integration of existing services?

**Both — it is a custom orchestration layer built on top of paid third-party services.**

What is genuinely custom-built (owned by you, no vendor lock-in):

- The pipeline logic: trend selection, virality thresholds, deduplication, retry/error handling
- The prompt engineering and creative-strategy layer (hook deconstruction, script synthesis)
- The Remotion video templates — your visual identity, in code
- The database schema, analytics store, and publishing modules
- The scheduling and operations layer (systemd)

What is rented from third parties:

| Service | What it does | What happens if you drop it |
| :--- | :--- | :--- |
| Claude | Script/hook generation | Swappable for another LLM; prompts are portable |
| Apify | Scraping TikTok/Instagram | Swappable, but this is the hardest piece to replace |
| Meta / TikTok / YouTube APIs | Publishing | Not replaceable — these are the platforms |

**The honest summary:** roughly 70% custom code, 30% integration. You own the
system and the logic. You do not own the data sources or the distribution
channels, and no vendor can give you those.

### Two commercial flags worth resolving before we build

1. **The Claude CLI/subscription approach in v3 is a cost optimization with a
   licensing question attached.** The doc proposes driving the `claude` CLI on a
   ~$20/mo consumer subscription instead of the metered API. Consumer
   subscriptions are intended for interactive personal use; powering an
   always-on automated commercial service from one sits in a grey area and is
   subject to interactive rate limits that a 24/7 pipeline will hit. My
   recommendation is to budget for the **API** instead. Real cost at your likely
   volume is small — roughly **$5–30/month** for tens of scripts per day — and it
   removes both the licensing question and the rate-limit fragility.

2. **Remotion's free licence covers individuals, non-profits, and companies with
   up to 3 employees.** If your business is larger than that, a Remotion company
   licence is required. Worth confirming your headcount now so the budget is
   accurate.

---

## 2. Will there be a single dashboard with publishing, AI generation, and analytics tabs?

**Not in the architecture as written. This is the largest scope gap in v3.**

The v3 system is **headless**: a background timer runs the pipeline, writes to a
local SQLite file, and posts. There is no user interface. To see anything you
would read the database or the logs.

Everything you described is buildable on top of the existing pipeline — the data
model and the modules are already the right shape for it — but it is a distinct
piece of work that v3 does not price or schedule. Concretely, a dashboard means
adding:

- **A web application** (API layer + front end) alongside the pipeline
- **A content calendar** with drag-and-drop scheduling, replacing the fixed 6-hour cron
- **A human review/approval queue** — see the note below
- **An analytics section** aggregating per-post metrics across platforms
- **A generation screen** to trigger and re-roll scripts on demand
- **Login and session handling**, plus migrating SQLite → Postgres if this is ever
  hosted rather than run on your own machine

**Strong recommendation regardless of dashboard scope:** do **not** run this
fully unattended into live accounts on day one. AI-generated video going
straight to a brand account with no human in the loop is how accounts get
damaged. The realistic sequence is *generate → human approves → publish*, with
the approval step being exactly what a dashboard is for. That makes the
dashboard less of a nice-to-have and more of a phase-2 requirement.

Please confirm whether the dashboard is in scope so it can be estimated properly.

---

## 3. Will it sync Instagram, Facebook, TikTok, and YouTube from one place?

**Architecturally yes — all four are reachable through official APIs. But v3 only
specifies two of them, and each platform has an approval process with real lead
time.**

| Platform | Covered in v3? | API | Practical requirements |
| :--- | :--- | :--- | :--- |
| **Instagram** (Reels) | Yes | Meta Graph API | Instagram **Business or Creator** account linked to a Facebook Page; Meta app review for content-publishing permissions |
| **Facebook** (Pages/Reels) | No — but low effort | Meta Graph API | Same Meta app and review as Instagram; mostly incremental work |
| **TikTok** | Yes | Content Posting API | Requires TikTok app **audit**. Before audit is granted, an app can typically only post privately/to self — public posting is gated |
| **YouTube** (Shorts) | **No — not in v3 at all** | YouTube Data API v3 | OAuth per channel; default daily quota is ~10,000 units and a video upload costs ~1,600, i.e. **roughly 6 uploads/day per project** unless you request more |

Three things to plan around:

1. **Facebook and YouTube need to be added to scope.** Facebook is cheap to add.
   YouTube is a separate integration with its own auth, quota model, and upload
   flow.
2. **Platform approvals are the critical path, not the code.** Meta app review
   and TikTok audit are external processes measured in weeks and can come back
   with change requests. These should start early and in parallel with
   development, not after it.
3. **Publishing is one-way (push).** "Sync" in the sense of a unified inbox —
   reading and replying to comments and DMs from one place — is a materially
   different feature set with its own permissions. Let me know if that is part of
   what you meant.

---

## 4. How do the bots work? How is reach increased, and sales driven, while staying compliant?

This question needs a direct answer, because the word "bots" usually means one of
two very different things.

### What this system is **not**

It is **not** an engagement bot. It does not auto-follow, auto-unfollow,
mass-like, spam comments, run view/like farms, use follow-back loops, or operate
sockpuppet accounts. All of those are explicit violations of Instagram, TikTok,
and YouTube terms of service. They are also increasingly ineffective, and the
enforcement outcome is shadowbanning or permanent loss of the account and its
audience. I will not build them, and you should be sceptical of anyone who
offers to.

### What the "bot" actually is

A **content production bot**. It automates the labour of producing on-trend
video, not the manipulation of the audience. The reach mechanism is entirely on
the supply side:

1. **Trend-jacking with speed.** The system detects a format while it is still
   climbing and produces your version within hours instead of days. Timing
   against the trend curve is the single largest lever on reach.
2. **Structural hook transfer.** Claude extracts *why* a video held attention —
   the first-3-second pattern, pacing, retention structure — and rebuilds it
   around your product. Retention rate is what the recommendation algorithms
   actually optimise for.
3. **Volume with variation.** Organic short-form reach is high-variance. Ten
   competent posts consistently outperform one polished post, because you get ten
   draws at the algorithm.
4. **Consistent cadence.** Automated scheduling removes the irregular posting
   that suppresses distribution.
5. **A closed feedback loop.** Section 3.4 pulls performance data back into
   ingestion, so the system learns which hooks work *for your account* rather
   than in general.

In short: reach comes from making better content faster, not from gaming
engagement signals.

### Sales and conversion

The architecture as written stops at "post published" and does not track
revenue. To connect content to sales, the following need to be added:

- **UTM-tagged destination links**, stored per post in SQLite, so each video maps
  to sessions and orders in your analytics
- **Link-in-bio routing** — a landing page per campaign rather than one generic link
- **Native commerce surfaces** where available (Instagram product tags, TikTok
  Shop, YouTube Shorts product links) — these convert far better than sending
  users off-platform
- **A CTA generated as part of the script**, not bolted on afterwards. Claude
  should be prompted to write the hook and the call-to-action as one unit
- **A conversion column in the reporting**, so the feedback loop optimises for
  purchases rather than views. High-view content and high-converting content are
  frequently not the same content

### Compliance — the real constraints

These are not optional, and two of them affect the current design directly:

1. **AI-generated content must be disclosed.** Both Meta and TikTok now require
   AI-generated or significantly AI-edited content to be labelled, and both do
   automated detection. The publishing modules should set the AI-content flag on
   upload rather than relying on you to remember.
2. **Do not republish other creators' assets — this needs a change to §3.1.** The
   architecture currently says the scraper "downloads audio tracks" and extracts
   transcripts. Re-uploading another creator's audio or footage is copyright
   infringement and a takedown/strike risk. The correct behaviour is to use
   scraped material **as analysis input only** — extract the structure, then
   generate your own voiceover and use licensed or original footage. Trending
   *sounds* should be attached via the platform's own audio library at post time,
   which is the licensed path. I would like to amend the document on this point.
3. **Scrape public data only**, at reasonable rates, and never behind a login.
4. **No fake engagement of any kind** — purchased views, likes, followers, or
   comment pods.
5. **Rate limits are a compliance surface too.** Posting far above human cadence
   is itself a spam signal. Realistic ceiling is roughly **1–3 posts per account
   per day**, not the maximum the API permits.

---

## 5. How many accounts, brands, or niches can be managed at once?

**No hard limit in the software. The real limits are cost, machine capacity, and
platform rate limits — and v3 is currently written for a single brand.**

The pipeline as specified assumes one product brief and one set of credentials.
Multi-tenancy is a straightforward but non-zero change: brand profiles become
config, and `brand_id` becomes a dimension on every table and every scheduled job.

Once that is in place, here is where the ceilings actually sit:

| Constraint | Effect as you add brands |
| :--- | :--- | 
| **Apify credits** | Scales roughly linearly with niches monitored. The $39 Starter tier covers a handful of brands; heavy multi-brand monitoring pushes you to a higher tier |
| **LLM cost** | Linear per script, but small in absolute terms |
| **Render time** | The binding constraint on a laptop. Remotion + FFmpeg is CPU-bound, on the order of minutes per video. ~20–40 videos/day is a sane ceiling for a single decent machine before it needs to run overnight or move to a server |
| **Platform rate limits** | Per-account, so they do not compound across brands — but each brand still needs its own OAuth tokens and its own approved app connection |
| **Storage** | ~20 GB baseline; add headroom per brand for assets and renders |
| **Your review time** | With a human approval step, this becomes the practical limit long before any technical one |

**Practical guidance:** the design comfortably supports **5–15 brands** on a
single reasonably specced machine. Beyond that, the honest answer is a move to a
server with a render queue rather than a claim that a laptop scales
indefinitely. Nothing in the architecture prevents that move — it is the same
code on different hardware — but it should be a planned phase rather than a
surprise.

---

## Summary of items needing your decision

| # | Item | Why it matters |
| :--- | :--- | :--- |
| 1 | Dashboard in scope? | Largest gap between v3 and your expectations; drives timeline and cost |
| 2 | Facebook + YouTube in scope? | Two of your four platforms are not in v3 |
| 3 | Claude API vs. consumer subscription | Licensing clarity and rate-limit stability; ~$5–30/mo |
| 4 | Company headcount | Determines whether a Remotion licence is required |
| 5 | Human approval before publishing? | Strongly recommended; also defines the dashboard's core screen |
| 6 | Number of brands at launch | Determines whether multi-tenancy is phase 1 or phase 2 |
| 7 | Amend §3.1 on asset reuse | Current wording implies republishing scraped audio — a copyright risk |
| 8 | Start platform approvals now | Meta review and TikTok audit are the critical path, measured in weeks |
