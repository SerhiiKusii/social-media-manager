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

```bash
trendstealer ingest run <brand> --dry-run     # print what would be queued
trendstealer worker run-once <brand>          # process exactly one item
trendstealer publish run <brand>               # one rate-gated publish attempt
trendstealer maintenance backup --keep-last 14
trendstealer status                            # content_items counts by status
```

Every command that touches an external service defaults to the safe mode
switch; nothing here spends money or posts live unless the corresponding
`TRENDSTEALER_*_MODE` env var is set to `live`.
