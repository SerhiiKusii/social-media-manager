from __future__ import annotations

import typer

from trendstealer import db, repo
from trendstealer.config import get_settings, list_brand_ids, load_app_config, load_brand_config

app = typer.Typer(no_args_is_help=True, add_completion=False)
db_app = typer.Typer(no_args_is_help=True)
brands_app = typer.Typer(no_args_is_help=True)
review_app = typer.Typer(no_args_is_help=True)
ingest_app = typer.Typer(no_args_is_help=True)
worker_app = typer.Typer(no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(brands_app, name="brands")
app.add_typer(review_app, name="review")
app.add_typer(ingest_app, name="ingest")
app.add_typer(worker_app, name="worker")


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
        f"items_skipped={summary.items_skipped}"
    )


@worker_app.command("run-once")
def worker_run_once(brand_key: str) -> None:
    """Claim and fully process one item (synthesize/render/whatever stage
    it's at). Prints nothing and exits 0 if there was nothing to claim."""
    import fcntl
    import os
    import socket

    from trendstealer.commands.worker import run_worker_once
    from trendstealer.intelligence.synthesize import get_backend
    from trendstealer.tts.piper import PiperBackend

    settings = get_settings()
    app_config = load_app_config()
    brand = load_brand_config(brand_key, app_config=app_config)

    lock_dir = settings.var_dir_abs / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = open(lock_dir / "worker.lock", "w")  # noqa: SIM115 - held for process lifetime
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        typer.echo("another worker run is already in progress, skipping", err=True)
        raise typer.Exit(code=0) from None

    conn = db.connect()
    llm_backend = get_backend(
        settings.llm_backend,
        model=app_config.intelligence.model,
        max_tokens=app_config.intelligence.max_tokens,
    )
    tts_backend = PiperBackend(
        target_lufs=app_config.tts.target_lufs, sample_rate_hz=app_config.tts.sample_rate_hz
    )
    worker_id = f"{socket.gethostname()}:{os.getpid()}"

    item_id = run_worker_once(
        conn,
        brand=brand,
        llm_backend=llm_backend,
        tts_backend=tts_backend,
        worker_id=worker_id,
        lease_ttl_seconds=app_config.worker.lease_ttl_seconds,
    )
    if item_id is not None:
        typer.echo(f"processed item {item_id}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
