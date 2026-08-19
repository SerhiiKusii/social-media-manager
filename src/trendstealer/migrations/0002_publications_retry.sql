-- publications.idempotency_key was UNIQUE unconditionally, which conflated
-- two different things: "never publish the same revision twice" (the real
-- invariant) and "never *attempt* the same revision twice". A failed
-- attempt wrote a row holding the key, so every subsequent retry of that
-- item died on IntegrityError -- and because the success-path INSERT runs
-- *after* the Graph API call, that failure landed with the Reel already
-- live and no publications row recording it.
--
-- The invariant we want is at most one row per key with status='published',
-- which is exactly a partial unique index. Failed attempts stay recorded
-- (they are the audit trail for publications.error) but no longer block a
-- retry.
--
-- SQLite cannot drop a column-level UNIQUE, so the table is rebuilt.

CREATE TABLE publications_new (
    id                INTEGER PRIMARY KEY,
    content_item_id   INTEGER NOT NULL REFERENCES content_items(id),
    revision_id       INTEGER NOT NULL REFERENCES revisions(id),
    brand_id          INTEGER NOT NULL REFERENCES brands(id),
    platform          TEXT NOT NULL CHECK (platform IN ('instagram', 'tiktok', 'facebook', 'youtube')),
    account_id        INTEGER NOT NULL REFERENCES accounts(id),
    idempotency_key   TEXT NOT NULL,
    platform_media_id TEXT,
    permalink         TEXT,
    published_at      TEXT NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('published', 'failed')),
    error             TEXT
);

INSERT INTO publications_new
    SELECT id, content_item_id, revision_id, brand_id, platform, account_id,
           idempotency_key, platform_media_id, permalink, published_at, status, error
    FROM publications;

DROP TABLE publications;

ALTER TABLE publications_new RENAME TO publications;

CREATE INDEX idx_publications_brand_time ON publications(brand_id, published_at);

CREATE INDEX idx_publications_content_item ON publications(content_item_id);

CREATE UNIQUE INDEX idx_publications_published_once
    ON publications(idempotency_key) WHERE status = 'published';
