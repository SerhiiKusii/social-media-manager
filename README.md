# Trend Stealer

An automated content pipeline: scrape trending TikTok/Instagram videos,
use Claude to deconstruct the viral hook and rewrite it for your product,
render a vertical video with Remotion, put it in front of a human for
review, and publish approved videos to Instagram Reels.

Nothing reaches a live account without an explicit human approval. See
[`docs/Viral_Social_Media_Architecture.md`](docs/Viral_Social_Media_Architecture.md)
for the system design and [`docs/RUNBOOK.md`](docs/RUNBOOK.md) for
operating it.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
./scripts/install-tools.sh          # portable node/npm + ffmpeg, no sudo
cd video-renderer && npm install && cd ..
python -m piper.download_voices --download-dir var/piper-voices en_US-lessac-medium

cp .env.example .env                # defaults are safe: fixture/dry-run everywhere
trendstealer db upgrade
trendstealer brands add acme

make test                           # full pipeline, zero external calls, zero cost
```

Everything defaults to fixture/dry-run mode (`TRENDSTEALER_APIFY_MODE`,
`TRENDSTEALER_LLM_BACKEND`, `TRENDSTEALER_PUBLISH_MODE` in `.env.example`)
so the whole pipeline runs offline before you connect a single paid API
or real account.

## Try the review/revise loop end to end

```bash
trendstealer worker run-once acme      # fixture LLM -> real Piper -> real Remotion render
trendstealer review serve              # http://127.0.0.1:5000, needs REVIEW_DASHBOARD_TOKEN
# in the dashboard: request changes on the item -> note becomes the next revision's instruction
trendstealer worker run-once acme      # produces revision 1 with a different hook
```

## Repo layout

- `src/trendstealer/` — the pipeline: `ingest/`, `intelligence/` (LLM),
  `tts/`, `render/` (Remotion contract), `review/` (Flask dashboard),
  `publish/` (Instagram), `metrics/`, `commands/` (orchestration), `cli.py`
- `video-renderer/` — the Remotion project; `src/types.ts` is the zod
  half of the Python↔Remotion JSON contract (`render/props.py` the other)
- `src/trendstealer/states.py` — the finite state machine enforcing the
  human review gate; `src/trendstealer/repo.py` — every SQL statement
- `tests/` — `unit/` (fast, offline), `integration/` (real toolchain,
  marked `slow`), `fixtures/`, `golden/`
- `deploy/systemd/` — service/timer units; `docs/RUNBOOK.md` for ops

## Testing

```bash
make test          # fast: fixtures/mocks only, <60s
make test-slow      # real Piper + faster-whisper + Remotion render, local only
```

## Status

Milestones M1–M10 of the implementation plan are built: skeleton, LLM
intelligence layer, TTS/captions, Remotion rendering, the review
dashboard, ingestion, the revision-loop worker, Instagram publishing,
metrics/feedback loop, and ops tooling.

The full chain has been run end to end against a live Instagram Business
account: ingest → synthesize → Piper voiceover → Remotion render →
dashboard review (including a request-changes revision) → live Reel →
insights snapshot. Two things are still fixture-backed by default and
have never been exercised live: `TRENDSTEALER_APIFY_MODE=live` (real
scraping) and `TRENDSTEALER_LLM_BACKEND=anthropic` (real script
generation — the fixture backend only string-concatenates, so revisions
read as garbage until this is switched on).

### Instagram auth: two incompatible flows

Which flow issued your token decides both the API host and the upload
path, and the wrong combination fails in confusing ways:

| | Facebook Login for Business | Instagram Login (`IGAA…` tokens) |
|---|---|---|
| API host | `graph.facebook.com` | `graph.instagram.com` |
| Upload | resumable byte upload | **`video_url` only** |
| Needs a public URL | no | yes |

For Instagram Login, set `TRENDSTEALER_GRAPH_API_BASE` and
`TRENDSTEALER_PUBLISH_TUNNEL=cloudflared` (see `.env.example`);
`publish/tunnel.py` then serves the MP4 through a disposable Cloudflare
quick tunnel for the one fetch Meta makes, and tears it down after.
