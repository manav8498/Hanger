from __future__ import annotations

import asyncio
import os

import typer

from hangar.auth.keys import create_api_key
from hangar.db.models import Base
from hangar.db.session import make_engine, make_sessionmaker
from hangar.store import PostgresStore

app = typer.Typer(help="Hangar control plane CLI.")
admin_app = typer.Typer(help="Administrative commands.")
app.add_typer(admin_app, name="admin")


@admin_app.command("create-api-key")
def create_admin_api_key(
    name: str = typer.Option(..., "--name"),
    admin_token: str = typer.Option(..., "--admin-token", envvar="HANGAR_ADMIN_TOKEN"),
) -> None:
    expected = os.environ.get("HANGAR_ADMIN_TOKEN")
    if expected is not None and admin_token != expected:
        raise typer.BadParameter("admin token does not match HANGAR_ADMIN_TOKEN")

    created = asyncio.run(_create_key(name))
    typer.echo(created)


async def _create_key(name: str) -> str:
    engine = make_engine()
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        store = PostgresStore(make_sessionmaker(engine))
        created = create_api_key(name)
        await store.create_api_key(created.id, name, created.hashed_key)
        return created.raw_key
    finally:
        await engine.dispose()
