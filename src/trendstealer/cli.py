from __future__ import annotations

import os
import sqlite3
from typing import TYPE_CHECKING, NamedTuple

import typer

from trendstealer import db, repo
from trendstealer.config import get_settings, list_brand_ids, load_app_config, load_brand_config

if TYPE_CHECKING:
    from trendstealer.commands.publish import PublishOutcome

app = typer.Typer(no_args_is_help=True, add_completion=False)
db_app = typer.Typer(no_args_is_help=True)
brands_app = typer.Typer(no_args_is_help=True)
review_app = typer.Typer(no_args_is_help=True)
ingest_app = typer.Typer(no_args_is_help=True)
worker_app = typer.Typer(no_args_is_help=True)
generate_app = typer.Typer(no_args_is_help=True)
publish_app = typer.Typer(no_args_is_help=True)
metrics_app = typer.Typer(no_args_is_help=True)
maintenance_app = typer.Typer(no_args_is_help=True)
assets_app = typer.Typer(no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(brands_app, name="brands")
app.add_typer(review_app, name="review")
app.add_typer(ingest_app, name="ingest")
app.add_typer(worker_app, name="worker")
app.add_typer(generate_app, name="generate")
app.add_typer(publish_app, name="publish")
app.add_typer(metrics_app, name="metrics")
app.add_typer(maintenance_app, name="maintenance")
app.add_typer(assets_app, name="assets")


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Apply any pending migrations."""
    conn = db.connect()
    applied = db.upgrade(conn)
    if applied:
        typer.echo(f"applied {len(applied)} migration(s): {', '.join(applied)}")
    else:
        typer.echo("schema already up to date")


@db_app.command("check")
def db_check() -> None:
    """Exit 1 if there are unapplied migrations. Applies nothing."""
    conn = db.connect()
    pending = db.check(conn)
    if pending:
        typer.echo(f"pending migrations: {', '.join(pending)}")
        raise typer.Exit(code=1)
    typer.echo("schema up to date")


@brands_app.command("add")
def brands_add(brand_key: str) -> None:
    """Register a brand from config/brands/<brand_key>.toml into the database."""
    brand_config = load_brand_config(brand_key)
    conn = db.connect()
    brand_id = repo.upsert_brand(conn, brand_key, brand_config.brand.name)
    typer.echo(f"brand '{brand_key}' -> id {brand_id}")


@brands_app.command("list")
def brands_list() -> None:
    """List brand configs on disk and whether each is registered in the database."""
    conn = db.connect()
    registered = {row["brand_key"] for row in repo.list_brands(conn)}
    for brand_key in list_brand_ids():
        marker = "registered" if brand_key in registered else "not registered"
        typer.echo(f"{brand_key}  ({marker})")


@app.command("status")
def status() -> None:
    """Print content_items counts grouped by pipeline status."""
    conn = db.connect()
    counts = repo.count_content_items_by_status(conn)
    if not counts:
        typer.echo("no content items yet")
        return
    width = max(len(k) for k in counts)
    for state, n in sorted(counts.items()):
        typer.echo(f"{state.ljust(width)}  {n}")


@review_app.command("serve")
def review_serve(host: str | None = None, port: int | None = None) -> None:
    """Run the review dashboard (production WSGI server, not Flask's dev server)."""
    from waitress import serve as waitress_serve

    from trendstealer.review.app import create_app

    settings = get_settings()
    if not settings.review_dashboard_token:
        typer.echo("REVIEW_DASHBOARD_TOKEN is not set", err=True)
        raise typer.Exit(code=1)

    bind_host = host or settings.review_dashboard_host
    bind_port = port or settings.review_dashboard_port
    flask_app = create_app(
        db_path=settings.db_path_abs,
        render_root=settings.var_dir_abs / "work",
        token=settings.review_dashboard_token,
        secret_key=settings.flask_secret_key,
        allowed_hosts={f"{bind_host}:{bind_port}", f"localhost:{bind_port}"},
    )
    waitress_serve(flask_app, host=bind_host, port=bind_port)


@ingest_app.command("run")
def ingest_run(brand_key: str, dry_run: bool = False) -> None:
    """Scrape trending videos for a brand and queue survivors of the virality gate."""
    from trendstealer.commands.ingest import run_ingest
    from trendstealer.ingest.apify_backend import LiveApifyBackend
    from trendstealer.ingest.backend import ApifyBackend
    from trendstealer.ingest.fixture_backend import ApifyFixtureBackend

    settings = get_settings()
    app_config = load_app_config()
    brand = load_brand_config(brand_key, app_config=app_config)

    conn = db.connect()
    brand_id = repo.upsert_brand(conn, brand_key, brand.brand.name)

    backend: ApifyBackend
    if settings.apify_mode == "live":
        if not settings.apify_api_token:
            typer.echo("APIFY_API_TOKEN is not set", err=True)
            raise typer.Exit(code=1)
        backend = LiveApifyBackend(settings.apify_api_token)
    else:
        backend = ApifyFixtureBackend()

    summary = run_ingest(
        conn,
        brand=brand,
        brand_id=brand_id,
        app_config=app_config,
        backend=backend,
        dry_run=dry_run,
    )
    typer.echo(
        f"trends_seen={summary.trends_seen} items_new={summary.items_new} "
        f"items_backfilled={summary.items_backfilled} items_skipped={summary.items_skipped}"
    )


@worker_app.command("run-once")
def worker_run_once(brand_key: str) -> None:
    """Claim and fully process one item (synthesize/render/whatever stage
    it's at). Prints nothing and exits 0 if there was nothing to claim."""
    from trendstealer.commands.worker import (
        WorkerBusyError,
        build_backends,
        run_worker_once,
        worker_lock,
    )

    settings = get_settings()
    app_config = load_app_config()
    brand = load_brand_config(brand_key, app_config=app_config)

    try:
        with worker_lock(settings.var_dir_abs):
            conn = db.connect()
            llm_backend, tts_backend, worker_id = build_backends(settings, app_config)
            item_id = run_worker_once(
                conn,
                brand=brand,
                llm_backend=llm_backend,
                tts_backend=tts_backend,
                worker_id=worker_id,
                lease_ttl_seconds=app_config.worker.lease_ttl_seconds,
            )
    except WorkerBusyError:
        typer.echo("another worker run is already in progress, skipping", err=True)
        raise typer.Exit(code=0) from None

    if item_id is not None:
        typer.echo(f"processed item {item_id}")


@generate_app.command("now")
def generate_now(
    brand_key: str,
    item_id: int | None = None,
    skip_ingest: bool = False,
) -> None:
    """Ingest, then render one item immediately -- the manual alternative to
    waiting for viral-worker.timer. Prints the rendered MP4 path."""
    from trendstealer.commands.worker import (
        WorkerBusyError,
        build_backends,
        run_worker_once,
        worker_lock,
    )

    settings = get_settings()
    app_config = load_app_config()
    brand = load_brand_config(brand_key, app_config=app_config)

    if not skip_ingest and item_id is None:
        ingest_run(brand_key)

    try:
        with worker_lock(settings.var_dir_abs):
            conn = db.connect()
            llm_backend, tts_backend, worker_id = build_backends(settings, app_config)
            processed = run_worker_once(
                conn,
                brand=brand,
                llm_backend=llm_backend,
                tts_backend=tts_backend,
                worker_id=worker_id,
                lease_ttl_seconds=app_config.worker.lease_ttl_seconds,
                item_id=item_id,
            )
    except WorkerBusyError:
        typer.echo(
            "another worker run is already in progress -- "
            "wait for it to finish, or stop viral-worker.timer",
            err=True,
        )
        raise typer.Exit(code=1) from None

    if processed is None:
        if item_id is not None:
            typer.echo(
                f"item {item_id} is not claimable (wrong status, or another worker holds it)",
                err=True,
            )
        elif settings.apify_mode == "fixture":
            typer.echo(
                "nothing to generate: no queued items, and ingest is in fixture mode so it "
                "replays the same recorded trends every run (all of which already have items). "
                "Set TRENDSTEALER_APIFY_MODE=live with APIFY_API_TOKEN to discover new ones.",
                err=True,
            )
        else:
            typer.echo(
                "nothing to generate: no queued items, and every trend the scrape returned "
                "was already recorded. The seed accounts may not have posted anything new "
                "since the last run -- check `trendstealer status` for items already awaiting "
                "review.",
                err=True,
            )
        raise typer.Exit(code=1)

    conn = db.connect()
    detail = repo.get_content_item(conn, processed)
    revision = repo.get_revision(conn, detail["current_revision_id"]) if detail else None
    typer.echo(f"item {processed}: {detail['status'] if detail else 'unknown'}")
    if revision and revision["video_path"]:
        typer.echo(revision["video_path"])


def _echo_outcome(outcome: PublishOutcome) -> None:
    typer.echo(
        f"item {outcome.item_id}: {outcome.status}"
        + (f" ({outcome.reason})" if outcome.reason else "")
    )


@publish_app.command("run")
def publish_run(brand_key: str) -> None:
    """Rate-gate then publish at most one approved item to Instagram.

    This is what viral-publish.service calls. It has no override flag by
    design -- the forced path is a separate command, so no edit to a unit
    file can make a timer bypass the rate limiter.
    """
    from trendstealer.commands.publish import (
        MissingCredentialsError,
        build_publisher,
        run_publish_once,
    )

    settings = get_settings()
    app_config = load_app_config()
    brand = load_brand_config(brand_key, app_config=app_config)

    conn = db.connect()
    brand_id = repo.upsert_brand(conn, brand_key, brand.brand.name)

    try:
        publisher, access_token, business_account_id = build_publisher(settings, brand)
    except MissingCredentialsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    account_id = repo.upsert_account(
        conn, brand_id=brand_id, platform="instagram", platform_account_id=business_account_id
    )

    outcome = run_publish_once(
        conn,
        brand=brand,
        brand_id=brand_id,
        account_id=account_id,
        publisher=publisher,
        access_token=access_token,
    )
    if outcome is None:
        typer.echo("nothing to publish this run")
    else:
        _echo_outcome(outcome)


@publish_app.command("now")
def publish_now(
    brand_key: str,
    item_id: int | None = None,
    yes: bool = False,
) -> None:
    """Publish an approved item immediately, skipping the rate limiter.

    Bypasses the posting windows, the minimum gap, and the daily cap. The
    review gate is untouched: only an `approved` item can go, preflight
    still runs, and the idempotency key still prevents a double-post. The
    bypass is recorded in status_events.
    """
    from trendstealer.commands.publish import (
        ItemNotPublishableError,
        MissingCredentialsError,
        build_publisher,
        run_publish_once,
    )

    settings = get_settings()
    app_config = load_app_config()
    brand = load_brand_config(brand_key, app_config=app_config)

    conn = db.connect()
    brand_id = repo.upsert_brand(conn, brand_key, brand.brand.name)

    try:
        publisher, access_token, business_account_id = build_publisher(settings, brand)
    except MissingCredentialsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    target = _describe_publish_target(conn, brand_id=brand_id, item_id=item_id)
    if target is None:
        typer.echo("nothing approved to publish", err=True)
        raise typer.Exit(code=1)

    mode = "LIVE post to" if settings.publish_mode == "live" else "dry-run against"
    typer.echo(f"item {target.id}: {target.hook}")
    typer.echo(f"  -> {mode} account {business_account_id}")
    if not yes and not typer.confirm("publish it now, skipping the rate limiter?"):
        typer.echo("aborted")
        raise typer.Exit(code=1)

    account_id = repo.upsert_account(
        conn, brand_id=brand_id, platform="instagram", platform_account_id=business_account_id
    )

    try:
        outcome = run_publish_once(
            conn,
            brand=brand,
            brand_id=brand_id,
            account_id=account_id,
            publisher=publisher,
            access_token=access_token,
            enforce_rate_limit=False,
            item_id=target.id,
            actor="publisher:forced",
            note="rate limiter bypassed via `publish now`",
        )
    except ItemNotPublishableError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if outcome is None:
        typer.echo("nothing to publish", err=True)
        raise typer.Exit(code=1)
    _echo_outcome(outcome)


class _PublishTarget(NamedTuple):
    id: int
    hook: str
    status: str


def _describe_publish_target(
    conn: sqlite3.Connection, *, brand_id: int, item_id: int | None
) -> _PublishTarget | None:
    """The one-line summary shown before the confirmation prompt."""
    if item_id is None:
        approved = repo.list_approved_items(conn, brand_id=brand_id)
        if not approved:
            return None
        item = approved[0]
    else:
        found = repo.get_content_item(conn, item_id)
        if found is None:
            return None
        item = found

    revision = repo.get_revision(conn, item["current_revision_id"])
    hook = revision["on_screen_hook"] if revision else "(no revision)"
    return _PublishTarget(id=item["id"], hook=hook, status=item["status"])


@metrics_app.command("run")
def metrics_run(brand_key: str) -> None:
    """Snapshot Instagram insights for published items due for a refresh."""
    import httpx

    from trendstealer.commands.metrics import run_metrics_once
    from trendstealer.metrics.instagram_insights import (
        GRAPH_API_BASE,
        MediaInsights,
        fetch_media_insights,
    )

    settings = get_settings()
    app_config = load_app_config()
    brand = load_brand_config(brand_key, app_config=app_config)

    conn = db.connect()
    brand_id = repo.upsert_brand(conn, brand_key, brand.brand.name)
    access_token = brand.instagram_access_token()

    if settings.publish_mode == "live" and access_token:
        client = httpx.Client(timeout=30.0)
        graph_api_base = os.environ.get("TRENDSTEALER_GRAPH_API_BASE", GRAPH_API_BASE)

        def fetch(media_id: str) -> MediaInsights:
            return fetch_media_insights(
                media_id=media_id,
                access_token=access_token,
                client=client,
                graph_api_base=graph_api_base,
            )
    else:

        def fetch(media_id: str) -> MediaInsights:
            return MediaInsights()

    count = run_metrics_once(conn, brand_id=brand_id, fetch_insights=fetch)
    typer.echo(f"recorded {count} snapshot(s)")


@maintenance_app.command("gc")
def maintenance_gc(max_pending_review_hours: int = 48, retention_days: int = 30) -> None:
    """Auto-archive stale pending_review items and delete render artifacts
    for old terminal-state items."""
    from trendstealer.commands.maintenance import (
        auto_archive_stale_pending_review,
        gc_render_artifacts,
    )

    settings = get_settings()
    conn = db.connect()
    archived = auto_archive_stale_pending_review(conn, max_age_hours=max_pending_review_hours)
    removed = gc_render_artifacts(
        conn, render_root=settings.var_dir_abs / "work", retention_days=retention_days
    )
    typer.echo(f"archived {archived} stale item(s), removed {removed} render artifact dir(s)")


@maintenance_app.command("backup")
def maintenance_backup(keep_last: int = 14) -> None:
    """Back up the database via SQLite's online backup API (safe under WAL,
    unlike a plain file copy)."""
    from trendstealer.commands.maintenance import backup_database

    settings = get_settings()
    result = backup_database(
        settings.db_path_abs, settings.var_dir_abs / "backups", keep_last=keep_last
    )
    typer.echo(f"backed up to {result.path} ({result.size_bytes} bytes)")


@maintenance_app.command("check-token")
def maintenance_check_token(brand_key: str, warn_days: int = 7) -> None:
    """Check IG access token validity/expiry via Graph API's debug_token."""
    import httpx

    from trendstealer.commands.maintenance import check_token_expiry

    app_config = load_app_config()
    brand = load_brand_config(brand_key, app_config=app_config)
    access_token = brand.instagram_access_token()
    if not access_token:
        typer.echo("no IG access token configured for this brand", err=True)
        raise typer.Exit(code=1)

    status = check_token_expiry(access_token=access_token, client=httpx.Client(timeout=30.0))
    if not status.is_valid:
        typer.echo("token is INVALID", err=True)
        raise typer.Exit(code=1)
    if status.days_remaining is not None and status.days_remaining < warn_days:
        typer.echo(f"token expires in {status.days_remaining:.1f} day(s) -- refresh it", err=True)
        raise typer.Exit(code=1)
    typer.echo("token OK")


@app.command("healthz")
def healthz() -> None:
    """Exit 0 if the DB is reachable and migrations are current, else 1."""
    try:
        conn = db.connect()
        pending = db.check(conn)
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"unhealthy: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if pending:
        typer.echo(f"unhealthy: pending migrations {pending}", err=True)
        raise typer.Exit(code=1)
    typer.echo("ok")


@assets_app.command("fetch-pexels")
def assets_fetch_pexels(
    query: str,
    count: int = 5,
    tags: str | None = None,
) -> None:
    """Download stock B-roll from Pexels and register it as cleared."""
    from trendstealer.commands.assets import fetch_pexels_broll

    settings = get_settings()
    if not settings.pexels_api_key:
        typer.echo("PEXELS_API_KEY is not set (free at https://www.pexels.com/api/)", err=True)
        raise typer.Exit(code=1)

    conn = db.connect()
    summary = fetch_pexels_broll(
        conn, query=query, api_key=settings.pexels_api_key, count=count, tags=tags
    )
    typer.echo(
        f"found={summary.found} downloaded={summary.downloaded} registered={summary.registered}"
    )


@assets_app.command("add")
def assets_add(
    path: str,
    kind: str = "video",
    license: str = "unknown",  # noqa: A002 - matches the column name
    tags: str | None = None,
    attribution: str | None = None,
    cleared: bool = False,
) -> None:
    """Register a file already under assets/ (own footage, licensed media)."""
    from pathlib import Path as _Path

    from trendstealer.commands.assets import register_local_asset

    conn = db.connect()
    try:
        asset_id = register_local_asset(
            conn,
            path=_Path(path),
            kind=kind,
            license=license,
            tags=tags,
            attribution=attribution,
            cleared_for_commercial=cleared,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"asset {asset_id}: {path} (cleared={cleared})")


@assets_app.command("list")
def assets_list(kind: str | None = None, all_assets: bool = False) -> None:
    """Show registered assets, least-recently-used first."""
    conn = db.connect()
    rows = repo.list_assets(conn, kind=kind, cleared_only=not all_assets, limit=200)
    if not rows:
        typer.echo("no assets registered")
        return
    for row in rows:
        flag = "cleared" if row["cleared_for_commercial"] else "UNCLEARED"
        used = row["last_used_at"] or "never used"
        typer.echo(f"{row['id']:>4}  {flag:<9}  {row['kind']:<5}  {row['path']}  ({used})")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
