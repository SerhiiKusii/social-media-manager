# Runbook

Operational reference for running trend-stealer in production. For the
system design and build order, see
[`Viral_Social_Media_Architecture.md`](Viral_Social_Media_Architecture.md)
and the implementation plan in the repo's commit history.

## Layout on the host

```
/opt/trendstealer/          # WorkingDirectory for every unit
  .venv/                    # Python virtualenv
  var/                      # DB, renders, logs, backups, locks
/etc/trendstealer/env       # EnvironmentFile -- secrets + BRAND_KEY, chmod 600
```

## systemd units

| Unit | Cadence | What it does |
|---|---|---|
| `viral-review.service` | always-on | Review dashboard (`trendstealer review serve`) |
| `viral-ingest.timer` | 4x/day (02/08/14/20:00, ±15min) | Scrape, virality-gate, dedupe, queue survivors |
| `viral-worker.timer` | every 2 min | One unit of work: synthesize/render one item |
| `viral-publish.timer` | every 30 min | Rate-gated publish, one item per run |
| `viral-metrics.timer` | daily | Snapshot insights for published items |
| `viral-gc.timer` | daily | Auto-archive stale reviews, prune old render dirs |
| `viral-backup.timer` | nightly 03:00 | `sqlite3`-safe online backup to `var/backups/` |

Install: copy `deploy/systemd/*.service` and `*.timer` to
`/etc/systemd/system/`, then `systemctl daemon-reload && systemctl enable
--now viral-review.service viral-ingest.timer viral-worker.timer
viral-publish.timer viral-metrics.timer viral-gc.timer viral-backup.timer`.

Check status: `systemctl list-timers 'viral-*'` and `journalctl -u
viral-worker.service -n 50`.

### User-mode install (no root)

`deploy/systemd/user/install.sh` renders the same unit files for
`systemctl --user` -- no dedicated `trendstealer` user, no `/opt`, no
root. It rewrites paths to point at the repo checkout and `.env`, and
prints the enable commands rather than running them. Requires `make dev`
and a filled-in `.env` first. User services stop at logout unless
lingering is on (`loginctl show-user $USER | grep Linger`; enable with
`loginctl enable-linger $USER`).

Everywhere below, a system-wide install uses plain `systemctl` /
`journalctl -u`; a user-mode install adds `--user` to both.

## Verifying system state

Two questions come up constantly: "is everything actually running?" and
"is everything actually stopped?" Neither is answered by looking at one
unit -- there are 5 timers, 2 long/short-running services, an OS-level
lock file, and the DB's own notion of in-flight work. Check all of them.

### Is everything running properly?

```bash
# 1. Every unit the deploy expects to be enabled is enabled, and none are failed.
systemctl [--user] list-unit-files 'viral-*'      # *.timer should show `enabled` (all 5)
systemctl [--user] list-timers 'viral-*'           # NEXT/LAST columns populated, nothing stuck
systemctl [--user] list-units 'viral-*' --all      # ACTIVE/SUB for each -- no `failed`

# 2. The dashboard is actually serving.
systemctl [--user] status viral-review.service     # active (running)
curl -sI http://127.0.0.1:${REVIEW_DASHBOARD_PORT:-5000}/   # any HTTP response, not connection-refused

# 3. The app-level health check: DB reachable, schema current.
trendstealer healthz                                # prints "ok" and exits 0

# 4. No unit has been silently failing.
systemctl [--user] list-units 'viral-*' --all --state=failed
journalctl [--user] -u 'viral-*' -p err --since -24h --no-pager

# 5. Work is actually flowing (not just that units *fire* -- that they *finish*).
trendstealer status                                 # nothing stuck in synthesizing/rendering/publishing
                                                      # for longer than a lease TTL (default 600s) plus a retry
```

If (5) shows an item stuck in `synthesizing` or `rendering` for a while,
that's expected until the next `viral-worker.timer` tick reclaims the
expired lease -- see "Common incidents" below before intervening by hand.

### Is everything stopped?

Stopping the timers is not enough on its own -- a run can already be
in flight, and the worker lock/DB state outlive the unit that created
them. Check all of these before assuming nothing will happen next:

```bash
# 1. Stop the timers (prevents new runs) and the dashboard.
systemctl [--user] stop viral-ingest.timer viral-worker.timer \
  viral-publish.timer viral-metrics.timer viral-gc.timer viral-backup.timer
systemctl [--user] stop viral-review.service

# To also prevent them from starting again on the next boot/login:
systemctl [--user] disable viral-ingest.timer viral-worker.timer \
  viral-publish.timer viral-metrics.timer viral-gc.timer viral-backup.timer viral-review.service

# 2. Confirm no *.service triggered by a timer is still mid-run --
#    `stop` on the *.timer does not kill an already-running *.service.
systemctl [--user] list-units 'viral-*.service' --all   # every SUB should be `dead` or `exited`, none `running`
# if one is still running:
systemctl [--user] stop viral-<name>.service              # e.g. viral-worker.service, viral-publish.service

# 3. Confirm the worker lock is free (held via flock on var/locks/worker.lock
#    for the duration of a render -- killing the service releases it, but
#    verify rather than assume if a process was killed forcefully).
fuser var/locks/worker.lock 2>&1 || echo "lock free"
lsof var/locks/worker.lock 2>&1 || echo "lock free"

# 4. Confirm nothing is left mid-pipeline in the DB (expected to be empty,
#    or only contain items you know are legitimately mid-flight).
sqlite3 var/db/trendstealer.db \
  "SELECT id, status FROM content_items WHERE status IN
   ('synthesizing','rendering','publishing');"

# 5. No stray trendstealer process outside systemd's control (a manual
#    `generate now` / `publish now` run in a terminal isn't a unit and
#    `systemctl stop` won't touch it).
pgrep -af 'trendstealer (worker|publish|generate|ingest)'
```

`publish now` in particular is worth double-checking after a "stop
everything" -- it bypasses the rate limiter, so if it's still running in
a terminal somewhere, stopping the timers does nothing to it.

## First-time setup

```bash
trendstealer db upgrade
trendstealer brands add <brand_key>
trendstealer healthz          # exit 0 once the schema is current
```

`TRENDSTEALER_APIFY_MODE`, `TRENDSTEALER_LLM_BACKEND`, and
`TRENDSTEALER_PUBLISH_MODE` all default to their safe/offline value.
Nothing calls a paid API or posts live until these are explicitly set to
`live` in `/etc/trendstealer/env`.

## Command reference

Every subcommand the `trendstealer` CLI exposes (`src/trendstealer/cli.py`).
All of them read config/env the same way the systemd units do, so they're
safe to run ad hoc against the live DB.

**Database**
```bash
trendstealer db upgrade                # apply pending migrations
trendstealer db check                  # exit 1 if migrations are pending; applies nothing
```

**Brands**
```bash
trendstealer brands add <brand_key>    # register config/brands/<brand_key>.toml in the DB
trendstealer brands list               # brands on disk + whether each is registered
```

**Top-level**
```bash
trendstealer status                    # content_items counts by pipeline status
trendstealer healthz                   # exit 0 if DB is reachable and schema is current, else 1
```

**Review dashboard**
```bash
trendstealer review serve [--host H] [--port P]   # production WSGI server (waitress), needs REVIEW_DASHBOARD_TOKEN
```

**Ingest**
```bash
trendstealer ingest run <brand_key> [--dry-run]   # scrape + virality gate + dedupe, queue survivors
```

**Worker**
```bash
trendstealer worker run-once <brand_key>          # claim and fully process one item; no-op if nothing claimable
```

**Generate (manual, bypasses the worker timer)**
```bash
trendstealer generate now <brand_key> [--item-id N] [--skip-ingest]
```

**Publish**
```bash
trendstealer publish run <brand_key>                          # rate-gated, at most one item -- what the timer calls
trendstealer publish now <brand_key> [--item-id N] [--yes]    # skips the rate limiter, still gated by review + preflight
```

**Metrics**
```bash
trendstealer metrics run <brand_key>   # snapshot IG insights for published items due a refresh
```

**Maintenance**
```bash
trendstealer maintenance gc [--max-pending-review-hours 48] [--retention-days 30]
trendstealer maintenance backup [--keep-last 14]
trendstealer maintenance check-token <brand_key> [--warn-days 7]
```

**Assets**
```bash
trendstealer assets fetch-pexels <query> [--count 5] [--tags ...]   # download + register cleared stock B-roll
trendstealer assets add <path> [--kind video] [--license ...] [--tags ...] [--attribution ...] [--cleared]
trendstealer assets list [--kind video] [--all-assets]              # least-recently-used first; cleared-only by default
```

Every command supports `--help` for the full flag list, including flags
not spelled out above.

## Day-to-day: the review queue

Reviewers work entirely through the dashboard (`viral-review.service`,
bearer token in `REVIEW_DASHBOARD_TOKEN`). Approve, reject, or request
changes; a "request changes" note becomes the next revision's prompt
instruction. The cap is 3 revisions (`states.MAX_REVISIONS`) -- past that
the dashboard disables the button and the item must be approved or
rejected as-is.

Items sitting in `pending_review` past 48h are auto-archived by
`viral-gc.timer`, not left to rot.

## Common incidents

**A worker run is stuck / an item is wedged in `synthesizing` or
`rendering`.** Check `journalctl -u viral-worker.service`. Leases expire
after `worker.lease_ttl_seconds` (default 600s); the next tick reclaims
and retries automatically. If it keeps failing the same way, the error is
almost certainly in the log from the failed attempt -- fix the root cause
(bad prompt output, missing voice model, `ffmpeg`/`node` not on `PATH`)
rather than manually flipping the DB status.

**Publish keeps failing.** `trendstealer publish run <brand>` prints the
outcome directly. Check `publications.error` for the last attempt
(`sqlite3 var/db/trendstealer.db "SELECT * FROM publications WHERE
status='failed' ORDER BY id DESC LIMIT 5"`). A `190` error code means the
access token expired -- see below.

**A container goes straight to `status_code=ERROR` within seconds.** Too
fast to be a video problem -- Meta validates `video_url` synchronously at
container creation, so this is the URL not answering yet. On the tunnel
path `publish/tunnel.py` already waits for the edge to respond before
handing the URL over; if it still happens, check that `cloudflared` is
reachable and that nothing is blocking `*.trycloudflare.com`. (A local
DNS filter blocking that domain does **not** break publishing -- Meta
does the fetching -- but it does break the readiness probe, which then
falls back to resolving over DoH.)

**A Reel is live but the DB says `publishing`.** The publish succeeded and
the bookkeeping INSERT afterwards did not. Search the log for
`publish_recorded_failed_but_post_is_live`; it carries the
`platform_media_id` and `permalink`. Insert the `publications` row by
hand with `status='published'`, then transition the item
`publishing -> published`. Do **not** re-run publish -- that double-posts.

**Access token expiring or expired.**
`trendstealer maintenance check-token <brand> --warn-days 7` exits
non-zero once the token is within the warning window; wire it into a
monitoring check. Refresh the long-lived token in Meta's dashboard and
update `IG_ACCESS_TOKEN` (or the per-brand `IG_ACCESS_TOKEN__<BRAND>`
override) in the env file.

**Need to restore from backup.** Backups are plain SQLite files in
`var/backups/trendstealer-<timestamp>.db`, made via SQLite's own backup
API (safe to take while the live DB is being written under WAL). Stop
every unit, copy the desired backup over `var/db/trendstealer.db`, run
`trendstealer db check` to confirm the schema still matches, then restart
the units.

**Disk filling up.** `viral-gc.timer` prunes render artifacts for items
in a terminal state (`published`/`archived`/`rejected`) older than 30
days. Run `trendstealer maintenance gc` manually to force a pass, or
adjust `--retention-days`.

## Manual one-offs

See "Command reference" above for the full list. Every command that
touches an external service defaults to the safe mode switch; nothing
spends money or posts live unless the corresponding
`TRENDSTEALER_*_MODE` env var is set to `live`.

## "Do it right now"

The timers exist for unattended operation. When you want something to
happen immediately, use these rather than editing `config/brands/*.toml`
to loosen the gate — a loosened config is easy to leave in place, which
silently disables rate limiting for the account.

```bash
trendstealer generate now <brand>              # ingest + render one item now
trendstealer generate now <brand> --item-id 7  # re-render one specific item
trendstealer publish now <brand>               # publish oldest approved, NOW
trendstealer publish now <brand> --item-id 7 --yes
```

`generate now` prints the rendered MP4 path. It takes the same `flock` as
the timer-driven worker, so it will refuse rather than fight a scheduled
render for cores. With `TRENDSTEALER_APIFY_MODE=fixture` it will report
"nothing to generate" once the recorded trends are used up — that is the
fixture replaying itself, not a failure.

`publish now` **skips the rate limiter entirely** — posting windows, the
minimum gap, and the daily cap. It prompts before posting unless `--yes`.
What it does *not* skip: only an `approved` item can publish, `preflight()`
still enforces the AI-disclosure line and the asset licence check, and the
publications idempotency key still makes a double-publish an
`IntegrityError` rather than a second Reel.

Every forced publish is recorded — `status_events.actor` is
`publisher:forced` with a note naming the bypass:

```bash
sqlite3 var/db/trendstealer.db \
  "SELECT content_item_id, actor, note FROM status_events
   WHERE actor = 'publisher:forced' ORDER BY id DESC LIMIT 10;"
```

Note that `publish run` — what `viral-publish.service` invokes — has no
override flag at all. The forced path is a separate command on purpose, so
no edit to a unit file can make a timer bypass the rate limiter.
