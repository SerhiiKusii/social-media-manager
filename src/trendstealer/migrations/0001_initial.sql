-- 0001_initial.sql
-- Forward-only. Do not edit after this has been applied anywhere — add a new
-- migration file instead. See db.py:upgrade() for the checksum guard.

CREATE TABLE brands (
    id         INTEGER PRIMARY KEY,
    brand_key  TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE accounts (
    id                  INTEGER PRIMARY KEY,
    brand_id            INTEGER NOT NULL REFERENCES brands(id),
    platform            TEXT NOT NULL CHECK (platform IN ('instagram', 'tiktok', 'facebook', 'youtube')),
    platform_account_id TEXT NOT NULL,
    display_name        TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (brand_id, platform, platform_account_id)
);

CREATE TABLE scrape_runs (
    id             INTEGER PRIMARY KEY,
    brand_id       INTEGER NOT NULL REFERENCES brands(id),
    platform       TEXT NOT NULL CHECK (platform IN ('instagram', 'tiktok')),
    actor_id       TEXT NOT NULL,
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    status         TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    items_scraped  INTEGER NOT NULL DEFAULT 0,
    compute_units  REAL,
    error          TEXT
);

CREATE INDEX idx_scrape_runs_brand ON scrape_runs(brand_id, started_at);

-- Scraped candidate videos. Analysis input only — deliberately has no media
-- path column. Source audio/video is transient (var/tmp/), transcribed, and
-- unlinked; it is structurally unable to reach the renderer through this table.
CREATE TABLE trends (
    id                     INTEGER PRIMARY KEY,
    scrape_run_id          INTEGER REFERENCES scrape_runs(id),
    brand_id               INTEGER NOT NULL REFERENCES brands(id),
    platform               TEXT NOT NULL CHECK (platform IN ('instagram', 'tiktok')),
    platform_video_id      TEXT NOT NULL,
    source_account         TEXT,
    source_url             TEXT,
    caption                TEXT,
    transcript             TEXT,
    views                  INTEGER,
    likes                  INTEGER,
    comments               INTEGER,
    shares                 INTEGER,
    source_follower_count  INTEGER,
    duration_secs          REAL,
    posted_at              TEXT,
    scraped_at             TEXT NOT NULL,
    audio_id               TEXT,
    transcript_simhash     INTEGER,
    virality_score         REAL,
    skip_reason            TEXT,
    UNIQUE (platform, platform_video_id)
);

CREATE INDEX idx_trends_brand_scraped ON trends(brand_id, scraped_at);
CREATE INDEX idx_trends_audio_cooldown ON trends(brand_id, audio_id, posted_at);
CREATE INDEX idx_trends_simhash ON trends(brand_id, transcript_simhash);

-- One row per (brand, trend) pushed through the pipeline. `status` is the
-- finite-state-machine column enforced exclusively by trendstealer.states.
-- `version` is an optimistic-concurrency token: the review dashboard's
-- UPDATE must match it, so a stale page load can't clobber a newer action.
CREATE TABLE content_items (
    id                  INTEGER PRIMARY KEY,
    brand_id            INTEGER NOT NULL REFERENCES brands(id),
    trend_id            INTEGER NOT NULL REFERENCES trends(id),
    status              TEXT NOT NULL CHECK (status IN (
                             'queued', 'synthesizing', 'script_ready', 'rendering',
                             'pending_review', 'approved', 'rejected', 'changes_requested',
                             'publishing', 'published', 'publish_failed', 'archived'
                         )),
    version             INTEGER NOT NULL DEFAULT 1,
    current_revision_id INTEGER REFERENCES revisions(id),
    lease_owner         TEXT,
    lease_expires_at    TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (brand_id, trend_id)
);

CREATE INDEX idx_content_items_status ON content_items(status);
CREATE INDEX idx_content_items_lease ON content_items(lease_expires_at);

-- One row per synthesize+render attempt. revision_no 0 is the original;
-- 1..max_revisions are "changes requested" loops (see states.py cap).
CREATE TABLE revisions (
    id                     INTEGER PRIMARY KEY,
    content_item_id        INTEGER NOT NULL REFERENCES content_items(id),
    revision_no             INTEGER NOT NULL,
    prompt_version          TEXT NOT NULL,
    change_request          TEXT,
    script_plan_json        TEXT,
    on_screen_hook          TEXT,
    spoken_script           TEXT,
    voiceover_path          TEXT,
    captions_path           TEXT,
    video_path              TEXT,
    render_ms               INTEGER,
    llm_input_tokens        INTEGER,
    llm_output_tokens       INTEGER,
    llm_cache_read_tokens   INTEGER,
    created_at               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (content_item_id, revision_no)
);

CREATE INDEX idx_revisions_content_item ON revisions(content_item_id);

-- content_items.current_revision_id is created before revisions exist, so
-- the FK is added here instead of inline (SQLite allows forward references
-- in CREATE TABLE, but keeping it explicit avoids relying on that).

CREATE TABLE assets (
    id                      INTEGER PRIMARY KEY,
    brand_id                INTEGER REFERENCES brands(id),
    path                    TEXT NOT NULL UNIQUE,
    kind                    TEXT NOT NULL CHECK (kind IN ('video', 'image', 'audio')),
    tags                    TEXT,
    license                 TEXT NOT NULL,
    attribution             TEXT,
    cleared_for_commercial  INTEGER NOT NULL DEFAULT 0 CHECK (cleared_for_commercial IN (0, 1)),
    last_used_at            TEXT,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_assets_cleared ON assets(cleared_for_commercial, kind);

-- Provenance: exactly which assets went into which revision's render.
CREATE TABLE item_assets (
    id           INTEGER PRIMARY KEY,
    revision_id  INTEGER NOT NULL REFERENCES revisions(id),
    asset_id     INTEGER NOT NULL REFERENCES assets(id),
    role         TEXT,
    UNIQUE (revision_id, asset_id, role)
);

CREATE INDEX idx_item_assets_revision ON item_assets(revision_id);

-- idempotency_key makes a double-publish attempt raise IntegrityError
-- instead of posting twice (see publish/instagram.py).
CREATE TABLE publications (
    id                INTEGER PRIMARY KEY,
    content_item_id   INTEGER NOT NULL REFERENCES content_items(id),
    revision_id       INTEGER NOT NULL REFERENCES revisions(id),
    brand_id          INTEGER NOT NULL REFERENCES brands(id),
    platform          TEXT NOT NULL CHECK (platform IN ('instagram', 'tiktok', 'facebook', 'youtube')),
    account_id        INTEGER NOT NULL REFERENCES accounts(id),
    idempotency_key   TEXT NOT NULL UNIQUE,
    platform_media_id TEXT,
    permalink         TEXT,
    published_at      TEXT NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('published', 'failed')),
    error             TEXT
);

CREATE INDEX idx_publications_brand_time ON publications(brand_id, published_at);
CREATE INDEX idx_publications_content_item ON publications(content_item_id);

CREATE TABLE metrics_snapshots (
    id              INTEGER PRIMARY KEY,
    publication_id  INTEGER NOT NULL REFERENCES publications(id),
    captured_at     TEXT NOT NULL,
    views           INTEGER,
    likes           INTEGER,
    comments        INTEGER,
    shares          INTEGER,
    saves           INTEGER,
    reach           INTEGER,
    conversions     INTEGER,
    UNIQUE (publication_id, captured_at)
);

CREATE INDEX idx_metrics_publication ON metrics_snapshots(publication_id);

-- Append-only audit log. Every trendstealer.states.transition() call writes
-- exactly one row here in the same transaction as the status UPDATE.
CREATE TABLE status_events (
    id               INTEGER PRIMARY KEY,
    content_item_id  INTEGER NOT NULL REFERENCES content_items(id),
    from_status      TEXT,
    to_status        TEXT NOT NULL,
    actor            TEXT NOT NULL,
    note             TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_status_events_item ON status_events(content_item_id, created_at);

-- Cost / quota ledger across every paid external service.
CREATE TABLE api_usage (
    id           INTEGER PRIMARY KEY,
    brand_id     INTEGER REFERENCES brands(id),
    service      TEXT NOT NULL CHECK (service IN ('apify', 'anthropic', 'instagram')),
    operation    TEXT NOT NULL,
    units        REAL NOT NULL,
    unit_kind    TEXT NOT NULL,
    cost_usd     REAL,
    recorded_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_api_usage_service_time ON api_usage(service, recorded_at);
CREATE INDEX idx_api_usage_brand_time ON api_usage(brand_id, recorded_at);
