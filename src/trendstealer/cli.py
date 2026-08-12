from __future__ import annotations

import typer

from trendstealer import db, repo
from trendstealer.config import list_brand_ids, load_brand_config

app = typer.Typer(no_args_is_help=True, add_completion=False)
db_app = typer.Typer(no_args_is_help=True)
brands_app = typer.Typer(no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(brands_app, name="brands")


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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
